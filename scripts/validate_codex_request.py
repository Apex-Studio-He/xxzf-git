#!/usr/bin/env python3
"""Validate the public-only input used by the Codex build workflow."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from codex_request import RequestError, load_request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        request = load_request(args.request)
    except RequestError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"REQUEST_INVALID: {exc}")
        return 2
    if args.json:
        print(json.dumps({"ok": True, "request": asdict(request)}, ensure_ascii=False))
    else:
        print("REQUEST_OK")
        print(f"  targets: {', '.join(request.targets)}")
        print(f"  build mode: {request.build_mode}")
        print(f"  public base: {request.public_base}")
        print(f"  update base: {request.update_base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
