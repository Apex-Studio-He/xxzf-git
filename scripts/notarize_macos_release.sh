#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
  echo "Usage: $0 /path/to/signed-release.dmg" >&2
  exit 2
fi

ARTIFACT="$1"
: "${XXZF_NOTARY_KEYCHAIN_PROFILE:?Set XXZF_NOTARY_KEYCHAIN_PROFILE}"

if [ -L "$ARTIFACT" ]; then
  echo "Refusing to notarize a symbolic link" >&2
  exit 1
fi

/usr/bin/xcrun notarytool submit \
  "$ARTIFACT" \
  --keychain-profile "$XXZF_NOTARY_KEYCHAIN_PROFILE" \
  --wait
/usr/bin/xcrun stapler staple "$ARTIFACT"
/usr/bin/xcrun stapler validate "$ARTIFACT"
/usr/sbin/spctl --assess --type open --context context:primary-signature --verbose=2 "$ARTIFACT"
/usr/bin/shasum -a 256 "$ARTIFACT" > "$ARTIFACT.sha256"
echo "Notarized artifact: $ARTIFACT"
