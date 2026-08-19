#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BINARY="$HERE/.test-agent-supervisor"
PID_FILE="$(mktemp "${TMPDIR:-/tmp}/xxzf-agent-child.XXXXXX")"
SUPERVISOR_PID=""
CHILD_PID=""

cleanup() {
  [ -z "$SUPERVISOR_PID" ] || kill -KILL "$SUPERVISOR_PID" 2>/dev/null || true
  [ -z "$CHILD_PID" ] || kill -KILL "$CHILD_PID" 2>/dev/null || true
  rm -f "$BINARY" "$PID_FILE"
}
trap cleanup EXIT HUP INT TERM

clang -fobjc-arc -framework Foundation \
  "$HERE/test_agent_supervisor.m" -o "$BINARY"

"$BINARY" "$PID_FILE" &
SUPERVISOR_PID=$!
for _ in $(seq 1 50); do
  [ -s "$PID_FILE" ] && break
  sleep 0.05
done
[ -s "$PID_FILE" ] || {
  echo "agent supervisor did not start its child" >&2
  exit 1
}
CHILD_PID="$(tr -d '[:space:]' < "$PID_FILE")"
kill -TERM "$SUPERVISOR_PID"
for _ in $(seq 1 50); do
  kill -0 "$SUPERVISOR_PID" 2>/dev/null || break
  sleep 0.05
done
if kill -0 "$SUPERVISOR_PID" 2>/dev/null; then
  echo "agent supervisor did not stop after SIGTERM" >&2
  exit 1
fi
wait "$SUPERVISOR_PID"
if kill -0 "$CHILD_PID" 2>/dev/null; then
  echo "agent supervisor left its child running" >&2
  exit 1
fi
echo "Agent supervisor lifecycle checks passed"
