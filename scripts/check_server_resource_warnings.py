#!/usr/bin/env python3
"""Run the server suite and fail if Python reports an unclosed resource."""

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = ROOT / "server"


def main():
    environment = os.environ.copy()
    environment["PYTHONTRACEMALLOC"] = "5"
    command = [
        sys.executable,
        "-W",
        "always::ResourceWarning",
        "-m",
        "unittest",
        "discover",
        "-s",
        str(SERVER_DIR),
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode:
        return result.returncode
    if "ResourceWarning:" in result.stdout or "ResourceWarning:" in result.stderr:
        print("server test suite emitted ResourceWarning", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
