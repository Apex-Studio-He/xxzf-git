#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$HERE/Info.plist")"
VERSION_CODE="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$HERE/Info.plist")"
WORK="$(mktemp -d)"
trap 'hdiutil detach /Volumes/XXZFUpdateTest >/dev/null 2>&1 || true; rm -rf "$WORK"' EXIT
mkdir -p "$WORK/source" "$WORK/home"
cp -R "$ROOT/dist/转发.app" "$WORK/source/转发.app"
hdiutil create -quiet -volname XXZFUpdateTest -srcfolder "$WORK/source" -format UDZO "$WORK/update.dmg"

/usr/bin/clang \
  -fobjc-arc \
  -mmacosx-version-min=10.14 \
  -framework Cocoa \
  -framework Security \
  "$HERE/UpdateManager.m" \
  "$HERE/UpdateInstallTests.m" \
  -o "$WORK/install-tests"
CFFIXED_USER_HOME="$WORK/home" "$WORK/install-tests" "$WORK/update.dmg" \
  "$VERSION" "$VERSION_CODE"

set +e
CFFIXED_USER_HOME="$WORK/home" "$ROOT/dist/转发.app/Contents/Resources/XXZFUpdateHelper" \
  --apply /tmp/not-allowed.app "$VERSION" "$VERSION_CODE" \
  0000000000000000000000000000000000000000 999999
STATUS=$?
set -e
if [ "$STATUS" -ne 3 ]; then
  echo "FAIL: helper accepted an installation path outside Applications" >&2
  exit 1
fi
echo "PASS: helper rejected an arbitrary installation path"

mkdir -p "$WORK/redirect"
ln -s "$WORK/redirect" "$WORK/home/Applications"
set +e
CFFIXED_USER_HOME="$WORK/home" "$ROOT/dist/转发.app/Contents/Resources/XXZFUpdateHelper" \
  --apply "$WORK/home/Applications/转发.app" "$VERSION" "$VERSION_CODE" \
  0000000000000000000000000000000000000000 999999
STATUS=$?
set -e
if [ "$STATUS" -ne 3 ]; then
  echo "FAIL: helper accepted a symlinked Applications path" >&2
  exit 1
fi
echo "PASS: helper rejected a symlinked Applications path"
