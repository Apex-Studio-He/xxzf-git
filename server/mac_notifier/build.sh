#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SOURCE_DIR="$ROOT/server/mac_notifier"
APP_DIR="$ROOT/dist/XXZFNotifier.app"
ICON_SOURCE="$SOURCE_DIR/AppIcon-source.png"
ICONSET_DIR="$ROOT/dist/XXZFNotifier.iconset"
EXECUTABLE_NAME="讯桥通知"

rm -rf "$APP_DIR" "$ICONSET_DIR"
mkdir -p \
  "$APP_DIR/Contents/MacOS" \
  "$APP_DIR/Contents/Resources/zh-Hans.lproj" \
  "$ICONSET_DIR"
cp "$SOURCE_DIR/Info.plist" "$APP_DIR/Contents/Info.plist"
cp "$SOURCE_DIR/InfoPlist.strings" \
  "$APP_DIR/Contents/Resources/zh-Hans.lproj/InfoPlist.strings"

render_icon() {
  local size="$1"
  local name="$2"
  sips -z "$size" "$size" "$ICON_SOURCE" --out "$ICONSET_DIR/$name" >/dev/null
}

render_icon 16 icon_16x16.png
render_icon 32 icon_16x16@2x.png
render_icon 32 icon_32x32.png
render_icon 64 icon_32x32@2x.png
render_icon 128 icon_128x128.png
render_icon 256 icon_128x128@2x.png
render_icon 256 icon_256x256.png
render_icon 512 icon_256x256@2x.png
render_icon 512 icon_512x512.png
render_icon 1024 icon_512x512@2x.png
iconutil -c icns "$ICONSET_DIR" -o "$APP_DIR/Contents/Resources/AppIcon.icns"
rm -rf "$ICONSET_DIR"

xcrun clang \
  -fobjc-arc \
  -fblocks \
  -framework Cocoa \
  -framework UserNotifications \
  -mmacosx-version-min=10.14 \
  "$SOURCE_DIR/Notifier.m" \
  -o "$APP_DIR/Contents/MacOS/$EXECUTABLE_NAME"

"$ROOT/scripts/sign_macos_app.sh" "$APP_DIR" >/dev/null
echo "$APP_DIR"
