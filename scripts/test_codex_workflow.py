#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path

from codex_request import RequestError, load_request


VALID = {
    "public_base": "https://notify.opensource.org/xxzf",
    "update_base": "https://downloads.opensource.org/downloads/forwarder/test",
    "targets": ["server", "android"],
    "build_mode": "debug",
    "server_platform": "linux",
}


class RequestValidationTests(unittest.TestCase):
    def load(self, payload):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "request.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return load_request(path)

    def test_accepts_public_only_request(self):
        request = self.load(VALID)
        self.assertEqual("notify.opensource.org", request.public_host)
        self.assertEqual(("server", "android"), request.targets)

    def test_rejects_placeholder(self):
        payload = dict(VALID, public_base="https://notify.example.com/xxzf")
        with self.assertRaisesRegex(RequestError, "placeholder"):
            self.load(payload)

    def test_rejects_password_in_url(self):
        payload = dict(VALID, public_base="https://user:secret@notify.opensource.org/xxzf")
        with self.assertRaisesRegex(RequestError, "username or password"):
            self.load(payload)

    def test_rejects_wrong_paths_and_non_https(self):
        for value in (
            "http://notify.opensource.org/xxzf",
            "https://notify.opensource.org/",
            "https://notify.opensource.org/xxzf?token=secret",
        ):
            with self.subTest(value=value), self.assertRaises(RequestError):
                self.load(dict(VALID, public_base=value))

    def test_rejects_unknown_and_duplicate_targets(self):
        with self.assertRaisesRegex(RequestError, "unsupported"):
            self.load(dict(VALID, targets=["ios"]))
        with self.assertRaisesRegex(RequestError, "duplicate"):
            self.load(dict(VALID, targets=["server", "server"]))

    def test_rejects_unknown_fields_to_catch_typos(self):
        payload = dict(VALID)
        payload["server_password"] = "must-not-be-here"
        with self.assertRaisesRegex(RequestError, "unknown"):
            self.load(payload)


if __name__ == "__main__":
    unittest.main()
