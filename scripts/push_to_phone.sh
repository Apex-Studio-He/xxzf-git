#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
ADB_BIN="${ADB_BIN:-$ANDROID_HOME/platform-tools/adb}"
serial="${1:-}"

if [ -z "$serial" ] || [ "$#" -ne 1 ]; then
  echo "Usage: $0 ANDROID_SERIAL" >&2
  exit 2
fi
if [ ! -x "$ADB_BIN" ]; then
  echo "Cannot find adb at $ADB_BIN" >&2
  exit 1
fi
if [ "$("$ADB_BIN" -s "$serial" get-state 2>/dev/null || true)" != "device" ]; then
  echo "Android device is not available or not authorized: $serial" >&2
  exit 1
fi

listener_component="com.zundu.notifybridge/com.zundu.notifybridge.NotifyBridgeService"
listener_was_enabled=0
confirm_pid=""

stop_confirmation_helper() {
  if [ -n "$confirm_pid" ] && kill -0 "$confirm_pid" >/dev/null 2>&1; then
    kill -TERM "$confirm_pid" >/dev/null 2>&1 || true
    wait "$confirm_pid" >/dev/null 2>&1 || true
  fi
}
trap stop_confirmation_helper EXIT

restore_listener_if_previously_allowed() {
  if [ "$listener_was_enabled" -eq 1 ]; then
    "$ADB_BIN" -s "$serial" shell cmd notification allow_listener \
      "$listener_component" >/dev/null 2>&1 || true
  fi
}

cd "$ROOT/android"
./build.sh
enabled_listeners="$("$ADB_BIN" -s "$serial" shell settings get secure \
  enabled_notification_listeners 2>/dev/null | tr -d '\r')"
case ":$enabled_listeners:" in
  *":$listener_component:"*) listener_was_enabled=1 ;;
esac

"$ADB_BIN" -s "$serial" shell am force-stop com.zundu.notifybridge \
  >/dev/null 2>&1 || true
ADB_BIN="$ADB_BIN" "$ROOT/scripts/confirm_vivo_install.sh" "$serial" &
confirm_pid=$!
if ! "$ADB_BIN" -s "$serial" install --no-incremental -r \
  "$ROOT/dist/NotifyBridge-debug.apk"; then
  exit 1
fi
stop_confirmation_helper
confirm_pid=""

"$ADB_BIN" -s "$serial" shell pm grant com.zundu.notifybridge \
  android.permission.POST_NOTIFICATIONS >/dev/null 2>&1 || true
"$ADB_BIN" -s "$serial" shell appops set com.zundu.notifybridge \
  POST_NOTIFICATION allow >/dev/null 2>&1 || true
"$ADB_BIN" -s "$serial" shell appops set com.zundu.notifybridge \
  RUN_IN_BACKGROUND allow >/dev/null 2>&1 || true
"$ADB_BIN" -s "$serial" shell appops set com.zundu.notifybridge \
  RUN_ANY_IN_BACKGROUND allow >/dev/null 2>&1 || true
"$ADB_BIN" -s "$serial" shell appops set com.zundu.notifybridge \
  AUTO_START allow >/dev/null 2>&1 || true
"$ADB_BIN" -s "$serial" shell cmd deviceidle whitelist \
  +com.zundu.notifybridge >/dev/null 2>&1 || true
restore_listener_if_previously_allowed
"$ADB_BIN" -s "$serial" shell monkey -p com.zundu.notifybridge \
  -c android.intent.category.LAUNCHER 1 >/dev/null
sleep 1
restore_listener_if_previously_allowed
