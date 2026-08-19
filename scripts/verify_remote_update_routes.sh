#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 4 ] || [ $((($# - 2) % 2)) -ne 0 ]; then
  echo "Usage: verify_remote_update_routes.sh SSH_BIN SSH_TARGET PLATFORM PACKAGE..." >&2
  exit 2
fi

SSH_BIN="$1"
SSH_TARGET="$2"
shift 2
[ -f "$SSH_BIN" ] && [ -x "$SSH_BIN" ] && [ ! -L "$SSH_BIN" ] || {
  echo "SSH executable is missing or unsafe" >&2
  exit 3
}

NGINX_DUMP="$(/usr/bin/mktemp "${TMPDIR:-/tmp}/xxzf-active-nginx.XXXXXX")"
cleanup() { /bin/rm -f "$NGINX_DUMP"; }
trap cleanup EXIT

if ! "$SSH_BIN" -o BatchMode=yes "$SSH_TARGET" \
    /usr/local/bin/nginx -T -c /usr/local/etc/nginx/nginx.conf \
    >"$NGINX_DUMP" 2>&1; then
  echo "Unable to inspect active remote nginx configuration" >&2
  exit 4
fi

if [ "$(/usr/bin/grep -Fxc \
    '# configuration file /usr/local/etc/nginx/xxzf_public_routes.inc:' \
    "$NGINX_DUMP" || true)" -ne 1 ]; then
  echo "Authoritative XXZF nginx include is not active exactly once" >&2
  exit 5
fi

while [ "$#" -gt 0 ]; do
  platform="$1"
  package_name="$2"
  shift 2
  case "$platform" in
    android|macos|windows) ;;
    *) echo "Unsupported route platform: $platform" >&2; exit 6 ;;
  esac
  manifest_selector="    location = /downloads/forwarder/test/$platform.json {"
  package_selector="    location = /downloads/forwarder/test/$package_name {"
  manifest_count="$(/usr/bin/grep -Fxc "$manifest_selector" "$NGINX_DUMP" || true)"
  package_count="$(/usr/bin/grep -Fxc "$package_selector" "$NGINX_DUMP" || true)"
  if [ "$manifest_count" -ne 1 ] || [ "$package_count" -ne 1 ]; then
    echo "missing or duplicated active nginx route: $platform / $package_name" >&2
    exit 7
  fi
done

printf 'REMOTE_UPDATE_ROUTES_OK target=%s\n' "$SSH_TARGET"
