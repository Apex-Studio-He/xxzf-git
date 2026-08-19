#!/usr/bin/env bash
set -euo pipefail

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

tmp_dir="$(mktemp -d)"
xml="$tmp_dir/window.xml"
device_xml="/sdcard/xxzf-vivo-install-$$.xml"
setting_read_failed="__XXZF_SETTING_READ_FAILED__"

read_setting() {
  local scope="$1"
  local value
  if value="$("$ADB_BIN" -s "$serial" shell settings get \
      "$scope" vivo_monkey_test 2>/dev/null)"; then
    printf '%s' "$value" | tr -d '\r\n'
  else
    printf '%s' "$setting_read_failed"
  fi
}

restore_setting() {
  local scope="$1"
  local value="$2"
  if [ "$value" = "$setting_read_failed" ]; then
    return
  fi
  if [ -z "$value" ] || [ "$value" = "null" ]; then
    "$ADB_BIN" -s "$serial" shell settings delete \
      "$scope" vivo_monkey_test >/dev/null 2>&1 || true
  else
    "$ADB_BIN" -s "$serial" shell settings put \
      "$scope" vivo_monkey_test "$value" >/dev/null 2>&1 || true
  fi
}

original_secure_value="$(read_setting secure)"
original_global_value="$(read_setting global)"

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  restore_setting secure "$original_secure_value"
  restore_setting global "$original_global_value"
  "$ADB_BIN" -s "$serial" shell rm -f "$device_xml" >/dev/null 2>&1 || true
  if [ -n "$tmp_dir" ] && [ -d "$tmp_dir" ]; then
    rm -rf "$tmp_dir"
  fi
  exit "$status"
}
trap 'cleanup' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

"$ADB_BIN" -s "$serial" shell settings put secure \
  vivo_monkey_test 1 >/dev/null 2>&1 || true
"$ADB_BIN" -s "$serial" shell settings put global \
  vivo_monkey_test 1 >/dev/null 2>&1 || true

dump_window() {
  "$ADB_BIN" -s "$serial" shell uiautomator dump "$device_xml" \
    >/dev/null 2>&1 || return 1
  "$ADB_BIN" -s "$serial" pull "$device_xml" "$xml" \
    >/dev/null 2>&1 || return 1
  [ -s "$xml" ]
}

bounds_for_xpath() {
  local xpath="$1"
  /usr/bin/xmllint --xpath "string(($xpath)[1]/@bounds)" \
    "$xml" 2>/dev/null || true
}

bounds_for_marker() {
  local marker="$1"
  local require_enabled="${2:-false}"
  local node
  node="$(sed 's/></>\
</g' "$xml" | grep -F -m 1 -- "$marker" || true)"
  if ! printf '%s' "$node" \
      | grep -q 'package="com.android.packageinstaller"'; then
    return
  fi
  if [ "$require_enabled" = "true" ] \
      && { ! printf '%s' "$node" | grep -q 'enabled="true"' \
        || ! printf '%s' "$node" | grep -q 'clickable="true"'; }; then
    return
  fi
  printf '%s' "$node" \
    | sed -nE 's/.*bounds="(\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\])".*/\1/p'
}

tap_bounds() {
  local bounds="$1"
  local coordinates
  local left top right bottom x y
  coordinates="$(printf '%s' "$bounds" | sed -nE \
    's/^\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]$/\1 \2 \3 \4/p')"
  [ -n "$coordinates" ] || return 1
  read -r left top right bottom <<EOF
$coordinates
EOF
  if [ "$right" -le "$left" ] || [ "$bottom" -le "$top" ] \
      || [ "$right" -gt 10000 ] || [ "$bottom" -gt 10000 ]; then
    return 1
  fi
  x=$(((left + right) / 2))
  y=$(((top + bottom) / 2))
  "$ADB_BIN" -s "$serial" shell input tap "$x" "$y" >/dev/null
}

checkbox_xpath="//node[@package='com.android.packageinstaller' and @enabled='true' and @clickable='true' and contains(@resource-id,'deleted_file_state_cb')]"
button_xpath="//node[@package='com.android.packageinstaller' and @enabled='true' and @clickable='true' and (@resource-id='android:id/button1' or @content-desc='继续安装' or @text='继续安装' or @content-desc='安装' or @text='安装')]"
checkbox_retry_wait=0

for _ in $(seq 1 45); do
  if ! dump_window; then
    sleep 0.5
    continue
  fi

  checkbox_bounds="$(bounds_for_xpath "$checkbox_xpath")"
  if [ -z "$checkbox_bounds" ]; then
    checkbox_bounds="$(bounds_for_marker "deleted_file_state_cb")"
  fi
  checkbox_checked="$(/usr/bin/xmllint --xpath \
    "string(($checkbox_xpath)[1]/@checked)" "$xml" 2>/dev/null || true)"
  if [ -n "$checkbox_bounds" ] && [ "$checkbox_checked" != "true" ]; then
    if [ "$checkbox_retry_wait" -eq 0 ]; then
      if tap_bounds "$checkbox_bounds"; then
        checkbox_retry_wait=6
      fi
    else
      checkbox_retry_wait=$((checkbox_retry_wait - 1))
    fi
    sleep 0.5
    continue
  fi
  checkbox_retry_wait=0

  button_bounds="$(bounds_for_xpath "$button_xpath")"
  if [ -z "$button_bounds" ]; then
    button_bounds="$(bounds_for_marker "android:id/button1" true)"
  fi
  if [ -z "$button_bounds" ]; then
    button_bounds="$(bounds_for_marker "继续安装" true)"
  fi
  if [ -n "$button_bounds" ] && tap_bounds "$button_bounds"; then
    sleep 2
    exit 0
  fi
  sleep 0.5
done

exit 1
