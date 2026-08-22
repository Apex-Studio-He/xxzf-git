#!/usr/bin/env python3
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/com/zundu/notifybridge/NotifyBridgeService.java"


class NotificationServiceHeartbeatPolicyTests(unittest.TestCase):
    def test_notification_listener_keeps_server_presence_fresh(self):
        source = SOURCE.read_text("utf-8")
        self.assertIn("HEARTBEAT_INTERVAL_MS = 60 * 1000L", source)
        self.assertIn("ServerClient.check(NotifyBridgeService.this", source)
        self.assertIn("updateHandler.post(heartbeat)", source)
        self.assertIn("updateHandler.removeCallbacks(heartbeat)", source)


if __name__ == "__main__":
    unittest.main()
