#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 6 ]; then
  echo "Usage: install_test_update_set_remote.sh ARCHIVE ARCHIVE_SHA ROOT VERIFIER VERIFIER_SHA PLATFORM..." >&2
  exit 2
fi

ARCHIVE="$1"
EXPECTED_ARCHIVE_SHA="$2"
REMOTE_ROOT="$3"
VERIFIER="$4"
EXPECTED_VERIFIER_SHA="$5"
shift 5
PLATFORMS=("$@")

PARENT="$(/usr/bin/dirname "$REMOTE_ROOT")"
INCOMING="$PARENT/.test-incoming.$$"
COMMITTED=0
ATOMIC_MOVE_COUNT=0
COMMITTED_MANIFEST_COUNT=0
NEW_PACKAGES=()
PACKAGE_STAGED=()
PACKAGE_NAMES=()
MANIFEST_STAGED=()
MANIFEST_TARGETS=()
MANIFEST_BACKUPS=()
MANIFEST_HAD_OLD=()

if [ "${XXZF_UPDATE_TEST_MODE:-0}" = "1" ]; then
  SAFE_TEST_ROOT="${TMPDIR:-/tmp}"
  case "$REMOTE_ROOT" in
    "$SAFE_TEST_ROOT"*) ;;
    *) echo "test hooks require a temporary root" >&2; exit 15 ;;
  esac
elif [ -n "${XXZF_UPDATE_TEST_FAIL_MOVE:-}" ]; then
  echo "move failure hook is disabled outside test mode" >&2
  exit 16
fi

atomic_move() {
  ATOMIC_MOVE_COUNT=$((ATOMIC_MOVE_COUNT + 1))
  if [ "${XXZF_UPDATE_TEST_MODE:-0}" = "1" ] \
      && [ "${XXZF_UPDATE_TEST_FAIL_MOVE:-0}" = "$ATOMIC_MOVE_COUNT" ]; then
    printf 'INJECTED_SWAP_FAILURE move=%s\n' "$ATOMIC_MOVE_COUNT" >&2
    return 97
  fi
  /bin/mv "$1" "$2"
}

rollback_manifests() {
  while [ "$COMMITTED_MANIFEST_COUNT" -gt 0 ]; do
    index=$((COMMITTED_MANIFEST_COUNT - 1))
    if [ "${MANIFEST_HAD_OLD[$index]}" -eq 1 ]; then
      /bin/mv "${MANIFEST_BACKUPS[$index]}" "${MANIFEST_TARGETS[$index]}"
    else
      /bin/rm -f "${MANIFEST_TARGETS[$index]}"
    fi
    COMMITTED_MANIFEST_COUNT="$index"
  done
}

cleanup() {
  status=$?
  trap - EXIT
  set +u
  if [ "$status" -ne 0 ] && [ "$COMMITTED" -eq 0 ]; then
    rollback_ok=1
    rollback_manifests || rollback_ok=0
    if [ "$rollback_ok" -eq 1 ]; then
      for package in "${NEW_PACKAGES[@]}"; do
        /bin/rm -f "$package"
      done
    fi
  fi
  for path in "${MANIFEST_STAGED[@]}" "${MANIFEST_BACKUPS[@]}"; do
    [ -z "$path" ] || /bin/rm -f "$path"
  done
  for path in "${PACKAGE_STAGED[@]}"; do
    [ -z "$path" ] || /bin/rm -f "$path"
  done
  /bin/rm -rf "$INCOMING"
  /bin/rm -f "$ARCHIVE" "$VERIFIER"
  exit "$status"
}
trap cleanup EXIT

[ -f "$ARCHIVE" ] && [ ! -L "$ARCHIVE" ] || exit 10
[ -f "$VERIFIER" ] && [ ! -L "$VERIFIER" ] || exit 11
[ "$(/usr/bin/shasum -a 256 "$ARCHIVE" | /usr/bin/cut -d' ' -f1)" = "$EXPECTED_ARCHIVE_SHA" ] || exit 12
[ "$(/usr/bin/shasum -a 256 "$VERIFIER" | /usr/bin/cut -d' ' -f1)" = "$EXPECTED_VERIFIER_SHA" ] || exit 13
[ -d "$PARENT" ] && [ ! -L "$PARENT" ] || exit 14
[ -d "$REMOTE_ROOT" ] && [ ! -L "$REMOTE_ROOT" ] || exit 23
if [ -n "$(find "$REMOTE_ROOT" -mindepth 1 ! -type f -print)" ]; then
  echo "existing update root contains a symlink, directory, or special file" >&2
  exit 24
fi

SEEN_PLATFORMS=""
for platform in "${PLATFORMS[@]}"; do
  case "$platform" in
    android|macos|windows) ;;
    *) echo "unsupported update platform: $platform" >&2; exit 17 ;;
  esac
  case " $SEEN_PLATFORMS " in
    *" $platform "*) echo "duplicate update platform: $platform" >&2; exit 18 ;;
  esac
  SEEN_PLATFORMS="$SEEN_PLATFORMS $platform"
done
EXPECTED_FILES=$((2 * ${#PLATFORMS[@]}))
[ "$EXPECTED_FILES" -gt 0 ] || exit 19

/bin/mkdir "$INCOMING"
/bin/chmod 700 "$INCOMING"
/usr/bin/python3 - "$ARCHIVE" "$INCOMING" "$EXPECTED_FILES" <<'PY'
import pathlib
import shutil
import sys
import tarfile

archive = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
expected_files = int(sys.argv[3])
with tarfile.open(archive, "r:gz") as bundle:
    members = bundle.getmembers()
    if len(members) != expected_files:
        raise SystemExit("update archive file count mismatch")
    names = set()
    for member in members:
        path = pathlib.PurePosixPath(member.name)
        if not member.isfile() or len(path.parts) != 1 or path.name in ("", ".", ".."):
            raise SystemExit("update archive contains an unsafe entry")
        if path.name in names:
            raise SystemExit("update archive contains duplicate names")
        names.add(path.name)
        source = bundle.extractfile(member)
        if source is None:
            raise SystemExit("update archive member is unreadable")
        with source, (destination / path.name).open("xb") as output:
            shutil.copyfileobj(source, output, 1024 * 1024)
PY

[ "$(find "$INCOMING" -mindepth 1 -maxdepth 1 -type f | wc -l | tr -d ' ')" = "$EXPECTED_FILES" ] || exit 20
if [ -n "$(find "$INCOMING" -mindepth 1 ! -type f -print)" ]; then exit 21; fi
for platform in "${PLATFORMS[@]}"; do
  manifest="$INCOMING/$platform.json"
  [ -f "$manifest" ] && [ ! -L "$manifest" ] || exit 22
  /usr/bin/python3 "$VERIFIER" "$manifest" --package-root "$INCOMING" >/dev/null
  package_name="$(/usr/bin/python3 - "$manifest" <<'PY'
import json
import pathlib
import sys
from urllib.parse import urlsplit

manifest = json.loads(pathlib.Path(sys.argv[1]).read_text("utf-8"))
print(pathlib.PurePosixPath(urlsplit(manifest["url"]).path).name)
PY
)"
  [ -n "$package_name" ] || exit 25
  PACKAGE_NAMES+=("$package_name")
done

# Immutable versioned artifacts are installed first. Reusing an immutable URL
# with different bytes is forbidden; identical bytes are safe to keep.
for index in "${!PLATFORMS[@]}"; do
  package_name="${PACKAGE_NAMES[$index]}"
  source_package="$INCOMING/$package_name"
  target_package="$REMOTE_ROOT/$package_name"
  if [ -e "$target_package" ] || [ -L "$target_package" ]; then
    [ -f "$target_package" ] && [ ! -L "$target_package" ] || exit 26
    source_sha="$(/usr/bin/shasum -a 256 "$source_package" | /usr/bin/cut -d' ' -f1)"
    target_sha="$(/usr/bin/shasum -a 256 "$target_package" | /usr/bin/cut -d' ' -f1)"
    if [ "$source_sha" != "$target_sha" ]; then
      echo "immutable package collision: $package_name" >&2
      exit 27
    fi
    continue
  fi
  staged_package="$REMOTE_ROOT/.$package_name.$$.new"
  PACKAGE_STAGED+=("$staged_package")
  /bin/cp "$source_package" "$staged_package"
  /bin/chmod 644 "$staged_package"
  [ "$(/usr/bin/shasum -a 256 "$staged_package" | /usr/bin/cut -d' ' -f1)" = \
    "$(/usr/bin/shasum -a 256 "$source_package" | /usr/bin/cut -d' ' -f1)" ] || exit 28
  if ! atomic_move "$staged_package" "$target_package"; then
    exit 29
  fi
  NEW_PACKAGES+=("$target_package")
done

# Stage and verify every manifest against the now-present immutable package.
# Manifests are renamed last and therefore act as the update commit points.
for index in "${!PLATFORMS[@]}"; do
  platform="${PLATFORMS[$index]}"
  source_manifest="$INCOMING/$platform.json"
  staged_manifest="$REMOTE_ROOT/.$platform.json.$$.new"
  target_manifest="$REMOTE_ROOT/$platform.json"
  backup_manifest="$REMOTE_ROOT/.$platform.json.$$.old"
  MANIFEST_STAGED+=("$staged_manifest")
  MANIFEST_TARGETS+=("$target_manifest")
  MANIFEST_BACKUPS+=("$backup_manifest")
  /bin/cp "$source_manifest" "$staged_manifest"
  /bin/chmod 644 "$staged_manifest"
  if [ -e "$target_manifest" ] || [ -L "$target_manifest" ]; then
    [ -f "$target_manifest" ] && [ ! -L "$target_manifest" ] || exit 30
    /bin/cp -p "$target_manifest" "$backup_manifest"
    MANIFEST_HAD_OLD+=(1)
  else
    MANIFEST_HAD_OLD+=(0)
  fi
  /usr/bin/python3 "$VERIFIER" "$staged_manifest" --package-root "$REMOTE_ROOT" >/dev/null
done

for index in "${!PLATFORMS[@]}"; do
  if atomic_move "${MANIFEST_STAGED[$index]}" "${MANIFEST_TARGETS[$index]}"; then
    COMMITTED_MANIFEST_COUNT=$((COMMITTED_MANIFEST_COUNT + 1))
  else
    exit 31
  fi
done
COMMITTED=1

for backup in "${MANIFEST_BACKUPS[@]}"; do
  /bin/rm -f "$backup"
done
/bin/chmod 755 "$REMOTE_ROOT"
printf 'UPDATE_SET_INSTALLED root=%s platforms=%s files=%s\n' \
  "$REMOTE_ROOT" "${PLATFORMS[*]}" \
  "$(find "$REMOTE_ROOT" -mindepth 1 -maxdepth 1 -type f | wc -l | tr -d ' ')"
