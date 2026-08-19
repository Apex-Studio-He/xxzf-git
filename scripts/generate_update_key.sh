#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
OUTPUT="${1:-}"
if [ -z "$OUTPUT" ]; then
  echo "Usage: generate_update_key.sh /private/path/update-signing" >&2
  exit 2
fi

mkdir -p "$OUTPUT"
OUTPUT="$(cd "$OUTPUT" && pwd -P)"
case "$OUTPUT/" in
  "$ROOT"/*)
    echo "Refusing to put update keys inside the source repository" >&2
    exit 3
    ;;
esac

PRIVATE_KEY="$OUTPUT/update-private.pem"
PUBLIC_PEM="$OUTPUT/update-public.pem"
PUBLIC_DER="$OUTPUT/update-public.der"
METADATA="$OUTPUT/update-public-values.txt"

for path in "$PRIVATE_KEY" "$PUBLIC_PEM" "$PUBLIC_DER" "$METADATA"; do
  if [ -e "$path" ] || [ -L "$path" ]; then
    echo "Refusing to overwrite existing path: $path" >&2
    exit 4
  fi
done

umask 077
/usr/bin/openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 \
  -out "$PRIVATE_KEY" >/dev/null 2>&1
/usr/bin/openssl pkey -in "$PRIVATE_KEY" -pubout -out "$PUBLIC_PEM" \
  >/dev/null 2>&1
/usr/bin/openssl pkey -in "$PRIVATE_KEY" -pubout -outform DER \
  -out "$PUBLIC_DER" >/dev/null 2>&1

PUBLIC_BASE64="$(/usr/bin/openssl base64 -A -in "$PUBLIC_DER")"
KEY_ID="$(/usr/bin/shasum -a 256 "$PUBLIC_DER" | /usr/bin/cut -c1-16)"
MODULUS="$(/usr/bin/openssl rsa -pubin -in "$PUBLIC_PEM" -modulus -noout \
  | /usr/bin/cut -d= -f2)"

{
  printf 'KEY_ID=%s\n' "$KEY_ID"
  printf 'PUBLIC_KEY_DER_BASE64=%s\n' "$PUBLIC_BASE64"
  printf 'PUBLIC_MODULUS_HEX=%s\n' "$MODULUS"
  printf 'PUBLIC_EXPONENT_HEX=010001\n'
} > "$METADATA"

chmod 600 "$PRIVATE_KEY" "$PUBLIC_PEM" "$PUBLIC_DER" "$METADATA"
printf 'UPDATE_KEY_CREATED directory=%s key_id=%s\n' "$OUTPUT" "$KEY_ID"
printf 'Private key contents were not printed. Keep update-private.pem offline.\n'
