#!/usr/bin/env bash
set -euo pipefail

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
HERE="$(cd "$(dirname "$0")" && pwd)"
PRIVATE_KEY="$WORK/private.pem"
PUBLIC_DER="$WORK/public.der"
/usr/bin/openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 \
  -out "$PRIVATE_KEY" >/dev/null 2>&1
/usr/bin/openssl pkey -in "$PRIVATE_KEY" -pubout -outform DER \
  -out "$PUBLIC_DER" >/dev/null 2>&1
PUBLIC_KEY_BASE64="$(/usr/bin/openssl base64 -A -in "$PUBLIC_DER")"
PACKAGE="$WORK/forwarder-macos-1.3.1-test.dmg"
printf 'XXZF macOS updater validation fixture\n' > "$PACKAGE"
SIZE="$(stat -f %z "$PACKAGE")"
SHA256="$(shasum -a 256 "$PACKAGE" | awk '{print $1}')"
PUBLISHED_AT="2026-07-12T12:00:00Z"
NOTES="Security update test"
CANONICAL="$WORK/canonical.txt"
/usr/bin/python3 - "$CANONICAL" "$SHA256" "$SIZE" "$PUBLISHED_AT" "$NOTES" <<'PY'
import sys

path, sha256, size, published_at, notes = sys.argv[1:]
fields = [
    "1", "test", "macos", "15", "1.3.1",
    "https://updates.example.com/downloads/forwarder/test/forwarder-macos-1.3.1-test.dmg",
    sha256, size, published_at, notes, "8545bd8392ab5de2",
]
with open(path, "wb") as handle:
    handle.write("\n".join(fields).encode("utf-8"))
PY
/usr/bin/openssl dgst -sha256 -sign "$PRIVATE_KEY" -out "$WORK/signature.bin" "$CANONICAL"
SIGNATURE="$(base64 < "$WORK/signature.bin" | tr -d '\n')"
/usr/bin/python3 - "$WORK/manifest.json" "$SHA256" "$SIZE" "$PUBLISHED_AT" "$NOTES" "$SIGNATURE" <<'PY'
import json
import sys

path, sha256, size, published_at, notes, signature = sys.argv[1:]
with open(path, "w", encoding="utf-8") as handle:
    json.dump({
        "schema": 1,
        "channel": "test",
        "platform": "macos",
        "versionCode": 15,
        "version": "1.3.1",
        "url": "https://updates.example.com/downloads/forwarder/test/forwarder-macos-1.3.1-test.dmg",
        "sha256": sha256,
        "size": int(size),
        "publishedAt": published_at,
        "notes": notes,
        "keyId": "8545bd8392ab5de2",
        "signature": signature,
    }, handle, separators=(",", ":"), ensure_ascii=True)
PY

/usr/bin/clang \
  "-DXXZF_TEST_PUBLIC_KEY_BASE64=\"$PUBLIC_KEY_BASE64\"" \
  -fobjc-arc \
  -mmacosx-version-min=10.14 \
  -framework Cocoa \
  -framework Security \
  "$HERE/UpdateManager.m" \
  "$HERE/UpdateManagerTests.m" \
  -o "$WORK/update-tests"
"$WORK/update-tests" "$WORK/manifest.json" "$PACKAGE"
