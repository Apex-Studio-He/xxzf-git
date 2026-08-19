#!/bin/zsh
set -eu
umask 077

source_dir="${XXZF_SOURCE_DIR:-$HOME/Library/Application Support/XXZF/server-data}"
backup_dir="${XXZF_BACKUP_DIR:-$HOME/Library/Application Support/XXZF/backups/server-data}"
database="$source_dir/devices.sqlite3"

[[ -f "$database" ]] || exit 0
mkdir -p -m 700 "$backup_dir"
chmod 700 "$backup_dir"
if [[ "$(stat -f '%Lp' "$backup_dir")" != "700" ]]; then
  echo "Backup directory does not enforce private permissions; use internal APFS or an encrypted APFS volume." >&2
  exit 1
fi

stamp=$(date +%Y%m%d-%H%M%S)
temporary="$backup_dir/devices-$stamp.sqlite3.tmp"
destination="$backup_dir/devices-$stamp.sqlite3"
/usr/bin/sqlite3 "$database" ".backup '$temporary'"
chmod 600 "$temporary"
/bin/mv "$temporary" "$destination"
chmod 600 "$destination"

backups=("$backup_dir"/devices-*.sqlite3(N.Om))
if (( ${#backups[@]} > 72 )); then
  /bin/rm -f -- "${backups[@]:72}"
fi
