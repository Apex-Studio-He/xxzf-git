#!/usr/bin/env python3
import base64
import unittest

from qr_code import png_base64


class QrCodeTests(unittest.TestCase):
    def test_pairing_payload_produces_png(self):
        raw = base64.b64decode(png_base64("xxzf://pair?server=https%3A%2F%2Fexample&code=123456"))
        self.assertTrue(raw.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(raw), 300)
        self.assertLess(len(raw), 64 * 1024)


if __name__ == "__main__":
    unittest.main()
