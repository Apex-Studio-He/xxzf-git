#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
APP="$ROOT/dist/转发.app"
CONTENTS="$APP/Contents"
RESOURCES="$CONTENTS/Resources"
MACOS="$CONTENTS/MacOS"
HELPER="$RESOURCES/XXZFUpdateHelper"

"$HERE/test_notification_policy.sh"
"$HERE/test_agent_supervisor.sh"
PYTHONPATH="$ROOT/server" /usr/bin/python3 -m unittest -v test_mac_notifier_path

rm -rf "$APP"
mkdir -p "$MACOS" "$RESOURCES"

/usr/bin/clang \
  -fobjc-arc \
  -arch arm64 \
  -arch x86_64 \
  -mmacosx-version-min=10.14 \
  -framework Cocoa \
  -framework CoreImage \
  -framework Security \
  -framework SystemConfiguration \
  -framework UserNotifications \
  "$HERE/Receiver.m" \
  "$HERE/UpdateManager.m" \
  -o "$MACOS/转发"

/usr/bin/clang \
  -fobjc-arc \
  -arch arm64 \
  -arch x86_64 \
  -mmacosx-version-min=10.14 \
  -framework Foundation \
  "$HERE/UpdateHelper.m" \
  -o "$HELPER"
chmod 0500 "$HELPER"

cp "$HERE/Info.plist" "$CONTENTS/Info.plist"
cp "$ROOT/server/mac_client.py" "$RESOURCES/mac_client_core.py"
cp "$HERE/AgentRunner.py" "$RESOURCES/mac_client.py"
chmod 0500 "$RESOURCES/mac_client.py" "$RESOURCES/mac_client_core.py"

if [ -f "$ROOT/server/mac_notifier/AppIcon-v3.png" ]; then
  cp "$ROOT/server/mac_notifier/AppIcon-v3.png" "$RESOURCES/AppIcon.png"
  /usr/libexec/PlistBuddy -c 'Add :CFBundleIconFile string AppIcon.png' "$CONTENTS/Info.plist"
fi

"$ROOT/scripts/sign_macos_app.sh" "$APP"
echo "App: $APP"
