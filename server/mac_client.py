#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

def resolve_notifier_app(environment=None, user_home=None, executable_test=os.path.isfile):
    environment = os.environ if environment is None else environment
    configured = str(environment.get("XXZF_NOTIFIER_APP") or "").strip()
    if configured:
        return os.path.expanduser(configured)

    user_home = os.path.expanduser("~") if user_home is None else user_home
    candidates = [
        "/Applications/转发.app",
        os.path.join(user_home, "Applications", "转发.app"),
    ]
    for candidate in candidates:
        executable = os.path.join(candidate, "Contents", "MacOS", "转发")
        if executable_test(executable):
            return candidate
    return candidates[0]


NOTIFIER_APP = resolve_notifier_app()


OFFICIAL_SERVER = "https://example.com/xxzf"
DEFAULT_SERVERS = OFFICIAL_SERVER

CREDENTIAL_FILE = Path(os.environ.get(
    "XXZF_RECEIVER_CREDENTIALS",
    "~/Library/Application Support/XXZF/receiver.json",
)).expanduser()
DIAGNOSTIC_FILE = CREDENTIAL_FILE.parent / "diagnostics.jsonl"


def parse_servers(values):
    # Server selection is intentionally not configurable: receiver credentials
    # must never be sent to a LAN, Tailscale-IP, or look-alike origin.
    return [OFFICIAL_SERVER]


SERVERS = parse_servers([DEFAULT_SERVERS])

CONTENT_MODES = ("source", "title", "full")
CONTENT_MODE_RANK = {mode: rank for rank, mode in enumerate(CONTENT_MODES)}


def diagnostic_log(level, code, http_status=0):
    entry = {
        "at": int(time.time() * 1000),
        "level": level if level in ("info", "warning", "error") else "info",
        "code": re.sub(r"[^A-Z0-9_.:-]", "_", str(code or "UNKNOWN").upper())[:48],
    }
    if http_status:
        entry["httpStatus"] = max(0, min(int(http_status), 999))
    try:
        DIAGNOSTIC_FILE.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        if DIAGNOSTIC_FILE.is_file():
            lines = DIAGNOSTIC_FILE.read_text("utf-8").splitlines()[:79]
        temporary = DIAGNOSTIC_FILE.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(entry, ensure_ascii=True, separators=(",", ":")) + "\n"
            + "\n".join(lines) + ("\n" if lines else ""),
            "utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, DIAGNOSTIC_FILE)
    except Exception:
        pass


def load_receiver_credentials():
    try:
        data = json.loads(CREDENTIAL_FILE.read_text("utf-8"))
    except Exception:
        return None
    receiver_id = str(data.get("receiverId") or "").strip()
    receiver_secret = str(data.get("receiverSecret") or "").strip()
    if not receiver_id or not receiver_secret:
        return None
    data["receiverId"] = receiver_id
    data["receiverSecret"] = receiver_secret
    if data.get("servers") != [OFFICIAL_SERVER]:
        data["servers"] = [OFFICIAL_SERVER]
        try:
            CREDENTIAL_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(CREDENTIAL_FILE.parent, 0o700)
            temporary = CREDENTIAL_FILE.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.chmod(temporary, 0o600)
            os.replace(temporary, CREDENTIAL_FILE)
            os.chmod(CREDENTIAL_FILE, 0o600)
        except Exception:
            pass
    return data


def normalize_content_mode(value, show_content=True):
    mode = str(value or "").strip().lower()
    if mode in CONTENT_MODE_RANK:
        return mode
    return "full" if show_content is not False else "source"


def receiver_content_mode(fallback=None):
    current = load_receiver_credentials()
    credentials = current or fallback or {}
    return normalize_content_mode(
        credentials.get("contentMode"),
        credentials.get("showContent", True),
    )


def effective_content_mode(phone_mode, receiver_mode):
    phone = normalize_content_mode(phone_mode)
    receiver = normalize_content_mode(receiver_mode)
    return min((phone, receiver), key=CONTENT_MODE_RANK.get)


def paired_events_url(server):
    if server != OFFICIAL_SERVER:
        raise ValueError("untrusted XXZF server")
    return OFFICIAL_SERVER + "/v1/events"


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


HTTPS_OPENER = urllib.request.build_opener(NoRedirectHandler)


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


def run_notification_command(command, timeout):
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:
        print(f"mac notification failed: {exc}", flush=True)
        return False
    if result.returncode == 0:
        return True
    print(f"mac notification failed: {result.stderr.strip()}", flush=True)
    return False


def notify(_source, title, body):
    title = (title or "Android").replace("\n", " ")[:120]
    body = (body or "").replace("\r", "").strip()[:240]
    executable = os.path.join(NOTIFIER_APP, "Contents", "MacOS", "转发")
    if os.path.isfile(executable) and run_notification_command(
            [executable, "--notify", title, body], 12):
        return True
    return run_notification_command([
            "/usr/bin/osascript",
            "-e",
            "on run argv",
            "-e",
            "display notification (item 2 of argv) with title (item 1 of argv) sound name \"Glass\"",
            "-e",
            "end run",
            title,
            body,
        ], 8)


def handle_event(event, content_mode="full"):
    app = event.get("appName") or event.get("packageName") or "Android"
    title = event.get("title") or ""
    text = clean_repeated_title(title, event.get("text") or "")
    privacy = effective_content_mode(event.get("privacyMode"), content_mode)
    display_title = f"转发：{app}"
    if privacy == "source":
        preview = ""
    elif privacy == "title":
        preview = title
    else:
        preview = "\n".join(part for part in (title, text) if part).strip()
    delivered = notify(app, display_title, preview)
    if delivered:
        diagnostic_log("info", "NOTIFICATION_DELIVERED")
        print(f"{time.strftime('%H:%M:%S')} notification delivered", flush=True)
    else:
        diagnostic_log("error", "NOTIFICATION_FAILED")
        print(f"{time.strftime('%H:%M:%S')} notification delivery failed", flush=True)
    return delivered


def stream(server, state, credentials=None):
    if server != OFFICIAL_SERVER:
        raise ValueError("untrusted XXZF server")
    if not credentials:
        raise RuntimeError("receiver credentials required; explicit pairing is required")
    headers = {"Accept": "text/event-stream"}
    token = credentials["receiverId"] + "." + credentials["receiverSecret"]
    headers["Authorization"] = "Bearer " + token
    url = paired_events_url(server)
    req = urllib.request.Request(url, headers=headers)
    with HTTPS_OPENER.open(req, timeout=30) as response:
        print(f"XXZF Air notifier connected via {server}", flush=True)
        diagnostic_log("info", "STREAM_CONNECTED", response.status)
        event_name = None
        data_lines = []
        for raw in response:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if line.endswith("\r"):
                line = line[:-1]
            if not line:
                if event_name == "notify" and data_lines:
                    payload = "\n".join(data_lines)
                    event = json.loads(payload)
                    fingerprint = (
                        event.get("id"),
                        event.get("receivedAt"),
                        event.get("postTime"),
                        event.get("title"),
                        event.get("text"),
                    )
                    if fingerprint != state.get("last_event"):
                        state["last_event"] = fingerprint
                        handle_event(event, content_mode=receiver_content_mode(credentials))
                event_name = None
                data_lines = []
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())


def wait_for_replacement_credentials(rejected):
    rejected_identity = (
        str((rejected or {}).get("receiverId") or ""),
        str((rejected or {}).get("receiverSecret") or ""),
    )
    while True:
        time.sleep(5)
        current = load_receiver_credentials()
        current_identity = (
            str((current or {}).get("receiverId") or ""),
            str((current or {}).get("receiverSecret") or ""),
        )
        if current and current_identity != rejected_identity:
            return current


def run():
    credentials = load_receiver_credentials()
    if not credentials:
        diagnostic_log("warning", "CREDENTIAL_MISSING")
        print("XXZF Air notifier waiting for explicit pairing", flush=True)
        while not credentials:
            time.sleep(5)
            credentials = load_receiver_credentials()
    servers = list(SERVERS)
    if credentials:
        configured = credentials.get("servers") or []
        if configured:
            servers = parse_servers([",".join(configured)])
        print(
            f"XXZF paired receiver {credentials['receiverId']} "
            f"key {credentials.get('receiverFingerprint', '')}",
            flush=True,
        )
    state = {"last_event": None}
    last_error = None
    while True:
        for server in servers:
            try:
                stream(server, state, credentials=credentials)
                last_error = None
            except KeyboardInterrupt:
                raise
            except urllib.error.HTTPError as exc:
                try:
                    if exc.code in (401, 403):
                        diagnostic_log("error", "AUTH_FAILED_WAITING_FOR_REPAIR", exc.code)
                        print(
                            "XXZF Air notifier credential rejected; "
                            "waiting for explicit pairing",
                            flush=True,
                        )
                        credentials = wait_for_replacement_credentials(credentials)
                        configured = credentials.get("servers") or []
                        servers = (
                            parse_servers([",".join(configured)])
                            if configured
                            else list(SERVERS)
                        )
                        last_error = None
                        break
                    message = f"{server}: HTTP {exc.code}"
                    if message != last_error:
                        print(f"XXZF Air notifier unavailable {message}", flush=True)
                        diagnostic_log("error", "STREAM_HTTP_FAILED", exc.code)
                        last_error = message
                finally:
                    exc.close()
            except Exception as exc:
                message = f"{server}: {exc}"
                if message != last_error:
                    print(f"XXZF Air notifier unavailable {message}", flush=True)
                    diagnostic_log("error", "STREAM_DISCONNECTED")
                    last_error = message
        time.sleep(2)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        SERVERS = parse_servers(sys.argv[1:])
    if not SERVERS:
        raise SystemExit("No XXZF server configured")
    run()
