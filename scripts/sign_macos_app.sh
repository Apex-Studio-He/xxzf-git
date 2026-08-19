#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ] || [ ! -d "$1" ]; then
  echo "Usage: $0 /path/to/App.app" >&2
  exit 2
fi

APP="$1"
BUILD_VARIANT="${BUILD_VARIANT:-debug}"

case "$BUILD_VARIANT" in
  debug)
    /usr/bin/codesign --force --deep --sign - "$APP"
    ;;
  release)
    : "${XXZF_MAC_SIGN_IDENTITY:?Set XXZF_MAC_SIGN_IDENTITY for a release build}"
    : "${XXZF_MAC_EXPECTED_TEAM_ID:?Set XXZF_MAC_EXPECTED_TEAM_ID for a release build}"
    case "$XXZF_MAC_SIGN_IDENTITY" in
      "Developer ID Application: "*) ;;
      *)
        echo "Release builds require a Developer ID Application identity" >&2
        exit 1
        ;;
    esac
    /usr/bin/codesign \
      --force \
      --deep \
      --options runtime \
      --timestamp \
      --sign "$XXZF_MAC_SIGN_IDENTITY" \
      "$APP"
    ACTUAL_TEAM="$(/usr/bin/codesign -d --verbose=4 "$APP" 2>&1 | sed -n 's/^TeamIdentifier=//p' | head -n 1)"
    if [ -z "$ACTUAL_TEAM" ] || [ "$ACTUAL_TEAM" != "$XXZF_MAC_EXPECTED_TEAM_ID" ]; then
      echo "Signed app TeamIdentifier does not match the pinned team" >&2
      exit 1
    fi
    ;;
  *)
    echo "BUILD_VARIANT must be debug or release" >&2
    exit 1
    ;;
esac

/usr/bin/codesign --verify --deep --strict --verbose=2 "$APP"
