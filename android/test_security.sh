#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
JAVA_HOME="${JAVA_HOME:-$HOME/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
PRIVATE_KEY="$tmp/private.pem"
PUBLIC_DER="$tmp/public.der"
/usr/bin/openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 \
  -out "$PRIVATE_KEY" >/dev/null 2>&1
/usr/bin/openssl pkey -in "$PRIVATE_KEY" -pubout -outform DER \
  -out "$PUBLIC_DER" >/dev/null 2>&1
PUBLIC_KEY_BASE64="$(/usr/bin/openssl base64 -A -in "$PUBLIC_DER")"

printf '%s' '1
test
android
999
9.9.9
https://updates.example.com/downloads/forwarder/test/forwarder-android-9.9.9-test.apk
0000000000000000000000000000000000000000000000000000000000000000
12345
2026-07-12T00:00:00Z
security test
8545bd8392ab5de2' > "$tmp/canonical.txt"

/usr/bin/openssl dgst -sha256 -sign "$PRIVATE_KEY" \
  -out "$tmp/signature.bin" "$tmp/canonical.txt"
signature="$(/usr/bin/openssl base64 -A -in "$tmp/signature.bin")"

"$JAVA_HOME/bin/javac" -encoding UTF-8 -d "$tmp/classes" \
  "$PROJECT_DIR/src/com/zundu/notifybridge/UpdateSecurity.java" \
  "$PROJECT_DIR/tests/UpdateSecurityTest.java"
"$JAVA_HOME/bin/java" -cp "$tmp/classes" \
  com.zundu.notifybridge.UpdateSecurityTest "$signature" "$PUBLIC_KEY_BASE64"

/usr/bin/python3 -m unittest "$PROJECT_DIR/tests/security_policy_test.py"
