#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TEST_BIN="$(mktemp "${TMPDIR:-/tmp}/xxzf-notification-policy.XXXXXX")"
trap 'rm -f "$TEST_BIN"' EXIT

/usr/bin/clang \
  -fobjc-arc \
  -mmacosx-version-min=10.14 \
  -framework Foundation \
  -framework UserNotifications \
  "$HERE/NotificationPolicyTests.m" \
  -o "$TEST_BIN"

"$TEST_BIN"
