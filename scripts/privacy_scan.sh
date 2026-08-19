#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
/usr/bin/python3 "$ROOT/scripts/privacy_scan.py"

if command -v gitleaks >/dev/null 2>&1 && [ -d "$ROOT/.git" ]; then
  gitleaks git --no-banner --redact "$ROOT"
else
  echo "GITLEAKS_SKIPPED install gitleaks for full-history scanning" >&2
fi
