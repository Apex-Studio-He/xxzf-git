#!/usr/bin/env python3
import tempfile
import unittest
from pathlib import Path

from diagnostic_store import DiagnosticStore


class DiagnosticStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name) / "诊断日志"

    def tearDown(self):
        self.temporary.cleanup()

    def test_record_keeps_allowlisted_operational_data_only(self):
        store = DiagnosticStore(self.directory, max_bytes=1024 * 1024)
        result = store.record(
            {
                "appVersion": "0.8",
                "networkStatus": "online",
                "serverStatus": "unreachable",
                "paired": True,
                "listenerEnabled": True,
                "notificationBody": "绝不能保存的通知正文",
                "secret": "绝不能保存的设备密钥",
                "entries": [
                    {
                        "at": 123456789,
                        "level": "error",
                        "code": "SERVER_UNREACHABLE",
                        "httpStatus": 503,
                        "detail": "绝不能保存的自由文本",
                    },
                    {"at": 123456790, "level": "info", "code": "STREAM_CONNECTED"},
                ],
            },
            device={
                "device_id": "r_1",
                "name": "客户电脑",
                "platform": "windows",
                "role": "receiver",
                "fingerprint": "ABC1234567",
            },
        )

        self.assertRegex(result["diagnosticId"], r"^D-[A-F0-9]{12}$")
        records = store.query()
        self.assertEqual(1, len(records))
        self.assertEqual("客户电脑", records[0]["device_name"])
        self.assertEqual("SERVER_UNREACHABLE", records[0]["entries"][0]["code"])
        self.assertEqual(503, records[0]["entries"][0]["httpStatus"])
        raw = store.database_path.read_bytes()
        self.assertNotIn("绝不能保存的通知正文".encode("utf-8"), raw)
        self.assertNotIn("绝不能保存的设备密钥".encode("utf-8"), raw)
        self.assertNotIn("绝不能保存的自由文本".encode("utf-8"), raw)

    def test_entries_and_fields_are_bounded(self):
        store = DiagnosticStore(self.directory, max_bytes=1024 * 1024)
        payload = {
            "appVersion": "v" * 1000,
            "entries": [
                {"at": index, "level": "invalid", "code": "X" * 200, "httpStatus": 9999}
                for index in range(300)
            ],
        }
        store.record(payload, device={"device_id": "s_1", "name": "手机", "platform": "android", "role": "sender"})
        record = store.query()[0]
        self.assertLessEqual(len(record["app_version"]), 32)
        self.assertEqual(100, len(record["entries"]))
        self.assertEqual("info", record["entries"][0]["level"])
        self.assertLessEqual(len(record["entries"][0]["code"]), 48)
        self.assertEqual(999, record["entries"][0]["httpStatus"])


if __name__ == "__main__":
    unittest.main()
