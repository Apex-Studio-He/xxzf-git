#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PUBLISHER="$ROOT/scripts/publish_test_update.py"
VERIFIER="$ROOT/scripts/verify_published_update.py"
REMOTE_INSTALLER_SOURCE="$ROOT/scripts/install_test_update_set_remote.sh"
REMOTE_ROUTE_CHECKER="$ROOT/scripts/verify_remote_update_routes.sh"
ROUTES_SOURCE="$ROOT/nginx/xxzf_public_routes.inc"
SSH_TARGET="${XXZF_UPDATE_SSH_TARGET:-}"
REMOTE_ROOT="${XXZF_UPDATE_REMOTE_ROOT:-/opt/xxzf/public/downloads/forwarder/test}"

usage() {
  cat >&2 <<'EOF'
Usage: deploy_test_updates.sh [--preflight-only] [--notes TEXT] PLATFORM...

Provide any non-empty subset of complete platform groups:
  --android APK --android-version VERSION --android-code CODE
  --macos DMG --macos-version VERSION --macos-code CODE
  --windows EXE --windows-version VERSION --windows-code CODE
EOF
  exit 2
}

ANDROID_PACKAGE=""
ANDROID_VERSION=""
ANDROID_CODE=""
MACOS_PACKAGE=""
MACOS_VERSION=""
MACOS_CODE=""
WINDOWS_PACKAGE=""
WINDOWS_VERSION=""
WINDOWS_CODE=""
NOTES="安全性与稳定性更新"
PREFLIGHT_ONLY=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --preflight-only) PREFLIGHT_ONLY=1; shift ;;
    --android) ANDROID_PACKAGE="${2:-}"; shift 2 ;;
    --android-version) ANDROID_VERSION="${2:-}"; shift 2 ;;
    --android-code) ANDROID_CODE="${2:-}"; shift 2 ;;
    --macos) MACOS_PACKAGE="${2:-}"; shift 2 ;;
    --macos-version) MACOS_VERSION="${2:-}"; shift 2 ;;
    --macos-code) MACOS_CODE="${2:-}"; shift 2 ;;
    --windows) WINDOWS_PACKAGE="${2:-}"; shift 2 ;;
    --windows-version) WINDOWS_VERSION="${2:-}"; shift 2 ;;
    --windows-code) WINDOWS_CODE="${2:-}"; shift 2 ;;
    --notes) NOTES="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done

if [ ! -f "$ROUTES_SOURCE" ] || [ -L "$ROUTES_SOURCE" ]; then
  echo "Authoritative nginx route set is missing or unsafe" >&2
  exit 3
fi
if [ ! -f "$VERIFIER" ] || [ -L "$VERIFIER" ]; then
  echo "Published-update verifier is missing or unsafe" >&2
  exit 4
fi
if [ ! -f "$REMOTE_INSTALLER_SOURCE" ] || [ -L "$REMOTE_INSTALLER_SOURCE" ]; then
  echo "Remote update installer is missing or unsafe" >&2
  exit 5
fi
if [ ! -x "$REMOTE_ROUTE_CHECKER" ] || [ -L "$REMOTE_ROUTE_CHECKER" ]; then
  echo "Remote nginx route checker is missing or unsafe" >&2
  exit 5
fi

SELECTED_PLATFORMS=()
SELECTED_PACKAGE_NAMES=()

require_exact_route() {
  platform="$1"
  package_name="$2"
  manifest_selector="    location = /downloads/forwarder/test/$platform.json {"
  package_selector="    location = /downloads/forwarder/test/$package_name {"
  manifest_count="$(/usr/bin/grep -Fxc "$manifest_selector" "$ROUTES_SOURCE" || true)"
  package_count="$(/usr/bin/grep -Fxc "$package_selector" "$ROUTES_SOURCE" || true)"
  if [ "$manifest_count" -ne 1 ] || [ "$package_count" -ne 1 ]; then
    echo "Missing exact nginx route for $platform update: $package_name" >&2
    return 1
  fi
}

select_platform() {
  platform="$1"
  package="$2"
  version="$3"
  version_code="$4"
  extension="$5"
  supplied=0
  [ -n "$package" ] && supplied=$((supplied + 1))
  [ -n "$version" ] && supplied=$((supplied + 1))
  [ -n "$version_code" ] && supplied=$((supplied + 1))
  if [ "$supplied" -eq 0 ]; then
    return
  fi
  [ "$supplied" -eq 3 ] || usage
  [ -f "$package" ] && [ ! -L "$package" ] || {
    echo "Package is missing or unsafe for $platform" >&2
    exit 6
  }
  if ! [[ "$version" =~ ^[0-9]+(\.[0-9]+){1,3}(-[A-Za-z0-9.]+)?$ ]]; then
    echo "Invalid client-compatible version for $platform: $version" >&2
    exit 7
  fi
  case "$version_code" in
    ''|*[!0-9]*) echo "Invalid version code for $platform" >&2; exit 8 ;;
  esac
  /usr/bin/python3 - "$version_code" <<'PY' || {
import sys
value = int(sys.argv[1])
raise SystemExit(0 if 0 < value <= (1 << 63) - 1 else 1)
PY
    echo "Invalid version code for $platform" >&2
    exit 8
  }
  package_name="forwarder-$platform-$version-test.$extension"
  require_exact_route "$platform" "$package_name"
  SELECTED_PLATFORMS+=("$platform")
  SELECTED_PACKAGE_NAMES+=("$package_name")
}

select_platform android "$ANDROID_PACKAGE" "$ANDROID_VERSION" "$ANDROID_CODE" apk
select_platform macos "$MACOS_PACKAGE" "$MACOS_VERSION" "$MACOS_CODE" dmg
select_platform windows "$WINDOWS_PACKAGE" "$WINDOWS_VERSION" "$WINDOWS_CODE" exe
[ "${#SELECTED_PLATFORMS[@]}" -gt 0 ] || usage

if [ "$PREFLIGHT_ONLY" -eq 1 ]; then
  printf 'UPDATE_PREFLIGHT_OK platforms=%s\n' "${SELECTED_PLATFORMS[*]}"
  exit 0
fi

if [ -z "$SSH_TARGET" ]; then
  echo "Set XXZF_UPDATE_SSH_TARGET before deploying updates" >&2
  exit 11
fi

STAGING="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/xxzf-updates.XXXXXX")"
ARCHIVE="$STAGING.tar.gz"
REMOTE_ARCHIVE="/tmp/xxzf-updates.$$.tar.gz"
REMOTE_VERIFIER="/tmp/verify_published_update.$$.py"
REMOTE_INSTALLER="/tmp/install_test_update_set_remote.$$.sh"
REMOTE_UPLOAD_STARTED=0
cleanup() {
  /bin/rm -rf "$STAGING" "$ARCHIVE"
  if [ "$REMOTE_UPLOAD_STARTED" -eq 1 ]; then
    /usr/bin/ssh -o BatchMode=yes "$SSH_TARGET" /bin/rm -f \
      "$REMOTE_ARCHIVE" "$REMOTE_VERIFIER" "$REMOTE_INSTALLER" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
/bin/chmod 700 "$STAGING"

publish() {
  platform="$1"
  version="$2"
  version_code="$3"
  package="$4"
  command=(
    "$PUBLISHER" --platform "$platform" --version "$version"
    --version-code "$version_code" --package "$package" --notes "$NOTES"
    --output-root "$STAGING"
  )
  if [ -n "${XXZF_UPDATE_PRIVATE_KEY:-}" ]; then
    command+=(--private-key "$XXZF_UPDATE_PRIVATE_KEY")
  fi
  "${command[@]}"
  /usr/bin/python3 "$VERIFIER" "$STAGING/$platform.json" --package-root "$STAGING" >/dev/null
}

[ -z "$ANDROID_PACKAGE" ] || publish android "$ANDROID_VERSION" "$ANDROID_CODE" "$ANDROID_PACKAGE"
[ -z "$MACOS_PACKAGE" ] || publish macos "$MACOS_VERSION" "$MACOS_CODE" "$MACOS_PACKAGE"
[ -z "$WINDOWS_PACKAGE" ] || publish windows "$WINDOWS_VERSION" "$WINDOWS_CODE" "$WINDOWS_PACKAGE"

EXPECTED_FILES=$((2 * ${#SELECTED_PLATFORMS[@]}))
ACTUAL_FILES="$(find "$STAGING" -mindepth 1 -maxdepth 1 -type f | wc -l | tr -d ' ')"
[ "$ACTUAL_FILES" = "$EXPECTED_FILES" ] || {
  echo "Published update set file count mismatch" >&2
  exit 9
}
if [ -n "$(find "$STAGING" -mindepth 1 ! -type f -print)" ]; then
  echo "Published update set contains a symlink, directory, or special file" >&2
  exit 10
fi

REMOTE_ROUTE_ARGS=()
for index in "${!SELECTED_PLATFORMS[@]}"; do
  REMOTE_ROUTE_ARGS+=("${SELECTED_PLATFORMS[$index]}")
  REMOTE_ROUTE_ARGS+=("${SELECTED_PACKAGE_NAMES[$index]}")
done
"$REMOTE_ROUTE_CHECKER" /usr/bin/ssh "$SSH_TARGET" "${REMOTE_ROUTE_ARGS[@]}"

ARCHIVE_FILES=()
for index in "${!SELECTED_PLATFORMS[@]}"; do
  ARCHIVE_FILES+=("${SELECTED_PLATFORMS[$index]}.json")
  ARCHIVE_FILES+=("${SELECTED_PACKAGE_NAMES[$index]}")
done
/usr/bin/env COPYFILE_DISABLE=1 \
  /usr/bin/tar -C "$STAGING" -czf "$ARCHIVE" "${ARCHIVE_FILES[@]}"
LOCAL_SHA="$(/usr/bin/shasum -a 256 "$ARCHIVE" | /usr/bin/cut -d' ' -f1)"
VERIFIER_SHA="$(/usr/bin/shasum -a 256 "$VERIFIER" | /usr/bin/cut -d' ' -f1)"
INSTALLER_SHA="$(/usr/bin/shasum -a 256 "$REMOTE_INSTALLER_SOURCE" | /usr/bin/cut -d' ' -f1)"

/usr/bin/scp -q "$ARCHIVE" "$SSH_TARGET:$REMOTE_ARCHIVE"
REMOTE_UPLOAD_STARTED=1
/usr/bin/scp -q "$VERIFIER" "$SSH_TARGET:$REMOTE_VERIFIER"
/usr/bin/scp -q "$REMOTE_INSTALLER_SOURCE" "$SSH_TARGET:$REMOTE_INSTALLER"
/usr/bin/ssh -o BatchMode=yes "$SSH_TARGET" /bin/bash -s -- \
  "$REMOTE_INSTALLER" "$INSTALLER_SHA" "$REMOTE_ARCHIVE" "$LOCAL_SHA" \
  "$REMOTE_ROOT" "$REMOTE_VERIFIER" "$VERIFIER_SHA" \
  "${SELECTED_PLATFORMS[@]}" <<'REMOTE'
set -euo pipefail
INSTALLER="$1"
EXPECTED_INSTALLER_SHA="$2"
shift 2
cleanup_installer() { /bin/rm -f "$INSTALLER"; }
trap cleanup_installer EXIT
[ -f "$INSTALLER" ] && [ ! -L "$INSTALLER" ] || exit 50
[ "$(/usr/bin/shasum -a 256 "$INSTALLER" | /usr/bin/cut -d' ' -f1)" = "$EXPECTED_INSTALLER_SHA" ] || exit 51
/usr/bin/env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin \
  /bin/bash "$INSTALLER" "$@"
REMOTE

REMOTE_UPLOAD_STARTED=0
trap - EXIT
/bin/rm -rf "$STAGING" "$ARCHIVE"
printf 'TEST_UPDATES_DEPLOYED target=%s platforms=%s sha256=%s installer_sha256=%s\n' \
  "$SSH_TARGET" "${SELECTED_PLATFORMS[*]}" "$LOCAL_SHA" "$INSTALLER_SHA"
