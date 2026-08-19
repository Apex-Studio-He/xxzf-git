#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ROUTE_SOURCE="$PROJECT_DIR/nginx/xxzf_public_routes.inc"
CHECK_ONLY=0
if [ "${1:-}" = "--check" ]; then
  CHECK_ONLY=1
  shift
fi
SSH_TARGET="${1:-}"
REMOTE_TEMP="/tmp/xxzf_public_routes.inc.$$.candidate"

if [ "$CHECK_ONLY" -ne 1 ] && [ -z "$SSH_TARGET" ]; then
  echo "Usage: install_public_nginx_route.sh [--check] SSH_TARGET" >&2
  exit 2
fi

validate_routes() {
  local path="$1"
  local selector count
  for selector in \
    "    location = /xxzf/notify {" \
    "    location = /xxzf/pair/start {" \
    "    location = /xxzf/pair/claim {" \
    "    location = /xxzf/v1/events {" \
    "    location = /xxzf/v1/device/revoke {" \
    "    location = /xxzf/v1/receiver/senders/revoke {" \
    "    location = /xxzf/v1/health {" \
    "    location = /downloads/forwarder/test/android.json {" \
    "    location ^~ /xxzf/ {"; do
    count="$(/usr/bin/grep -Fxc "$selector" "$path" || true)"
    if [ "$count" -ne 1 ]; then
      echo "Route-set validation failed for: $selector" >&2
      return 1
    fi
  done
  if /usr/bin/grep -Eq \
    'proxy_add_x_forwarded_for|zundu/auth/check|XXZF notify bridge public ingress (start|end)' \
    "$path"; then
    echo "Route-set contains a forbidden legacy coupling or proxy chain" >&2
    return 1
  fi
}

if [ ! -f "$ROUTE_SOURCE" ] || [ -L "$ROUTE_SOURCE" ]; then
  echo "Authoritative route file is missing or unsafe: $ROUTE_SOURCE" >&2
  exit 1
fi
validate_routes "$ROUTE_SOURCE"
LOCAL_SHA="$(/usr/bin/shasum -a 256 "$ROUTE_SOURCE" | /usr/bin/cut -d' ' -f1)"
if [ "$CHECK_ONLY" -eq 1 ]; then
  printf 'route-set valid; sha256=%s\n' "$LOCAL_SHA"
  exit 0
fi

/usr/bin/scp -q "$ROUTE_SOURCE" "$SSH_TARGET:$REMOTE_TEMP"

/usr/bin/ssh "$SSH_TARGET" bash -s -- "$REMOTE_TEMP" "$LOCAL_SHA" <<'REMOTE'
set -euo pipefail

REMOTE_TEMP="$1"
EXPECTED_SHA="$2"
ROUTES="/usr/local/etc/nginx/xxzf_public_routes.inc"
MAIN="/usr/local/etc/nginx/nginx.conf"
NGINX="/usr/local/bin/nginx"
STAMP="$(/bin/date +%Y%m%d-%H%M%S)"
BACKUP_DIR="/usr/local/etc/nginx/backups/${STAMP}-xxzf-route-authority"
STAGED="/usr/local/etc/nginx/.xxzf_public_routes.inc.$$.new"
HAD_ROUTE=0
COMMITTED=0
ACTIVE=0
MUTATED=0

cleanup() {
  /bin/rm -f "$REMOTE_TEMP" "$STAGED"
}

restore_route() {
  if [ "$HAD_ROUTE" -eq 1 ]; then
    /bin/cp -p "$BACKUP_DIR/xxzf_public_routes.inc" "$ROUTES"
  else
    /bin/rm -f "$ROUTES"
  fi
  if [ "$ACTIVE" -eq 1 ]; then
    "$NGINX" -t -c "$MAIN"
    "$NGINX" -s reload -c "$MAIN"
  fi
}

on_exit() {
  status=$?
  if [ "$status" -ne 0 ] && [ "$COMMITTED" -eq 0 ] && [ "$MUTATED" -eq 1 ]; then
    restore_route || true
  fi
  cleanup
  exit "$status"
}
trap on_exit EXIT

ACTUAL_SHA="$(/usr/bin/shasum -a 256 "$REMOTE_TEMP" | /usr/bin/cut -d' ' -f1)"
if [ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]; then
  echo "Transferred route file hash mismatch" >&2
  exit 2
fi

for selector in \
  "    location = /xxzf/notify {" \
  "    location = /xxzf/pair/start {" \
  "    location = /xxzf/pair/claim {" \
  "    location = /xxzf/v1/events {" \
  "    location = /xxzf/v1/device/revoke {" \
  "    location = /xxzf/v1/receiver/senders/revoke {" \
  "    location = /xxzf/v1/health {" \
  "    location = /downloads/forwarder/test/android.json {" \
  "    location ^~ /xxzf/ {"; do
  count="$(/usr/bin/grep -Fxc "$selector" "$REMOTE_TEMP" || true)"
  if [ "$count" -ne 1 ]; then
    echo "Remote route-set validation failed" >&2
    exit 3
  fi
done
if /usr/bin/grep -Eq \
  'proxy_add_x_forwarded_for|zundu/auth/check|XXZF notify bridge public ingress (start|end)' \
  "$REMOTE_TEMP"; then
  echo "Remote route-set contains a forbidden legacy coupling" >&2
  exit 4
fi

/bin/mkdir -p "$BACKUP_DIR"
/bin/chmod 700 "$BACKUP_DIR"
if [ -f "$ROUTES" ]; then
  HAD_ROUTE=1
  /bin/cp -p "$ROUTES" "$BACKUP_DIR/xxzf_public_routes.inc"
else
  /usr/bin/touch "$BACKUP_DIR/route-was-absent"
  /bin/chmod 600 "$BACKUP_DIR/route-was-absent"
fi

/bin/cp "$REMOTE_TEMP" "$STAGED"
/bin/chmod 644 "$STAGED"
/bin/mv "$STAGED" "$ROUTES"
MUTATED=1

if "$NGINX" -T -c "$MAIN" 2>&1 | /usr/bin/grep -Fq \
  '# configuration file /usr/local/etc/nginx/xxzf_public_routes.inc:'; then
  ACTIVE=1
  "$NGINX" -t -c "$MAIN"
  "$NGINX" -s reload -c "$MAIN"
  "$NGINX" -t -c "$MAIN"
fi

COMMITTED=1
trap - EXIT
cleanup
printf 'XXZF route %s; backup=%s; sha256=%s\n' \
  "$([ "$ACTIVE" -eq 1 ] && printf installed || printf staged)" \
  "$BACKUP_DIR" "$EXPECTED_SHA"
REMOTE
