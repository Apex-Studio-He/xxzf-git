#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVER_URL="${1:-https://example.com/xxzf}"
OFFICIAL_SERVER="https://example.com/xxzf"
SUPPORT_DIR="$HOME/Library/Application Support/XXZF"
PID_FILE="$SUPPORT_DIR/xxzf-air-notifier.pid"
LOG_FILE="$SUPPORT_DIR/xxzf-air-notifier.log"

if [ "$SERVER_URL" != "$OFFICIAL_SERVER" ]; then
  echo "Refusing untrusted XXZF server URL" >&2
  exit 2
fi

mkdir -p "$SUPPORT_DIR"
chmod 700 "$SUPPORT_DIR"

if [ -f "$PID_FILE" ] && ps -p "$(cat "$PID_FILE")" >/dev/null 2>&1; then
  kill "$(cat "$PID_FILE")" || true
  sleep 1
fi

: > "$LOG_FILE"
chmod 600 "$LOG_FILE"
nohup bash -c '
  while true; do
    python3 "$0/server/mac_client.py" "$1"
    echo "$(date "+%Y-%m-%d %H:%M:%S") notifier exited; restarting in 2s"
    sleep 2
  done
' "$ROOT" "$SERVER_URL" > "$LOG_FILE" 2>&1 &

echo $! > "$PID_FILE"
chmod 600 "$PID_FILE"
echo "Air notifier started: $(cat "$PID_FILE")"
