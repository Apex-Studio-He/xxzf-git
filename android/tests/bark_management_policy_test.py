#!/usr/bin/env python3
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src/com/zundu/notifybridge"


class BarkManagementPolicyTests(unittest.TestCase):
    def test_private_activity_and_paired_sender_entry(self):
        manifest = (ROOT / "AndroidManifest.xml").read_text(encoding="utf-8")
        pair = (SRC / "PairActivity.java").read_text(encoding="utf-8")
        main = (SRC / "MainActivity.java").read_text(encoding="utf-8")
        block = re.search(
            r'<activity\s+android:name="\.BarkDestinationActivity"([\s\S]*?)/>',
            manifest,
        )
        self.assertIsNotNone(block)
        self.assertIn('android:exported="false"', block.group(0))
        self.assertIn('"管理 iPhone（Bark）"', pair)
        self.assertIn("new Intent(PairActivity.this, BarkDestinationActivity.class)", pair)
        self.assertLess(pair.index("if (Prefs.paired(this))"), pair.index('"管理 iPhone（Bark）"'))
        self.assertIn('settingRow("iPhone（Bark）")', main)
        self.assertIn('Ui.button(this, "连接 / 管理", true)', main)
        self.assertIn("MainActivity.this, BarkDestinationActivity.class", main)
        self.assertIn("只显示来源应用和通知标题，不发送正文", main)
        self.assertNotRegex(main, r"ANCS|Ancs|蓝牙配对 iPhone")

    def test_complete_bounded_self_service_flow(self):
        source = (SRC / "BarkDestinationActivity.java").read_text(encoding="utf-8")
        client = (SRC / "PairingClient.java").read_text(encoding="utf-8")
        self.assertIn("PairingClient.startBarkEnrollment", source)
        self.assertIn('optString("qrPng"', source)
        self.assertRegex(source, r'code\.matches\("\[0-9\]\{6\}"\)')
        self.assertIn("POLL_WINDOW_MS = 5 * 60 * 1000", source)
        self.assertIn("handler.removeCallbacks(enrollmentPoll)", source)
        self.assertIn("PairingClient.destinations", source)
        self.assertIn("PairingClient.testBark", source)
        self.assertIn("PairingClient.revokeBark", source)
        self.assertIn('setTitle("移除这台 iPhone？")', source)
        self.assertIn('setPositiveButton("移除此设备"', source)
        self.assertIn('"/v1/bark/enroll/start"', client)
        self.assertIn('"/v1/bark/test"', client)
        self.assertIn('"/v1/bark/revoke"', client)

    def test_bark_key_and_enrollment_link_are_never_displayed_or_saved(self):
        source = (SRC / "BarkDestinationActivity.java").read_text(encoding="utf-8")
        self.assertNotIn('optString("barkKey"', source)
        self.assertNotIn('optString("bindUrl"', source)
        self.assertNotIn("SharedPreferences", source)
        self.assertNotIn("Clipboard", source)
        self.assertNotRegex(source, r"(?:Log\.|System\.(?:out|err))")
        self.assertIn('value.optString("type", "")', source)
        self.assertIn('if (!"bark".equals(type)) return null;',
                      (SRC / "BarkDestination.java").read_text(encoding="utf-8"))

    def test_qr_decode_is_size_and_format_bounded(self):
        source = (SRC / "BarkDestinationActivity.java").read_text(encoding="utf-8")
        self.assertIn("MAX_QR_BASE64_LENGTH", source)
        self.assertIn("MAX_QR_BYTES", source)
        self.assertIn("data[0] == (byte) 0x89", source)
        self.assertIn("bitmap.getWidth() > 2048", source)
        self.assertIn('setContentDescription("iPhone Bark 绑定二维码")', source)


if __name__ == "__main__":
    unittest.main()
