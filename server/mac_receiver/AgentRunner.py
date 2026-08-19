#!/usr/bin/env python3
"""Run the existing receiver with credentials supplied once over an anonymous pipe."""

import importlib.util
import json
import os
from pathlib import Path
import sys


SUPPORT = Path.home() / "Library" / "Application Support" / "XXZF"
CONFIG = SUPPORT / "receiver.json"
CORE = SUPPORT / "mac_client_core.py"


def fail_closed(message):
    print(message, file=sys.stderr, flush=True)
    raise SystemExit(2)


if sys.argv[1:] != ["--credentials-stdin"]:
    fail_closed("XXZF agent requires the private credential pipe")

raw = sys.stdin.buffer.read(32 * 1024 + 1)
if not raw or len(raw) > 32 * 1024:
    fail_closed("XXZF agent rejected credential input")

try:
    initial = json.loads(raw.decode("utf-8"))
except Exception:
    fail_closed("XXZF agent rejected credential input")

receiver_id = str(initial.get("receiverId") or "").strip()
receiver_secret = str(initial.get("receiverSecret") or "").strip()
if not receiver_id or not receiver_secret:
    fail_closed("XXZF agent credential is unavailable")

spec = importlib.util.spec_from_file_location("xxzf_mac_client_core", CORE)
if spec is None or spec.loader is None:
    fail_closed("XXZF agent runtime is unavailable")
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


def secure_credentials():
    try:
        current = json.loads(CONFIG.read_text("utf-8"))
    except Exception:
        return None
    if str(current.get("receiverId") or "").strip() != receiver_id:
        os._exit(75)
    result = dict(current)
    result["receiverId"] = receiver_id
    result["receiverSecret"] = receiver_secret
    result["servers"] = [core.OFFICIAL_SERVER]
    return result


def restart_for_repaired_credentials(_rejected):
    os._exit(75)


core.load_receiver_credentials = secure_credentials
core.wait_for_replacement_credentials = restart_for_repaired_credentials
core.run()
