#!/usr/bin/env python3
import base64
import io
import sys
from pathlib import Path


VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

import segno  # noqa: E402


def png_base64(payload):
    output = io.BytesIO()
    segno.make_qr(str(payload), error="m").save(
        output,
        kind="png",
        scale=6,
        border=2,
        dark="#111827",
        light="#ffffff",
    )
    return base64.b64encode(output.getvalue()).decode("ascii")
