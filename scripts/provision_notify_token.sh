#!/usr/bin/env zsh
set -euo pipefail
umask 077

target="${1:-${XXZF_TOKEN_FILE:-$HOME/Library/Application Support/XXZF/server-data/notify-token.txt}}"
directory="$(dirname "$target")"

mkdir -p "$directory"
chmod 700 "$directory"

if [[ -f "$target" ]]; then
  if [[ -L "$target" ]]; then
    echo "Refusing a symbolic-link token file." >&2
    exit 1
  fi
  chmod 600 "$target"
  /usr/bin/python3 - "$target" <<'PY'
import re
import sys
from pathlib import Path

value = Path(sys.argv[1]).read_text("utf-8").strip()
is_hex = bool(re.fullmatch(r"[A-Fa-f0-9]{48,128}", value))
is_urlsafe = bool(re.fullmatch(r"[A-Za-z0-9_-]{32,256}", value))
required = 10 if is_hex else 16
if not (is_hex or is_urlsafe) or len(set(value)) < required:
    raise SystemExit("Existing legacy notify token is weak; rotate it during a controlled client migration.")
PY
  echo "Legacy notify token is already provisioned."
  exit 0
fi

temporary="$(mktemp "${target}.tmp.XXXXXX")"
trap 'rm -f "$temporary"' EXIT
/usr/bin/openssl rand -hex 32 > "$temporary"
chmod 600 "$temporary"
mv "$temporary" "$target"
trap - EXIT

echo "Legacy notify token provisioned."
