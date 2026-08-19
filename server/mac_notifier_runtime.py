#!/usr/bin/env python3
import copy
import fcntl
import hashlib
import json
import os
import plistlib
import re
import shutil
import struct
import subprocess
import tempfile
import time
import unicodedata
import uuid
from pathlib import Path


BASE_BUNDLE_ID = "com.zundu.xxzf.notifier"
BASE_APP = Path(
    os.environ.get("XXZF_NOTIFIER_APP", "~/Applications/讯桥通知.app")
).expanduser()
APPLICATIONS_DIR = Path.home() / "Applications"
SUPPORT_DIR = Path.home() / "Library/Application Support/XXZF"
LOCK_FILE = SUPPORT_DIR / "source-notifier.lock"
NCPREFS_FILE = Path.home() / "Library/Preferences/com.apple.ncprefs.plist"
FOCUS_FILE = Path.home() / "Library/DoNotDisturb/DB/ModeConfigurationsSecure.json"
LSREGISTER = Path(
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/"
    "LaunchServices.framework/Support/lsregister"
)


def _run(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def _source_label(source):
    value = unicodedata.normalize("NFC", str(source or "Android")).strip()
    value = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    value = value.replace("/", "／").replace(":", "：").replace("\0", "")
    value = "".join(char for char in value if unicodedata.category(char) != "Cc")
    return (value or "Android")[:36]


def _bundle_id(source):
    normalized = unicodedata.normalize("NFKC", str(source or "Android")).casefold()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"{BASE_BUNDLE_ID}.source.{digest}"


def _read_plist(path):
    with path.open("rb") as handle:
        return plistlib.load(handle)


def _write_backup(path, prefix):
    if not path.exists():
        return
    backup_dir = SUPPORT_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, backup_dir / f"{prefix}-{stamp}{path.suffix}")


def _register_app(app_path):
    _run([str(LSREGISTER), "-f", str(app_path)], stdout=subprocess.DEVNULL,
         stderr=subprocess.DEVNULL)


def _variant_is_current(app_path, bundle_id, display_name, base_info):
    try:
        info = _read_plist(app_path / "Contents/Info.plist")
    except Exception:
        return False
    return (
        info.get("CFBundleIdentifier") == bundle_id
        and info.get("CFBundleDisplayName") == display_name
        and info.get("CFBundleVersion") == base_info.get("CFBundleVersion")
    )


def _build_variant(source):
    if not BASE_APP.is_dir():
        raise FileNotFoundError(f"notification app missing: {BASE_APP}")

    display_name = f"转发：{_source_label(source)}"
    bundle_id = _bundle_id(source)
    target = APPLICATIONS_DIR / f"{display_name}.app"
    base_info = _read_plist(BASE_APP / "Contents/Info.plist")
    if _variant_is_current(target, bundle_id, display_name, base_info):
        _register_app(target)
        return target, bundle_id, False

    APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(prefix=".xxzf-source-", dir=APPLICATIONS_DIR))
    temporary_app = temporary_root / target.name
    try:
        shutil.copytree(BASE_APP, temporary_app, symlinks=True)
        info_path = temporary_app / "Contents/Info.plist"
        info = _read_plist(info_path)
        old_executable = info["CFBundleExecutable"]
        old_executable_path = temporary_app / "Contents/MacOS" / old_executable
        new_executable_path = temporary_app / "Contents/MacOS" / display_name
        old_executable_path.rename(new_executable_path)
        info.update({
            "CFBundleDisplayName": display_name,
            "CFBundleName": display_name,
            "CFBundleExecutable": display_name,
            "CFBundleIdentifier": bundle_id,
        })
        with info_path.open("wb") as handle:
            plistlib.dump(info, handle, fmt=plistlib.FMT_XML, sort_keys=False)

        resources = temporary_app / "Contents/Resources"
        for strings_file in resources.glob("*.lproj/InfoPlist.strings"):
            strings_file.write_text(
                f'"CFBundleDisplayName" = "{display_name}";\n'
                f'"CFBundleName" = "{display_name}";\n',
                encoding="utf-8",
            )

        shutil.rmtree(temporary_app / "Contents/_CodeSignature", ignore_errors=True)
        _run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(temporary_app)],
             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if target.exists():
            _run([str(LSREGISTER), "-u", str(target)], stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL)
            shutil.rmtree(target)
        temporary_app.rename(target)
        _register_app(target)
        return target, bundle_id, True
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def _requirement_blob(app_path):
    result = _run(
        ["/usr/bin/codesign", "-d", "-r-", str(app_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    match = re.search(r'cdhash H"([0-9a-fA-F]{40})"', result.stdout)
    if not match:
        raise RuntimeError("could not read notification app code requirement")
    cdhash = bytes.fromhex(match.group(1))
    return struct.pack(">IIIII", 0xFADE0C00, 40, 1, 8, 20) + cdhash


def _ensure_notification_preferences(app_path, bundle_id):
    data = _read_plist(NCPREFS_FILE)
    apps = data.setdefault("apps", [])
    base = next((app for app in apps if app.get("bundle-id") == BASE_BUNDLE_ID), None)
    if base is None:
        raise RuntimeError("base notification permission is missing")

    requirement = _requirement_blob(app_path)
    entry = next((app for app in apps if app.get("bundle-id") == bundle_id), None)
    existing_source = (entry or {}).get("src", [])
    already_current = (
        entry is not None
        and entry.get("path") == str(app_path)
        and entry.get("auth") == 7
        and len(existing_source) == 1
        and existing_source[0].get("path") == str(app_path)
        and existing_source[0].get("req") == requirement
    )
    if already_current:
        return False

    if entry is None:
        entry = copy.deepcopy(base)
        apps.append(entry)
    entry.update({
        "bundle-id": bundle_id,
        "path": str(app_path),
        "auth": 7,
        "grouping": base.get("grouping", 0),
        "content_visibility": base.get("content_visibility", 0),
        "src": [{
            "req": requirement,
            "path": str(app_path),
            "flags": 0,
            "uuid": str(uuid.uuid4()).upper(),
        }],
    })

    _write_backup(NCPREFS_FILE, "ncprefs-before-source")
    temporary = SUPPORT_DIR / "ncprefs-source-import.plist"
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    with temporary.open("wb") as handle:
        plistlib.dump(data, handle, fmt=plistlib.FMT_BINARY)
    _run(["/usr/bin/defaults", "import", "com.apple.ncprefs", str(temporary)],
         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    temporary.unlink(missing_ok=True)
    return True


def _ensure_focus_permission(bundle_id):
    if not FOCUS_FILE.exists():
        return False
    try:
        with FOCUS_FILE.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except PermissionError:
        return False

    changed = False
    for datum in data.get("data", []):
        for config in datum.get("secureModeConfigurations", {}).values():
            secure = config.get("secureConfiguration", {})
            allowed = secure.get("allowedApplications", {})
            if BASE_BUNDLE_ID not in allowed or bundle_id in allowed:
                continue
            allowed[bundle_id] = copy.deepcopy(allowed[BASE_BUNDLE_ID])
            platforms = secure.setdefault("platforms", {})
            platforms[bundle_id] = platforms.get(BASE_BUNDLE_ID, 2)
            changed = True
    if not changed:
        return False

    try:
        _write_backup(FOCUS_FILE, "focus-before-source")
        data.setdefault("header", {})["timestamp"] = time.time() - 978307200
        temporary = FOCUS_FILE.with_suffix(".xxzf.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
        os.chmod(temporary, FOCUS_FILE.stat().st_mode)
        os.replace(temporary, FOCUS_FILE)
        return True
    except PermissionError:
        temporary = FOCUS_FILE.with_suffix(".xxzf.tmp")
        temporary.unlink(missing_ok=True)
        return False


def _restart_notification_services():
    for process in ("cfprefsd", "donotdisturbd", "usernoted", "NotificationCenter"):
        subprocess.run(["/usr/bin/killall", process], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    time.sleep(2)


def ensure_source_notifier(source):
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        app_path, bundle_id, rebuilt = _build_variant(source)
        prefs_changed = _ensure_notification_preferences(app_path, bundle_id)
        focus_changed = _ensure_focus_permission(bundle_id)
        if rebuilt or prefs_changed or focus_changed:
            _restart_notification_services()
            _register_app(app_path)
            time.sleep(0.5)
        return app_path


def deliver_notification(source, fallback_title, body):
    notification_title = fallback_title
    try:
        app_path = ensure_source_notifier(source)
        notification_title = ""
    except Exception as exc:
        app_path = BASE_APP
        error = str(exc)
    else:
        error = ""

    if not app_path.is_dir():
        return False, error or f"notification app missing: {app_path}"
    result = subprocess.run(
        [
            "/usr/bin/open", "-n", "-g", str(app_path), "--args",
            notification_title[:120], (body or "")[:240],
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=8,
    )
    if result.returncode != 0:
        return False, result.stderr.strip() or f"open exited {result.returncode}"
    return True, error
