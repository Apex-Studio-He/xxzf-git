#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$HERE/Info.plist")"
APP="$ROOT/dist/转发.app"
DMG="$ROOT/安装包/转发-macOS-$VERSION-测试版.dmg"
STAGING="$(mktemp -d "${TMPDIR:-/tmp}/xxzf-macos-dmg.XXXXXX")"
trap 'rm -rf "$STAGING"' EXIT

"$HERE/build.sh"
mkdir -p "$(dirname "$DMG")"
cp -R "$APP" "$STAGING/转发.app"
ln -s /Applications "$STAGING/Applications"
rm -f "$DMG"
hdiutil create -quiet -volname "转发" -srcfolder "$STAGING" -ov -format UDZO "$DMG"
shasum -a 256 "$DMG" > "$DMG.sha256"

echo "DMG: $DMG"
