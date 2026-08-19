#!/usr/bin/env python3
import hashlib
import html
import ipaddress
import json
import os
import queue
import re
import secrets
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from audit_store import AuditStore, bounded_text
from bark_secret_store import BarkSecretStore
from diagnostic_store import DiagnosticStore
from device_store import DeviceStore, PairingClaimRateLimited
from qr_code import png_base64
from storage_security import (
    append_private,
    atomic_write_private,
    ensure_private_directory,
    ensure_private_file,
)

os.umask(0o077)

PORT = int(os.environ.get("PORT", "8787"))
HOST = os.environ.get("HOST", "127.0.0.1")
try:
    if not ipaddress.ip_address(HOST).is_loopback:
        raise RuntimeError("XXZF server must bind to a loopback address")
except ValueError as exc:
    raise RuntimeError("XXZF server HOST must be a numeric loopback address") from exc
DEFAULT_DATA_DIR = Path.home() / "Library" / "Application Support" / "XXZF" / "server-data"
DATA_DIR = Path(os.environ.get("DATA_DIR", str(DEFAULT_DATA_DIR))).expanduser()
CONFIG_FILE = DATA_DIR / "config.json"
ERROR_LOG = DATA_DIR / "server-errors.log"
DEFAULT_APK_FILE = (
    Path(__file__).resolve().parent.parent / "dist" / "NotifyBridge-release.apk"
)
APK_FILE = Path(os.environ.get("XXZF_APK_FILE", str(DEFAULT_APK_FILE))).expanduser()
WINDOWS_SSH_INSTALLER = (
    Path(__file__).resolve().parent.parent
    / "tools"
    / "OpenSSH-Win64-v10.0.0.0.msi"
)
TOKEN_FILE = Path(os.environ.get("XXZF_TOKEN_FILE", DATA_DIR / "notify-token.txt"))
MAC_NOTIFIER_APP = Path.home() / "Applications/转发.app"
DEVICE_DB = DATA_DIR / "devices.sqlite3"
AUDIT_DIR = Path(os.environ.get("XXZF_AUDIT_DIR", DATA_DIR / "notification_archive"))
AUDIT_TEMPLATE = Path(__file__).resolve().parent / "audit_index.html"
DIAGNOSTIC_DIR = Path(os.environ.get(
    "XXZF_DIAGNOSTIC_DIR", DATA_DIR / "diagnostics"
))
BARK_SECRET_FILE = Path(os.environ.get(
    "XXZF_BARK_SECRET_FILE", DATA_DIR / "bark-secrets.json"
))
PUBLIC_BASE = os.environ.get(
    "XXZF_PUBLIC_BASE", "https://example.com/xxzf"
).rstrip("/")
BARK_BIND_PAGE = os.environ.get(
    "XXZF_BARK_BIND_PAGE", "https://example.com/xxzf/bark/"
)
PUBLIC_ORIGIN = os.environ.get(
    "XXZF_PUBLIC_ORIGIN", "https://example.com:8443"
).rstrip("/")
BARK_ENROLLMENT_PUBLIC_ERROR = "绑定码无效、已过期或已使用，请重新生成"
PAIRING_PUBLIC_ERROR = "配对码无效、已过期或已使用，请重新生成"
PAIRING_RATE_LIMIT_ERROR = "配对尝试过于频繁，请稍后重试"
PAIRING_INTERNAL_ERROR = "配对服务暂时不可用"
MAX_EVENTS = 200
MAX_RECEIVER_STREAMS_PER_DEVICE = 4
MAX_RECEIVER_STREAMS_PER_CLIENT_IP = 8
MAX_EVENT_STREAMS_GLOBAL = 128
MAX_LOCAL_LEGACY_STREAMS = 4
EVENT_STREAM_QUEUE_SIZE = 32
EVENT_STREAM_WRITE_TIMEOUT_SECONDS = 20
PAIR_START_GLOBAL_LIMIT = 120
ERROR_LOG_MAX_BYTES = 5 * 1024 * 1024
ERROR_LOG_BACKUP_COUNT = 3
TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")
SERVICE_STARTED_AT = int(time.time() * 1000)
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
LOCAL_MANAGEMENT_POST_PATHS = frozenset({
    "/api/config",
    "/api/devices/revoke",
    "/api/devices/rate",
    "/api/test",
})
JSON_POST_PATHS = frozenset({
    "/api/notify",
    "/api/pair/start",
    "/api/pair/claim",
    "/api/v1/bark/enroll/start",
    "/api/v1/bark/enroll/claim",
    "/api/v1/bark/test",
    "/api/v1/bark/revoke",
    "/api/v1/receiver/senders/revoke",
    "/api/v1/device/revoke",
    "/api/v1/notify",
    "/api/v1/diagnostics",
    "/api/config",
    "/api/devices/revoke",
    "/api/devices/rate",
})


class UnsupportedMediaTypeError(Exception):
    pass


def normalized_host_header(value):
    raw = str(value or "").strip()
    if not raw or any(ord(character) < 0x20 or ord(character) == 0x7F for character in raw):
        return ""
    try:
        parsed = urllib.parse.urlsplit("//" + raw)
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            return ""
        # Accessing port validates malformed values such as non-numeric ports.
        parsed.port
        hostname = (parsed.hostname or "").rstrip(".").lower()
        return hostname.encode("idna").decode("ascii")
    except (TypeError, ValueError, UnicodeError):
        return ""


def public_request_hosts():
    hosts = set(LOOPBACK_HOSTS)
    for value in (PUBLIC_ORIGIN, PUBLIC_BASE):
        hostname = normalized_host_header(urllib.parse.urlparse(value).netloc)
        if hostname:
            hosts.add(hostname)
            if not hostname.startswith("www."):
                hosts.add("www." + hostname)
    return frozenset(hosts)


PUBLIC_REQUEST_HOSTS = public_request_hosts()


def script_safe_json(value):
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def canonical_https_origin(value):
    raw = str(value or "").strip().rstrip("/")
    try:
        parsed = urllib.parse.urlparse(raw)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid HTTPS origin") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid HTTPS origin")
    hostname = parsed.hostname.rstrip(".").lower().encode("idna").decode("ascii")
    if ":" in hostname:
        hostname = "[" + hostname + "]"
    return "https://%s%s" % (hostname, "" if port in (None, 443) else ":%d" % port)


def configured_bark_allowed_origins():
    configured = os.environ.get("XXZF_BARK_ALLOWED_ORIGINS", "https://api.day.app")
    origins = set()
    for value in configured.split(","):
        if value.strip():
            origins.add(canonical_https_origin(value))
    if not origins:
        raise RuntimeError("at least one Bark HTTPS origin is required")
    return frozenset(origins)


BARK_ALLOWED_ORIGINS = configured_bark_allowed_origins()


def normalize_bark_server(value):
    origin = canonical_https_origin(value or "https://api.day.app")
    if origin not in BARK_ALLOWED_ORIGINS:
        raise ValueError("Bark server is not allowlisted")
    return origin


def load_notify_token(path):
    path = Path(path)
    ensure_private_directory(path.parent)
    if not ensure_private_file(path, required=False):
        raise RuntimeError("legacy notify token file is required")
    try:
        if path.stat().st_size > 4096:
            raise RuntimeError("legacy notify token is invalid")
        token = path.read_text("utf-8").strip()
    except OSError as exc:
        raise RuntimeError("legacy notify token file is unreadable") from exc
    is_hex = bool(re.fullmatch(r"[A-Fa-f0-9]{48,128}", token))
    is_urlsafe = bool(re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token))
    distinct_required = 10 if is_hex else 16
    if not (is_hex or is_urlsafe) or len(set(token)) < distinct_required:
        raise RuntimeError("legacy notify token is missing or weak")
    return token

ensure_private_directory(DATA_DIR)
ensure_private_file(CONFIG_FILE, required=False)
ensure_private_file(ERROR_LOG, required=False)

NOTIFY_TOKEN = load_notify_token(TOKEN_FILE)


class EventStreamConnection:
    """A bounded SSE mailbox drained by exactly one request-handler thread."""

    def __init__(
        self,
        wfile,
        *,
        client_ip,
        receiver_id=None,
        legacy=False,
        queue_size=EVENT_STREAM_QUEUE_SIZE,
    ):
        self.wfile = wfile
        self.client_ip = str(client_ip or "")
        self.receiver_id = receiver_id
        self.legacy = bool(legacy)
        self.messages = queue.Queue(maxsize=max(1, int(queue_size)))
        self.closed = threading.Event()
        self._writer_claim = threading.Lock()

    def enqueue(self, payload):
        """Queue without blocking a notifier thread or writing to the network."""
        if self.closed.is_set():
            return False
        try:
            self.messages.put_nowait(payload)
            return True
        except queue.Full:
            self.close()
            return False

    def close(self):
        if self.closed.is_set():
            return
        self.closed.set()
        try:
            self.messages.put_nowait(None)
        except queue.Full:
            # A full mailbox is already enough to wake/terminate the writer
            # after its current write completes.
            pass

    def run_writer(self, keepalive_seconds=15):
        """Drain this connection from one thread; never call under ``lock``."""
        if not self._writer_claim.acquire(blocking=False):
            raise RuntimeError("event stream already has a writer")
        try:
            self.wfile.write(b"event: hello\ndata: {\"ok\": true}\n\n")
            self.wfile.flush()
            while not self.closed.is_set():
                try:
                    payload = self.messages.get(timeout=keepalive_seconds)
                except queue.Empty:
                    payload = b": keepalive\n\n"
                if payload is None or self.closed.is_set():
                    break
                self.wfile.write(payload)
                self.wfile.flush()
        finally:
            self.closed.set()
            self._writer_claim.release()


events = []
clients = set()
receiver_clients = {}
lock = threading.Lock()
rate_lock = threading.Lock()
error_log_lock = threading.Lock()
rate_windows = {}
device_store = DeviceStore(DEVICE_DB)
audit_store = AuditStore(AUDIT_DIR, AUDIT_TEMPLATE)
diagnostic_store = DiagnosticStore(DIAGNOSTIC_DIR)
bark_secret_store = BarkSecretStore(BARK_SECRET_FILE)


def delete_bark_secrets(destination_ids):
    """Delete selected credentials, failing the request if any erase fails."""
    failures = 0
    for destination_id in dict.fromkeys(destination_ids or []):
        try:
            bark_secret_store.delete(destination_id)
        except Exception:
            failures += 1
    if failures:
        raise RuntimeError("Bark credential cleanup failed")


def reconcile_revoked_bark_secrets():
    """Finish any DB-first credential deletion interrupted by an earlier run."""
    delete_bark_secrets(device_store.revoked_bark_destination_ids())


def revoke_bark_destination_and_secret(sender_id, destination_id):
    destination_ids = device_store.revoke_bark_destination_with_secrets(
        sender_id, destination_id
    )
    if not destination_ids:
        return False
    delete_bark_secrets(destination_ids)
    return True


def revoke_device_and_secrets(device_id):
    destination_ids = device_store.revoke_with_secrets(device_id)
    if destination_ids is None:
        return False
    close_unrouted_receiver_streams()
    delete_bark_secrets(destination_ids)
    return True


# Fail closed if a previously revoked destination's credential cannot be
# reconciled.  No key material or destination metadata is printed.
reconcile_revoked_bark_secrets()


def load_config():
    if not ensure_private_file(CONFIG_FILE, required=False):
        return {
            "barkEnabled": False,
            "barkServer": "https://api.day.app",
            "barkKey": "",
            "localMacNotify": True,
            "ownerSenderIds": [],
        }
    try:
        loaded = json.loads(CONFIG_FILE.read_text("utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("invalid config")
        loaded["barkServer"] = normalize_bark_server(loaded.get("barkServer"))
        loaded["barkEnabled"] = bool(loaded.get("barkEnabled"))
        loaded["barkKey"] = str(loaded.get("barkKey") or "")
        return loaded
    except Exception:
        return {
            "barkEnabled": False,
            "barkServer": "https://api.day.app",
            "barkKey": "",
            "localMacNotify": True,
            "ownerSenderIds": [],
        }


config = load_config()


def clean_repeated_title(title, text):
    title = (title or "").strip()
    text = (text or "").strip()
    if not title or not text:
        return text
    pattern = r"^(\[\d+条\])?\s*" + re.escape(title) + r"\s*[:：]\s*"
    match = re.match(pattern, text)
    if match:
        count = match.group(1) or ""
        remainder = text[match.end():].strip()
        return " ".join(part for part in (count, remainder) if part)
    return "" if text == title else text


def parse_bark_test_url(value):
    raw = str(value or "").strip()
    if len(raw) > 2048:
        raise ValueError("Bark 测试地址过长")
    try:
        parsed = urllib.parse.urlparse(raw)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Bark 测试地址无效") from exc
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() != "api.day.app"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise ValueError("仅支持 Bark 官方 HTTPS 测试地址")
    segments = [segment for segment in parsed.path.split("/") if segment]
    key = urllib.parse.unquote(segments[0]) if segments else ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,200}", key):
        raise ValueError("Bark 测试地址中的设备凭证无效")
    return "https://api.day.app", key


def bark_key_fingerprint(device_key):
    return hashlib.sha256(str(device_key).encode("utf-8")).hexdigest()[:10].upper()


def authorized(headers):
    value = headers.get("Authorization", "").strip()
    if not value.lower().startswith("bearer "):
        return False
    supplied = value[7:].strip()
    return bool(supplied) and secrets.compare_digest(supplied, NOTIFY_TOKEN)


def local_client_allowed(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local or ip in TAILSCALE_NET


def rate_allowed(key, limit, window_seconds=60):
    now = time.monotonic()
    with rate_lock:
        recent = [stamp for stamp in rate_windows.get(key, []) if now - stamp < window_seconds]
        if len(recent) >= limit:
            rate_windows[key] = recent
            return False
        recent.append(now)
        rate_windows[key] = recent
        if len(rate_windows) > 2000:
            cutoff = now - window_seconds
            for old_key in list(rate_windows):
                if not rate_windows[old_key] or rate_windows[old_key][-1] < cutoff:
                    rate_windows.pop(old_key, None)
        return True


def _all_event_streams_locked():
    streams = list(clients)
    for receiver_streams in receiver_clients.values():
        streams.extend(receiver_streams)
    return streams


def register_receiver_stream(wfile, receiver_id, client_ip):
    """Atomically enforce receiver, source-IP, and process-wide SSE limits."""
    with lock:
        active = receiver_clients.get(receiver_id, set())
        all_streams = _all_event_streams_locked()
        if len(active) >= MAX_RECEIVER_STREAMS_PER_DEVICE:
            return None, "receiver"
        if sum(
            1 for stream in all_streams
            if getattr(stream, "client_ip", None) == str(client_ip or "")
        ) >= MAX_RECEIVER_STREAMS_PER_CLIENT_IP:
            return None, "client_ip"
        if len(all_streams) >= MAX_EVENT_STREAMS_GLOBAL:
            return None, "global"
        stream = EventStreamConnection(
            wfile,
            client_ip=client_ip,
            receiver_id=receiver_id,
        )
        receiver_clients.setdefault(receiver_id, set()).add(stream)
        return stream, None


def register_legacy_stream(wfile, client_ip):
    with lock:
        all_streams = _all_event_streams_locked()
        if len(clients) >= MAX_LOCAL_LEGACY_STREAMS:
            return None, "local"
        if len(all_streams) >= MAX_EVENT_STREAMS_GLOBAL:
            return None, "global"
        stream = EventStreamConnection(
            wfile,
            client_ip=client_ip,
            legacy=True,
        )
        clients.add(stream)
        return stream, None


def unregister_event_stream(stream):
    """Remove a stream without touching its socket from this caller thread."""
    stream.close()
    with lock:
        if stream.legacy:
            clients.discard(stream)
            return
        active = receiver_clients.get(stream.receiver_id)
        if active is None:
            return
        active.discard(stream)
        if not active:
            receiver_clients.pop(stream.receiver_id, None)


def close_unrouted_receiver_streams():
    """Disconnect streams whose last active route was just revoked."""
    with lock:
        receiver_ids = list(receiver_clients)
    for receiver_id in receiver_ids:
        if device_store.receiver_has_active_route(receiver_id):
            continue
        with lock:
            stale_streams = list(receiver_clients.get(receiver_id, set()))
        for stream in stale_streams:
            unregister_event_stream(stream)


def _rotate_private_error_log(incoming_size):
    if not ensure_private_file(ERROR_LOG, required=False):
        return
    current_size = ERROR_LOG.stat().st_size
    if current_size + incoming_size <= ERROR_LOG_MAX_BYTES:
        return
    if current_size > ERROR_LOG_MAX_BYTES:
        # Do not preserve an unbounded file produced by an older version.
        ERROR_LOG.unlink()
        return
    oldest = ERROR_LOG.with_name(f"{ERROR_LOG.name}.{ERROR_LOG_BACKUP_COUNT}")
    if ensure_private_file(oldest, required=False):
        oldest.unlink()
    for index in range(ERROR_LOG_BACKUP_COUNT - 1, 0, -1):
        source = ERROR_LOG.with_name(f"{ERROR_LOG.name}.{index}")
        target = ERROR_LOG.with_name(f"{ERROR_LOG.name}.{index + 1}")
        if ensure_private_file(source, required=False):
            if source.stat().st_size > ERROR_LOG_MAX_BYTES:
                source.unlink()
            else:
                os.replace(source, target)
                ensure_private_file(target)
    first = ERROR_LOG.with_name(f"{ERROR_LOG.name}.1")
    os.replace(ERROR_LOG, first)
    ensure_private_file(first)


def record_internal_error(area, request_id, error):
    detail = " ".join(str(error).replace("\x00", " ").split())[:2000]
    entry = json.dumps({
        "at": int(time.time() * 1000),
        "requestId": request_id,
        "area": str(area)[:80],
        "type": error.__class__.__name__,
        "detail": detail,
    }, ensure_ascii=True, separators=(",", ":")) + "\n"
    with error_log_lock:
        _rotate_private_error_log(len(entry.encode("utf-8", "replace")))
        append_private(ERROR_LOG, entry.encode("utf-8", "replace"))


def audit_health_snapshot():
    stats = audit_store.stats()
    devices = device_store.list_devices()
    public_devices = {item["deviceId"]: item for item in devices}
    with lock:
        active_counts = {
            receiver_id: len(streams)
            for receiver_id, streams in receiver_clients.items()
            if streams
        }
    active_receivers = []
    for receiver_id, stream_count in active_counts.items():
        device = public_devices.get(receiver_id, {})
        active_receivers.append({
            "name": device.get("name") or "接收设备",
            "fingerprint": device.get("fingerprint") or "",
            "streams": stream_count,
        })
    active_devices = [item for item in devices if item.get("status") == "active"]
    return {
        "ok": True,
        "serverTime": int(time.time() * 1000),
        "startedAt": SERVICE_STARTED_AT,
        "latestEventAt": stats.get("newest"),
        "activeReceiverCount": len(active_receivers),
        "activeStreamCount": sum(active_counts.values()),
        "configuredSenderCount": sum(
            1 for item in active_devices if item.get("role") == "sender"
        ),
        "configuredReceiverCount": sum(
            1 for item in active_devices if item.get("role") == "receiver"
        ),
        "activeReceivers": active_receivers,
    }


def bearer_credentials(headers):
    value = headers.get("Authorization", "").strip()
    if not value.lower().startswith("bearer "):
        return "", ""
    token = value[7:].strip()
    if "." not in token:
        return "", ""
    return token.split(".", 1)


def pairing_qr_payload(code):
    query = urllib.parse.urlencode({"server": PUBLIC_BASE, "code": code})
    return f"xxzf://pair?{query}"


def save_config():
    atomic_write_private(
        CONFIG_FILE,
        json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8"),
    )


def normalize_event(data):
    return {
        "id": bounded_text(data.get("id") or f"{int(time.time() * 1000)}", 256),
        "receivedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "device": bounded_text(data.get("device") or "Android", 160),
        "packageName": bounded_text(data.get("packageName") or "", 256),
        "appName": bounded_text(data.get("appName") or data.get("packageName") or "Unknown App", 160),
        "title": bounded_text(data.get("title") or "", 1024),
        "text": bounded_text(data.get("text") or "", 8 * 1024),
        "postTime": int(data.get("postTime") or int(time.time() * 1000)),
        "privacyMode": bounded_text(data.get("privacyMode") or "full", 16),
    }


def push_event(event, receiver_ids=None, include_legacy=True):
    receiver_ids = set(receiver_ids or [])
    with lock:
        events.insert(0, event)
        del events[MAX_EVENTS:]
        payload = f"event: notify\ndata: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")
        targets = list(clients) if include_legacy else []
        for receiver_id in receiver_ids:
            targets.extend(receiver_clients.get(receiver_id, set()))

    # Queueing is bounded and non-blocking.  Crucially, no global registry
    # lock is held while an event-handler thread performs socket I/O.
    for stream in targets:
        if not stream.enqueue(payload):
            unregister_event_stream(stream)


def process_event(data, sender=None, legacy=False):
    event = normalize_event(data)
    # The normalized event already reflects the sender's selected privacy mode.
    # Never allow a client-controlled parallel archive payload to bypass it.
    archive_title = event["title"]
    archive_body = event["text"]
    desktop_destinations = (
        [] if legacy else device_store.destinations_for_sender(sender["device_id"])
    )
    bark_destinations = (
        [] if legacy else device_store.bark_destinations_for_sender(sender["device_id"])
    )
    destinations = desktop_destinations + bark_destinations
    owner_sender_ids = set(config.get("ownerSenderIds") or [])
    global_bark_available = bool(
        sender
        and sender["device_id"] in owner_sender_ids
        and config.get("barkEnabled")
        and config.get("barkKey")
    )
    if not legacy and not destinations and not global_bark_available:
        raise PermissionError("sender has no active destination")

    audit_store.record(
        event,
        sender=sender,
        destinations=destinations,
        archive_title=archive_title,
        archive_body=archive_body,
    )
    push_event(
        event,
        receiver_ids=[item["deviceId"] for item in desktop_destinations],
        include_legacy=legacy,
    )

    local_delivery = legacy or (sender and sender["device_id"] in owner_sender_ids)
    if local_delivery:
        queue_local_mac_notify(event)
    if bark_destinations:
        for destination in bark_destinations:
            queue_bark_destination(event, destination)
        bark = {"queued": True, "destinations": len(bark_destinations)}
    elif not local_delivery:
        bark = {"skipped": True}
    elif legacy:
        bark = public_bark_result(forward_bark(event))
    else:
        queue_bark(event)
        bark = {"queued": True}
    return event, destinations, bark


def local_mac_notify(event):
    if not config.get("localMacNotify"):
        return
    app = event.get("appName") or event.get("packageName") or "Android"
    source_title = event.get("title") or ""
    source_text = clean_repeated_title(source_title, event.get("text") or "")
    privacy = event.get("privacyMode") or "full"
    title = "转发：" + app
    if privacy == "source":
        body = ""
    elif privacy == "title":
        body = source_title
    else:
        body = "\n".join(part for part in (source_title, source_text) if part).strip()
    try:
        if MAC_NOTIFIER_APP.is_dir():
            executable = MAC_NOTIFIER_APP / "Contents" / "MacOS" / "转发"
            result = subprocess.run(
                [str(executable), "--notify", title[:120], body[:220]],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=12,
            )
            if result.returncode != 0:
                record_internal_error(
                    "local-notify",
                    secrets.token_hex(8),
                    RuntimeError("local notifier returned a non-zero status"),
                )
            return
        result = subprocess.run([
            "/usr/bin/osascript",
            "-e",
            "on run argv",
            "-e",
            "display notification (item 2 of argv) with title (item 1 of argv) sound name \"Glass\"",
            "-e",
            "end run",
            title[:120],
            body[:220],
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=8)
        if result.returncode != 0:
            record_internal_error(
                "local-notify",
                secrets.token_hex(8),
                RuntimeError("local notifier returned a non-zero status"),
            )
    except Exception as exc:
        record_internal_error("local-notify", secrets.token_hex(8), exc)


def queue_local_mac_notify(event):
    threading.Thread(target=local_mac_notify, args=(event,), daemon=True).start()


def send_bark(base, device_key, event):
    try:
        base = normalize_bark_server(base)
    except ValueError:
        return {"error": "invalid_server"}

    app = event.get("appName") or event.get("packageName") or "Android"
    source_title = event.get("title") or ""
    body = source_title or "收到一条新通知"

    payload = json.dumps({
        "device_key": str(device_key),
        "title": app,
        "body": body,
        "group": "转发",
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base + "/push",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read(500).decode("utf-8", "replace")
            return {"status": response.status, "body": raw}
    except Exception:
        # Do not persist arbitrary transport exception details here. Some HTTP
        # clients or test doubles can reflect request data in exception text;
        # Bark delivery logs must never retain Android notification content.
        record_internal_error(
            "bark-delivery",
            secrets.token_hex(8),
            RuntimeError("Bark transport request failed"),
        )
        return {"error": "delivery_failed"}


def forward_bark(event):
    if not config.get("barkEnabled") or not config.get("barkKey"):
        return {"skipped": True}
    return send_bark(
        config.get("barkServer") or "https://api.day.app",
        config.get("barkKey"),
        event,
    )


def public_bark_result(result):
    """Project internal Bark details to a fixed, non-reflective API shape."""
    if result.get("skipped"):
        return {"skipped": True}
    return {"delivered": bark_delivery_succeeded(result)}


def queue_bark(event):
    def deliver():
        result = forward_bark(dict(event))
        if result.get("error"):
            record_internal_error(
                "bark-queue",
                secrets.token_hex(8),
                RuntimeError("queued Bark delivery failed"),
            )

    threading.Thread(target=deliver, daemon=True).start()


def bark_delivery_succeeded(result):
    if result.get("error") or not 200 <= int(result.get("status") or 0) < 300:
        return False
    try:
        body = json.loads(result.get("body") or "{}")
    except (TypeError, ValueError):
        return True
    return int(body.get("code", 200)) == 200


def queue_bark_destination(event, destination):
    destination_id = destination.get("destinationId") or destination.get("deviceId")

    def deliver():
        try:
            device_key = bark_secret_store.get(destination_id)
        except Exception as exc:
            device_store.mark_bark_delivery(destination_id, False)
            record_internal_error("bark-secret", secrets.token_hex(8), exc)
            return
        if not device_key:
            device_store.mark_bark_delivery(destination_id, False)
            record_internal_error(
                "bark-secret",
                secrets.token_hex(8),
                RuntimeError("Bark destination credential is missing"),
            )
            return
        result = send_bark(destination.get("serverUrl"), device_key, dict(event))
        success = bark_delivery_succeeded(result)
        device_store.mark_bark_delivery(destination_id, success)
        if not success:
            record_internal_error(
                "bark-delivery",
                secrets.token_hex(8),
                RuntimeError("Bark destination delivery failed"),
            )

    threading.Thread(target=deliver, daemon=True).start()


def page(script_nonce=None):
    script_nonce = script_nonce or secrets.token_urlsafe(24)
    api_urls = [PUBLIC_BASE + "/v1/notify"]
    cfg = dict(config)
    initial_events_json = script_safe_json(events)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NotifyBridge</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #f5f7fb; --panel: #ffffff; --text: #172033; --muted: #6b7280;
      --line: #d9dee8; --accent: #1473e6; --good: #168b52; --bad: #b42318;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{ --bg: #111318; --panel: #191d24; --text: #edf1f7; --muted: #9aa4b2; --line: #323846; --accent: #63a7ff; }}
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }}
    header {{ padding: 22px 28px 14px; border-bottom: 1px solid var(--line); background: var(--panel); position: sticky; top: 0; z-index: 2; }}
    h1 {{ margin: 0 0 8px; font-size: 22px; letter-spacing: 0; }}
    .sub {{ color: var(--muted); font-size: 14px; }}
    main {{ display: grid; grid-template-columns: 360px minmax(0, 1fr); gap: 16px; padding: 16px; max-width: 1280px; margin: 0 auto; }}
    section {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
    h2 {{ margin: 0 0 12px; font-size: 15px; }}
    label {{ display: block; font-size: 12px; color: var(--muted); margin: 10px 0 6px; }}
    input[type="text"], input[type="password"] {{ width: 100%; padding: 10px 11px; border: 1px solid var(--line); border-radius: 6px; background: transparent; color: var(--text); font: inherit; }}
    .row {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
    button {{ border: 1px solid var(--line); border-radius: 6px; background: transparent; color: var(--text); padding: 9px 11px; font: inherit; cursor: pointer; }}
    button.primary {{ background: var(--accent); border-color: var(--accent); color: white; }}
    .pill {{ display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--line); border-radius: 999px; padding: 5px 9px; color: var(--muted); font-size: 12px; margin: 4px 4px 0 0; }}
    .dot {{ width: 8px; height: 8px; border-radius: 50%; background: var(--bad); }} .dot.on {{ background: var(--good); }}
    code {{ display: block; white-space: pre-wrap; word-break: break-all; padding: 9px; border: 1px solid var(--line); border-radius: 6px; color: var(--muted); margin: 6px 0; }}
    .event {{ border: 1px solid var(--line); border-radius: 8px; padding: 12px; margin-bottom: 10px; background: color-mix(in srgb, var(--panel), var(--bg) 35%); }}
    .event-head {{ display: flex; justify-content: space-between; gap: 12px; }}
    .app {{ font-weight: 650; }} .time {{ color: var(--muted); font-size: 12px; white-space: nowrap; }}
    .title {{ margin-top: 8px; font-weight: 600; }} .text {{ margin-top: 5px; color: var(--muted); white-space: pre-wrap; }}
    .meta {{ margin-top: 8px; color: var(--muted); font-size: 12px; word-break: break-all; }}
    .empty {{ color: var(--muted); padding: 28px; text-align: center; border: 1px dashed var(--line); border-radius: 8px; }}
    @media (max-width: 820px) {{ main {{ grid-template-columns: 1fr; }} header {{ position: static; }} }}
  </style>
</head>
<body>
  <header><h1>NotifyBridge</h1><div class="sub">局域网通知转发面板 <span class="pill"><span id="dot" class="dot"></span><span id="status">连接中</span></span></div></header>
  <main>
    <section>
      <h2>服务器地址</h2>
      {''.join(f'<code>{html.escape(u)}</code>' for u in api_urls)}
      <h2 style="margin-top:18px">红米安装</h2>
      <code>/apk（仅通过当前本地隧道）</code>
      <div class="row"><a href="/apk"><button>下载 APK</button></a></div>
      <div class="row"><button id="browserNotify">开启浏览器通知</button><button id="test" class="primary">发送测试</button></div>
      <h2 style="margin-top:18px">Bark</h2>
      <label>Bark Server</label><input id="barkServer" type="text" value="{html.escape(cfg.get('barkServer') or 'https://api.day.app')}">
      <label>Bark Key</label><input id="barkKey" type="password" value="" placeholder="{'已配置；留空保持不变' if cfg.get('barkKey') else '输入 Bark Key'}">
      <label class="row" style="display:flex"><input id="clearBarkKey" type="checkbox"><span>清除已保存的 Bark Key</span></label>
      <label class="row" style="display:flex"><input id="barkEnabled" type="checkbox" {'checked' if cfg.get('barkEnabled') else ''}><span>转发到 Bark</span></label>
      <label class="row" style="display:flex"><input id="localMacNotify" type="checkbox" {'checked' if cfg.get('localMacNotify') else ''}><span>本机 macOS 通知</span></label>
      <div class="row"><button id="saveConfig">保存</button></div>
    </section>
    <section><h2>实时通知</h2><div id="events" class="empty">等待红米手机上报通知</div></section>
  </main>
  <script id="initial-events" type="application/json" nonce="{script_nonce}">{initial_events_json}</script>
  <script nonce="{script_nonce}">
    const initialEvents = JSON.parse(document.getElementById('initial-events').textContent);
    const $ = (id) => document.getElementById(id);
    const eventsEl = $('events'), dot = $('dot'), statusEl = $('status');
    let events = [];
    function esc(value) {{ return String(value || '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])); }}
    function render() {{
      if (!events.length) {{ eventsEl.className = 'empty'; eventsEl.textContent = '等待红米手机上报通知'; return; }}
      eventsEl.className = '';
      eventsEl.innerHTML = events.map(ev => {{
        const when = new Date(ev.receivedAt || ev.postTime || Date.now()).toLocaleString();
        return '<div class="event"><div class="event-head"><div class="app">' + esc(ev.appName || ev.packageName || 'Android') + '</div><div class="time">' + esc(when) + '</div></div>' +
          (ev.title ? '<div class="title">' + esc(ev.title) + '</div>' : '') +
          (ev.text ? '<div class="text">' + esc(ev.text) + '</div>' : '') +
          '<div class="meta">' + esc(ev.device || '') + ' · ' + esc(ev.packageName || '') + '</div></div>';
      }}).join('');
    }}
    function notifyBrowser(ev) {{
      if (!('Notification' in window) || Notification.permission !== 'granted') return;
      new Notification(ev.appName + (ev.title ? ': ' + ev.title : ''), {{ body: ev.text || ev.packageName || '', tag: ev.id || String(Date.now()) }});
    }}
    function addEvent(ev, pop) {{ events.unshift(ev); events = events.slice(0, 80); render(); if (pop) notifyBrowser(ev); }}
    for (const ev of initialEvents.reverse()) addEvent(ev, false);
    const source = new EventSource('/events');
    source.onopen = () => {{ dot.classList.add('on'); statusEl.textContent = '已连接'; }};
    source.onerror = () => {{ dot.classList.remove('on'); statusEl.textContent = '重连中'; }};
    source.addEventListener('notify', msg => addEvent(JSON.parse(msg.data), true));
    $('browserNotify').onclick = async () => {{
      if (!('Notification' in window)) return alert('当前浏览器不支持通知');
      alert((await Notification.requestPermission()) === 'granted' ? '浏览器通知已开启' : '浏览器通知未授权');
    }};
    $('test').onclick = async () => {{ await fetch('/api/test', {{ method: 'POST' }}); }};
    $('saveConfig').onclick = async () => {{
      const body = {{ barkServer: $('barkServer').value.trim() || 'https://api.day.app', barkKey: $('barkKey').value.trim(), clearBarkKey: $('clearBarkKey').checked, barkEnabled: $('barkEnabled').checked, localMacNotify: $('localMacNotify').checked }};
      const res = await fetch('/api/config', {{ method: 'POST', headers: {{ 'content-type': 'application/json' }}, body: JSON.stringify(body) }});
      alert(res.ok ? '已保存' : '保存失败');
    }};
  </script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def client_ip(self):
        direct = self.client_address[0]
        if ipaddress.ip_address(direct).is_loopback:
            forwarded = self.headers.get("X-Real-IP", "").strip()
            if forwarded:
                try:
                    ipaddress.ip_address(forwarded)
                    return forwarded
                except ValueError:
                    pass
        return direct

    def local_only(self):
        try:
            peer_is_loopback = ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            peer_is_loopback = False
        if (
            peer_is_loopback
            and normalized_host_header(self.headers.get("Host")) in LOOPBACK_HOSTS
            and self.local_origin_allowed()
        ):
            return True
        self.send_json(403, {"ok": False, "error": "local management access denied"})
        return False

    def request_host_allowed(self):
        return normalized_host_header(self.headers.get("Host")) in PUBLIC_REQUEST_HOSTS

    def public_origin_allowed(self):
        origin = self.headers.get("Origin", "").strip().rstrip("/")
        return not origin or origin == PUBLIC_ORIGIN

    def local_origin_allowed(self):
        origin = self.headers.get("Origin", "").strip().rstrip("/")
        if not origin:
            return True
        try:
            parsed = urllib.parse.urlparse(origin)
            return (
                parsed.scheme in {"http", "https"}
                and normalized_host_header(parsed.netloc) in LOOPBACK_HOSTS
                and parsed.path in {"", "/"}
                and not parsed.params
                and not parsed.query
                and not parsed.fragment
            )
        except (TypeError, ValueError):
            return False

    def reject_untrusted_host(self):
        if self.request_host_allowed():
            return False
        self.send_json(421, {"ok": False, "error": "misdirected request"})
        return True

    def require_json_content_type(self, clean_path):
        if clean_path not in JSON_POST_PATHS:
            return True
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type == "application/json":
            return True
        self.send_json(415, {"ok": False, "error": "application/json required"})
        return False

    def authenticated_device(self, role=None):
        device_id, secret = bearer_credentials(self.headers)
        device = device_store.authenticate(device_id, secret, role=role)
        if device is None:
            self.send_json(401, {"ok": False, "error": "invalid device credential"})
        return device

    def send_security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def send_json(self, status, body, headers=None):
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_security_headers()
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        for name, value in (headers or {}).items():
            self.send_header(str(name), str(value))
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True

    def send_internal_error(self, area, error, public_error="request failed"):
        request_id = secrets.token_hex(8)
        record_internal_error(area, request_id, error)
        self.send_json(
            500,
            {
                "ok": False,
                "error": public_error,
                "requestId": request_id,
            },
            headers={"X-Request-ID": request_id},
        )

    def send_pairing_internal_error(self, area, error):
        self.send_internal_error(area, error, PAIRING_INTERNAL_ERROR)

    def read_json(self, maximum=64 * 1024):
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise UnsupportedMediaTypeError("application/json required")
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > maximum:
            raise ValueError("request body too large")
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def send_viewer(self):
        if not audit_store.viewer_path.is_file():
            self.send_json(404, {"ok": False, "error": "viewer missing"})
            return
        raw = audit_store.viewer_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-cache")
        self.send_security_headers()
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(raw)

    def send_receiver_stream(self, receiver_id):
        if not device_store.receiver_has_active_route(receiver_id):
            self.send_json(409, {"ok": False, "error": "receiver is not paired"})
            return
        stream, limit = register_receiver_stream(
            self.wfile, receiver_id, self.client_ip()
        )
        if stream is None:
            self.send_json(429, {"ok": False, "error": "too many receiver streams"})
            return
        # Close the narrow race where revocation commits between the first
        # route check and registry insertion.
        if not device_store.receiver_has_active_route(receiver_id):
            unregister_event_stream(stream)
            self.send_json(409, {"ok": False, "error": "receiver is not paired"})
            return
        try:
            self.connection.settimeout(EVENT_STREAM_WRITE_TIMEOUT_SECONDS)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            stream.run_writer()
        except Exception:
            pass
        finally:
            unregister_event_stream(stream)

    def do_OPTIONS(self):
        if self.reject_untrusted_host():
            return
        # The public Nginx server has the same fail-closed policy.  All browser
        # pages are same-origin and native clients do not use CORS, so exposing
        # a cross-origin preflight surface would only create policy drift.
        self.send_json(405, {"ok": False, "error": "method not allowed"})

    def do_GET(self):
        try:
            self._do_GET()
        except PermissionError:
            self.send_json(403, {"ok": False, "error": "operation not permitted"})
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"ok": False, "error": "invalid request"})
        except Exception as exc:
            self.send_internal_error("request", exc)

    def _do_GET(self):
        if self.reject_untrusted_host():
            return
        parsed = urllib.parse.urlparse(self.path)
        clean_path = parsed.path

        if clean_path == "/api/v1/health":
            if not rate_allowed(("health", self.client_ip()), 120):
                self.send_json(429, {"ok": False, "error": "too many requests"})
                return
            self.send_json(200, {
                "ok": True,
                "service": "xxzf",
                "serverTime": int(time.time() * 1000),
            })
            return

        if clean_path == "/api/v1/device-status":
            device = self.authenticated_device()
            if device is not None:
                self.send_json(200, {
                    "ok": True,
                    "device": {
                        "role": device["role"],
                        "fingerprint": device["fingerprint"],
                    },
                    "serverTime": int(time.time() * 1000),
                })
            return

        if clean_path == "/api/v1/events":
            receiver = self.authenticated_device("receiver")
            if receiver is not None:
                self.send_receiver_stream(receiver["device_id"])
            return

        if clean_path == "/api/v1/destinations":
            sender = self.authenticated_device("sender")
            if sender is not None:
                self.send_json(200, {
                    "ok": True,
                    "destinations": (
                        device_store.destinations_for_sender(sender["device_id"])
                        + device_store.bark_destinations_for_sender(sender["device_id"])
                    ),
                })
            return

        if clean_path == "/api/pair/status":
            receiver = self.authenticated_device("receiver")
            if receiver is None:
                return
            query = urllib.parse.parse_qs(parsed.query)
            pairing_id = (query.get("pairingId") or [""])[0]
            if pairing_id:
                pairing = device_store.pairing_status(receiver["device_id"], pairing_id)
                if pairing is None:
                    self.send_json(404, {"ok": False, "error": "pairing not found"})
                    return
                self.send_json(200, {
                    "ok": True,
                    "paired": pairing["claimed"],
                    "expired": pairing["expired"],
                    "pairingId": pairing["pairingId"],
                })
                return
            senders = []
            for device in device_store.list_devices():
                if device["role"] != "sender" or device["status"] != "active":
                    continue
                destinations = device_store.destinations_for_sender(device["deviceId"])
                if any(item["deviceId"] == receiver["device_id"] for item in destinations):
                    senders.append(device)
            self.send_json(200, {"ok": True, "paired": bool(senders), "senders": senders})
            return

        if not self.local_only():
            return
        if clean_path == "/":
            script_nonce = secrets.token_urlsafe(24)
            raw = page(script_nonce).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_security_headers()
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'nonce-%s'; style-src 'self' 'unsafe-inline'; "
                "connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; "
                "frame-ancestors 'none'" % script_nonce,
            )
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)
            return
        if clean_path == "/events":
            stream, limit = register_legacy_stream(self.wfile, self.client_ip())
            if stream is None:
                self.send_json(429, {"ok": False, "error": "too many local streams"})
                return
            try:
                self.connection.settimeout(EVENT_STREAM_WRITE_TIMEOUT_SECONDS)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                stream.run_writer()
            except Exception:
                pass
            finally:
                unregister_event_stream(stream)
            return
        if clean_path in ("/audit", "/audit/", "/audit/index.html"):
            self.send_viewer()
            return
        if clean_path == "/audit/api/events":
            query = urllib.parse.parse_qs(parsed.query)
            try:
                records = audit_store.query(
                    limit=(query.get("limit") or [100])[0],
                    before=(query.get("before") or [None])[0],
                    search=(query.get("q") or [""])[0],
                    offset=(query.get("offset") or [0])[0],
                    sender_id=(query.get("sender") or [""])[0],
                )
                total = audit_store.count(
                    search=(query.get("q") or [""])[0],
                    sender_id=(query.get("sender") or [""])[0],
                )
                device_groups = audit_store.device_groups()
            except (TypeError, ValueError):
                self.send_json(400, {"ok": False, "error": "invalid query"})
                return
            self.send_json(200, {
                "ok": True,
                "events": records,
                "total": total,
                "deviceGroups": device_groups,
            })
            return
        if clean_path == "/audit/api/stats":
            self.send_json(200, {"ok": True, "stats": audit_store.stats()})
            return
        if clean_path == "/audit/api/health":
            self.send_json(200, audit_health_snapshot())
            return
        if clean_path == "/audit/api/diagnostics":
            query = urllib.parse.parse_qs(parsed.query)
            try:
                records = diagnostic_store.query(
                    limit=(query.get("limit") or [100])[0],
                    device_id=(query.get("device") or [""])[0],
                )
            except (TypeError, ValueError):
                self.send_json(400, {"ok": False, "error": "invalid query"})
                return
            self.send_json(200, {
                "ok": True,
                "diagnostics": records,
                "stats": diagnostic_store.stats(),
                "deviceGroups": diagnostic_store.device_groups(),
            })
            return
        if clean_path == "/api/devices":
            self.send_json(200, {"ok": True, "devices": device_store.list_devices()})
            return
        if clean_path == "/api/config":
            redacted = dict(config)
            redacted["barkKey"] = "***" if redacted.get("barkKey") else ""
            self.send_json(200, {
                "ok": True,
                "config": redacted,
                "urls": [PUBLIC_BASE],
            })
            return
        if clean_path == "/apk":
            if not APK_FILE.exists():
                self.send_json(404, {"ok": False, "error": "APK not built"})
                return
            raw = APK_FILE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.android.package-archive")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Content-Disposition", "attachment; filename=NotifyBridge-release.apk")
            self.end_headers()
            self.wfile.write(raw)
            return
        if clean_path == "/tools/OpenSSH-Win64-v10.0.0.0.msi":
            if not WINDOWS_SSH_INSTALLER.is_file():
                self.send_json(404, {"ok": False, "error": "installer missing"})
                return
            raw = WINDOWS_SSH_INSTALLER.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-msdownload")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header(
                "Content-Disposition",
                "attachment; filename=OpenSSH-Win64-v10.0.0.0.msi",
            )
            self.send_header("Cache-Control", "private, no-store")
            self.end_headers()
            self.wfile.write(raw)
            return
        self.send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        global config
        try:
            clean_path = urllib.parse.urlparse(self.path).path
            if self.reject_untrusted_host():
                return
            if clean_path not in LOCAL_MANAGEMENT_POST_PATHS and not self.public_origin_allowed():
                self.send_json(403, {"ok": False, "error": "origin not allowed"})
                return
            if not self.require_json_content_type(clean_path):
                return
            if clean_path == "/api/pair/start":
                if not rate_allowed(
                    ("pair-start-global", "all"),
                    PAIR_START_GLOBAL_LIMIT,
                    window_seconds=60,
                ) or not rate_allowed(("pair-start", self.client_ip()), 8):
                    self.send_json(
                        429,
                        {"ok": False, "error": PAIRING_RATE_LIMIT_ERROR},
                        headers={"Retry-After": "60"},
                    )
                    return
                try:
                    body = self.read_json(16 * 1024)
                    if not isinstance(body, dict):
                        raise ValueError("pairing request must be an object")
                    device_id, secret = bearer_credentials(self.headers)
                    if device_id or secret:
                        receiver = device_store.authenticate(
                            device_id, secret, role="receiver"
                        )
                        if receiver is None:
                            self.send_json(
                                401,
                                {"ok": False, "error": "invalid device credential"},
                            )
                            return
                        pairing = device_store.start_pairing_for_receiver(
                            receiver["device_id"]
                        )
                    else:
                        pairing = device_store.start_pairing(
                            body.get("deviceName") or "Mac 接收端",
                            body.get("platform") or "macos",
                        )
                    pairing["serverBase"] = PUBLIC_BASE
                    pairing["qrPayload"] = pairing_qr_payload(pairing["code"])
                    pairing["qrPng"] = png_base64(pairing["qrPayload"])
                    self.send_json(201, {"ok": True, "pairing": pairing})
                except (ValueError, json.JSONDecodeError):
                    self.send_json(400, {"ok": False, "error": PAIRING_PUBLIC_ERROR})
                except Exception as exc:
                    self.send_pairing_internal_error("pair-start", exc)
                return
            if clean_path == "/api/pair/claim":
                if not rate_allowed(("pair-claim", self.client_ip()), 20):
                    self.send_json(
                        429,
                        {"ok": False, "error": PAIRING_RATE_LIMIT_ERROR},
                        headers={"Retry-After": "60"},
                    )
                    return
                try:
                    body = self.read_json(16 * 1024)
                    if not isinstance(body, dict):
                        raise ValueError("pairing request must be an object")
                    device_id, secret = bearer_credentials(self.headers)
                    if device_id or secret:
                        sender = device_store.authenticate(device_id, secret, role="sender")
                        if sender is None:
                            self.send_json(401, {"ok": False, "error": "invalid device credential"})
                            return
                        claimed = device_store.claim_pairing_for_sender(
                            body.get("code"), sender["device_id"]
                        )
                    else:
                        claimed = device_store.claim_pairing(
                            body.get("code"),
                            body.get("deviceName") or "Android 手机",
                            body.get("platform") or "android",
                        )
                    claimed["serverBase"] = PUBLIC_BASE
                    claimed["notifyUrl"] = PUBLIC_BASE + "/v1/notify"
                    claimed["notifyUrls"] = [claimed["notifyUrl"]]
                    self.send_json(200, {"ok": True, "device": claimed})
                except PairingClaimRateLimited as exc:
                    self.send_json(
                        429,
                        {"ok": False, "error": PAIRING_RATE_LIMIT_ERROR},
                        headers={"Retry-After": str(exc.retry_after)},
                    )
                    return
                except ValueError:
                    self.send_json(400, {"ok": False, "error": PAIRING_PUBLIC_ERROR})
                except Exception as exc:
                    self.send_pairing_internal_error("pair-claim", exc)
                return
            if clean_path == "/api/v1/bark/enroll/start":
                sender = self.authenticated_device("sender")
                if sender is None:
                    return
                if not rate_allowed(
                    ("bark-enroll-start-global", "all"), 120, window_seconds=60
                ) or not rate_allowed(
                    ("bark-enroll-start", sender["device_id"]), 12, window_seconds=3600
                ):
                    self.send_json(429, {"ok": False, "error": "生成绑定码过于频繁"})
                    return
                enrollment = device_store.start_bark_enrollment(sender["device_id"])
                raw_token = enrollment.pop("token")
                bind_url = BARK_BIND_PAGE + "#token=" + urllib.parse.quote(raw_token, safe="")
                enrollment["bindUrl"] = bind_url
                enrollment["qrPayload"] = bind_url
                enrollment["qrPng"] = png_base64(bind_url)
                self.send_json(201, {"ok": True, "enrollment": enrollment})
                return
            if clean_path == "/api/v1/bark/enroll/claim":
                if not rate_allowed(
                    ("bark-enroll-claim-global", "all"), 120, window_seconds=60
                ) or not rate_allowed(
                    ("bark-enroll-claim-short", self.client_ip()), 12, window_seconds=300
                ) or not rate_allowed(
                    ("bark-enroll-claim-hour", self.client_ip()), 30, window_seconds=3600
                ):
                    self.send_json(429, {"ok": False, "error": "绑定尝试过于频繁"})
                    return
                try:
                    body = self.read_json(8 * 1024)
                except ValueError:
                    self.send_json(400, {
                        "ok": False, "error": BARK_ENROLLMENT_PUBLIC_ERROR
                    })
                    return
                try:
                    device_store.validate_bark_enrollment(
                        token=body.get("token"), code=body.get("code")
                    )
                except ValueError:
                    self.send_json(400, {
                        "ok": False, "error": BARK_ENROLLMENT_PUBLIC_ERROR
                    })
                    return
                base, device_key = parse_bark_test_url(body.get("barkUrl"))
                verification = send_bark(base, device_key, {
                    "appName": "绑定成功",
                    "title": "iPhone 已连接",
                    "text": "这台 iPhone 已可以接收转发通知",
                    "privacyMode": "full",
                })
                if not bark_delivery_succeeded(verification):
                    self.send_json(400, {
                        "ok": False,
                        "error": "Bark 验证失败，请重新复制 Bark 首页的完整测试地址",
                    })
                    return
                try:
                    destination = device_store.claim_bark_enrollment(
                        token=body.get("token"),
                        code=body.get("code"),
                        name=body.get("deviceName") or "iPhone",
                        server_url=base,
                        key_fingerprint=bark_key_fingerprint(device_key),
                    )
                except ValueError:
                    self.send_json(400, {
                        "ok": False, "error": BARK_ENROLLMENT_PUBLIC_ERROR
                    })
                    return
                try:
                    bark_secret_store.put(destination["destinationId"], device_key)
                except Exception as exc:
                    try:
                        revoke_bark_destination_and_secret(
                            destination["senderId"], destination["destinationId"]
                        )
                    except Exception:
                        # The DB-first revoke remains safe; startup
                        # reconciliation will retry any secret erasure.
                        pass
                    self.send_internal_error(
                        "bark-enroll-save", exc, "保存绑定信息失败"
                    )
                    return
                device_store.mark_bark_delivery(destination["destinationId"], True)
                self.send_json(201, {"ok": True, "destination": destination})
                return
            if clean_path == "/api/v1/bark/test":
                sender = self.authenticated_device("sender")
                if sender is None:
                    return
                if not rate_allowed(
                    ("bark-test", sender["device_id"]), 12, window_seconds=3600
                ):
                    self.send_json(429, {"ok": False, "error": "测试过于频繁"})
                    return
                body = self.read_json(4 * 1024)
                destination = device_store.bark_destination_for_sender(
                    sender["device_id"], body.get("destinationId")
                )
                if destination is None:
                    self.send_json(404, {"ok": False, "error": "iPhone 接收设备不存在"})
                    return
                device_key = bark_secret_store.get(destination["destinationId"])
                if not device_key:
                    self.send_json(409, {"ok": False, "error": "iPhone 需要重新绑定"})
                    return
                result = send_bark(destination["serverUrl"], device_key, {
                    "appName": "转发测试",
                    "title": "连接正常",
                    "text": "这台 iPhone 可以接收通知",
                    "privacyMode": "full",
                })
                success = bark_delivery_succeeded(result)
                device_store.mark_bark_delivery(destination["destinationId"], success)
                self.send_json(200 if success else 502, {
                    "ok": success,
                    "error": "" if success else "Bark 暂时无法接收通知",
                })
                return
            if clean_path == "/api/v1/bark/revoke":
                sender = self.authenticated_device("sender")
                if sender is None:
                    return
                body = self.read_json(4 * 1024)
                destination_id = str(body.get("destinationId") or "")
                revoked = revoke_bark_destination_and_secret(
                    sender["device_id"], destination_id
                )
                if not revoked:
                    self.send_json(404, {"ok": False, "error": "iPhone 接收设备不存在"})
                    return
                self.send_json(200, {"ok": True})
                return
            if clean_path == "/api/v1/receiver/senders/revoke":
                receiver = self.authenticated_device("receiver")
                if receiver is None:
                    return
                body = self.read_json(4 * 1024)
                sender_id = str(body.get("senderId") or "")
                revoked = device_store.revoke_sender_route(
                    receiver["device_id"], sender_id
                )
                if not revoked:
                    self.send_json(404, {
                        "ok": False,
                        "error": "发送设备不存在或已解除",
                    })
                    return
                close_unrouted_receiver_streams()
                self.send_json(200, {"ok": True})
                return
            if clean_path == "/api/v1/device/revoke":
                device = self.authenticated_device()
                if device is None:
                    return
                revoked = revoke_device_and_secrets(device["device_id"])
                if not revoked:
                    self.send_json(404, {"ok": False, "error": "device not found"})
                    return
                self.send_json(200, {"ok": True})
                return
            if clean_path == "/api/v1/notify":
                sender = self.authenticated_device("sender")
                if sender is None:
                    return
                if not rate_allowed(("device", sender["device_id"]), int(sender["rate_limit"])):
                    self.send_json(429, {"ok": False, "error": "device rate limit exceeded"})
                    return
                event, destinations, bark = process_event(
                    self.read_json(64 * 1024), sender=sender, legacy=False
                )
                self.send_json(200, {
                    "ok": True,
                    "eventId": event["id"],
                    "destinations": len(destinations),
                    "bark": bark,
                })
                return
            if clean_path == "/api/v1/diagnostics":
                device = self.authenticated_device()
                if device is None:
                    return
                if not rate_allowed(
                    ("diagnostics-device", device["device_id"]), 6, window_seconds=3600
                ):
                    self.send_json(429, {"ok": False, "error": "diagnostic upload limit exceeded"})
                    return
                if not rate_allowed(
                    ("diagnostics-ip", self.client_ip()), 30, window_seconds=3600
                ):
                    self.send_json(429, {"ok": False, "error": "diagnostic upload limit exceeded"})
                    return
                result = diagnostic_store.record(self.read_json(64 * 1024), device)
                self.send_json(201, {"ok": True, **result})
                return
            if clean_path == "/api/config":
                if not self.local_only():
                    return
                body = self.read_json()
                bark_server = normalize_bark_server(body.get("barkServer"))
                submitted_bark_key = str(body.get("barkKey") or "").strip()
                if submitted_bark_key and not re.fullmatch(r"[A-Za-z0-9_-]{16,200}", submitted_bark_key):
                    raise ValueError("invalid Bark key")
                if body.get("clearBarkKey"):
                    next_bark_key = ""
                elif submitted_bark_key:
                    next_bark_key = submitted_bark_key
                else:
                    next_bark_key = str(config.get("barkKey") or "")
                config = {
                    "barkEnabled": bool(body.get("barkEnabled")) and bool(next_bark_key),
                    "barkServer": bark_server,
                    "barkKey": next_bark_key,
                    "localMacNotify": bool(body.get("localMacNotify")),
                    "ownerSenderIds": [
                        bounded_text(value, 96)
                        for value in (body.get("ownerSenderIds") or config.get("ownerSenderIds") or [])
                    ][:16],
                }
                save_config()
                self.send_json(200, {"ok": True})
                return
            if clean_path == "/api/devices/revoke":
                if not self.local_only():
                    return
                body = self.read_json(8 * 1024)
                revoked = revoke_device_and_secrets(body.get("deviceId"))
                self.send_json(200 if revoked else 404, {"ok": revoked})
                return
            if clean_path == "/api/devices/rate":
                if not self.local_only():
                    return
                body = self.read_json(8 * 1024)
                try:
                    updated, value = device_store.update_rate_limit(
                        body.get("deviceId"), body.get("rateLimit")
                    )
                except (TypeError, ValueError):
                    self.send_json(400, {"ok": False, "error": "invalid rate limit"})
                    return
                self.send_json(200 if updated else 404, {
                    "ok": updated,
                    "rateLimit": value,
                })
                return
            if clean_path == "/api/test":
                if not self.local_only():
                    return
                event = normalize_event({
                    "device": socket.gethostname(),
                    "packageName": "local.test",
                    "appName": "NotifyBridge",
                    "title": "测试通知",
                    "text": "这是一条来自局域网面板的测试消息",
                })
                event, _, bark = process_event(event, legacy=True)
                self.send_json(200, {"ok": True, "event": event, "bark": bark})
                return
            if clean_path == "/api/notify":
                if not authorized(self.headers):
                    self.send_json(401, {"ok": False, "error": "unauthorized"})
                    return
                event, _, bark = process_event(self.read_json(), legacy=True)
                self.send_json(200, {"ok": True, "eventId": event["id"], "bark": bark})
                return
            self.send_json(404, {"ok": False, "error": "not found"})
        except PermissionError:
            self.send_json(403, {"ok": False, "error": "operation not permitted"})
        except UnsupportedMediaTypeError:
            self.send_json(415, {"ok": False, "error": "application/json required"})
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"ok": False, "error": "invalid request"})
        except Exception as exc:
            self.send_internal_error("request", exc)

    def log_message(self, fmt, *args):
        # The default request line contains paths, query strings and one line
        # per Internet request.  Operational failures go to the private,
        # bounded error log instead; successful requests are deliberately
        # silent so launchd stdout cannot grow without bound.
        return


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"NotifyBridge server listening on {HOST}:{PORT}")
    print(f"Official client API: {PUBLIC_BASE}")
    server.serve_forever()


if __name__ == "__main__":
    main()
