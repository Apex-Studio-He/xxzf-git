#!/usr/bin/env bash
set -euo pipefail

ADB_BIN="${ADB_BIN:-$HOME/Library/Android/sdk/platform-tools/adb}"
MINI_SSH_TARGET="${XXZF_MINI_SSH_TARGET:-}"
MAC_LOG="${XXZF_MAC_RECEIVER_LOG:-$HOME/Library/Application Support/XXZF/xxzf-air-notifier.log}"
EXPECTED_VERSION="${XXZF_EXPECTED_ANDROID_VERSION:-0.9.16}"
EXPECTED_CODE="${XXZF_EXPECTED_ANDROID_CODE:-26}"
PACKAGE="com.zundu.notifybridge"
LISTENER="$PACKAGE/$PACKAGE.NotifyBridgeService"
serial="${1:-}"
mode="${2:-awake}"

if [ -z "$serial" ] || [ "$#" -gt 2 ]; then
  echo "Usage: $0 ANDROID_SERIAL [awake|screen-off]" >&2
  exit 2
fi
if [ -z "$MINI_SSH_TARGET" ]; then
  echo "Set XXZF_MINI_SSH_TARGET to your own server before running this test" >&2
  exit 2
fi
case "$mode" in
  awake|screen-off) ;;
  *)
    echo "Mode must be awake or screen-off" >&2
    exit 2
    ;;
esac
if [ ! -x "$ADB_BIN" ]; then
  echo "Cannot find adb at $ADB_BIN" >&2
  exit 1
fi
if [ "$("$ADB_BIN" -s "$serial" get-state 2>/dev/null || true)" != "device" ]; then
  echo "Android device is unavailable or unauthorized: $serial" >&2
  exit 1
fi
if [ ! -f "$MAC_LOG" ]; then
  echo "Mac receiver log is unavailable: $MAC_LOG" >&2
  exit 1
fi

temporary="$(mktemp -d "${TMPDIR:-/tmp}/xxzf-android-live.XXXXXX")"
logcat_pid=""
cleanup() {
  if [ -n "$logcat_pid" ] && kill -0 "$logcat_pid" >/dev/null 2>&1; then
    kill -TERM "$logcat_pid" >/dev/null 2>&1 || true
    wait "$logcat_pid" >/dev/null 2>&1 || true
  fi
  rm -rf "$temporary"
}
trap cleanup EXIT INT TERM HUP

package_dump="$("$ADB_BIN" -s "$serial" shell dumpsys package "$PACKAGE")"
printf '%s\n' "$package_dump" | grep -F "versionName=$EXPECTED_VERSION" >/dev/null
printf '%s\n' "$package_dump" | grep -F "versionCode=$EXPECTED_CODE " >/dev/null

enabled_listeners="$("$ADB_BIN" -s "$serial" shell settings get secure enabled_notification_listeners | tr -d '\r')"
case ":$enabled_listeners:" in
  *":$LISTENER:"*) ;;
  *)
    echo "Notification-listener permission is not enabled" >&2
    exit 1
    ;;
esac

service_dump="$("$ADB_BIN" -s "$serial" shell dumpsys activity services "$PACKAGE/.NotifyBridgeService")"
for state in "requested=true" "received=true" "hasBound=true"; do
  printf '%s\n' "$service_dump" | grep -F "$state" >/dev/null || {
    echo "Notification-listener service is not fully bound: $state" >&2
    exit 1
  }
done

installed_path="$("$ADB_BIN" -s "$serial" shell pm path "$PACKAGE" | tr -d '\r' | sed -n 's/^package://p' | head -n 1)"
if [ -z "$installed_path" ]; then
  echo "Installed APK path is unavailable" >&2
  exit 1
fi
"$ADB_BIN" -s "$serial" pull "$installed_path" "$temporary/installed.apk" >/dev/null
project_root="$(cd "$(dirname "$0")/.." && pwd)"
cmp -s "$project_root/dist/NotifyBridge-debug.apk" "$temporary/installed.apk" || {
  echo "Installed APK does not match the tested dist APK" >&2
  exit 1
}

if [ "$mode" = "screen-off" ]; then
  "$ADB_BIN" -s "$serial" shell svc power stayon false
  "$ADB_BIN" -s "$serial" shell input keyevent KEYCODE_SLEEP
  sleep 2
  if [ "$("$ADB_BIN" -s "$serial" shell settings get global stay_on_while_plugged_in | tr -d '\r')" != "0" ]; then
    echo "USB stay-awake could not be disabled" >&2
    exit 1
  fi
  "$ADB_BIN" -s "$serial" shell dumpsys power |
    grep -F "mWakefulness=Asleep" >/dev/null || {
      echo "Android device did not enter the asleep state" >&2
      exit 1
    }
fi

delivery_count() {
  awk '/notification delivered/{count++} END{print count + 0}' "$MAC_LOG"
}

before_delivery="$(delivery_count)"
marker="XXZF-E2E-$(date +%Y%m%d%H%M%S)-$$"

"$ADB_BIN" -s "$serial" logcat -T 1 -v brief \
  -s XXZFListener:I XXZFBridge:I '*:S' \
  >"$temporary/android.log" 2>&1 &
logcat_pid=$!
sleep 1

"$ADB_BIN" -s "$serial" shell cmd notification post \
  -t "$marker" "xxzf-$marker" "$marker" >/dev/null

android_ok=0
mac_ok=0
attempt=0
while [ "$attempt" -lt 20 ]; do
  if grep -F "notification accepted pkg=com.android.shell" "$temporary/android.log" >/dev/null &&
     grep -F "sent via https://example.com/xxzf/v1/notify" "$temporary/android.log" >/dev/null; then
    android_ok=1
  fi
  after_delivery="$(delivery_count)"
  if [ "$after_delivery" -gt "$before_delivery" ]; then
    mac_ok=1
  fi
  if [ "$android_ok" -eq 1 ] && [ "$mac_ok" -eq 1 ]; then
    break
  fi
  attempt=$((attempt + 1))
  sleep 1
done
if [ "$android_ok" -ne 1 ]; then
  echo "Android did not accept and send the real listener event" >&2
  exit 1
fi
if [ "$mac_ok" -ne 1 ]; then
  echo "Mac receiver did not record delivery in the test window" >&2
  exit 1
fi

audit_json="$(
  /usr/bin/ssh \
    -o BatchMode=yes \
    -o ConnectTimeout=8 \
    -o ServerAliveInterval=5 \
    -o ServerAliveCountMax=1 \
    "$MINI_SSH_TARGET" \
    "/usr/bin/curl -fsS 'http://127.0.0.1:8787/audit/api/events?limit=10&q=$marker'"
)"
audit_result="$(
  printf '%s' "$audit_json" |
    MARKER="$marker" /usr/bin/python3 -c '
import json
import os
import sys

payload = json.load(sys.stdin)
marker = os.environ["MARKER"]
matches = [
    event for event in payload.get("events", [])
    if event.get("title") == marker or event.get("body") == marker
]
if payload.get("ok") is not True or len(matches) != 1:
    raise SystemExit(1)
event = matches[0]
destinations = event.get("destinations") or []
if not destinations:
    raise SystemExit(1)
print("mini_match=1 destination_count=%d received_at=%s" % (
    len(destinations), event.get("received_at", ""),
))
'
)" || {
  echo "Mini audit did not contain exactly one routed marker event" >&2
  exit 1
}

if [ "$mode" = "screen-off" ]; then
  "$ADB_BIN" -s "$serial" shell dumpsys power |
    grep -F "mWakefulness=Asleep" >/dev/null || {
      echo "Android device woke during the screen-off test" >&2
      exit 1
    }
fi

printf '%s\n' "$audit_result"
echo "android_listener=pass mac_delivery=pass installed_apk=exact mode=$mode"
