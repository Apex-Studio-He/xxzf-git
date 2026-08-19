import os
import subprocess
import unittest
from unittest import mock

import mac_client


class NotifierAppPathTests(unittest.TestCase):
    def test_explicit_agent_path_wins(self):
        result = mac_client.resolve_notifier_app(
            {"XXZF_NOTIFIER_APP": "/custom/转发.app"},
            "/Users/tester",
            lambda _path: False,
        )
        self.assertEqual(result, "/custom/转发.app")

    def test_system_install_wins_over_stale_user_copy(self):
        executable = "/Applications/转发.app/Contents/MacOS/转发"
        result = mac_client.resolve_notifier_app(
            {},
            "/Users/tester",
            lambda path: path == executable,
        )
        self.assertEqual(result, "/Applications/转发.app")

    def test_user_install_is_used_when_it_is_the_only_install(self):
        executable = "/Users/tester/Applications/转发.app/Contents/MacOS/转发"
        result = mac_client.resolve_notifier_app(
            {},
            "/Users/tester",
            lambda path: path == executable,
        )
        self.assertEqual(result, "/Users/tester/Applications/转发.app")


class NotificationDeliveryTests(unittest.TestCase):
    @mock.patch.object(mac_client.os.path, "isfile", return_value=True)
    @mock.patch.object(mac_client.subprocess, "run")
    def test_native_failure_uses_osascript_fallback(self, run, _isfile):
        run.side_effect = [
            subprocess.CompletedProcess(["native"], 1, stderr="native failed"),
            subprocess.CompletedProcess(["osascript"], 0, stderr=""),
        ]
        with mock.patch("builtins.print"):
            delivered = mac_client.notify("Android", "转发：测试", "正文")
        self.assertTrue(delivered)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[1].args[0][0], "/usr/bin/osascript")

    @mock.patch.object(mac_client.os.path, "isfile", return_value=True)
    @mock.patch.object(mac_client.subprocess, "run")
    def test_both_notification_senders_failing_returns_false(self, run, _isfile):
        run.side_effect = [
            subprocess.CompletedProcess(["native"], 1, stderr="native failed"),
            subprocess.CompletedProcess(["osascript"], 1, stderr="fallback failed"),
        ]
        with mock.patch("builtins.print"):
            delivered = mac_client.notify("Android", "转发：测试", "正文")
        self.assertFalse(delivered)
        self.assertEqual(run.call_count, 2)

    def test_handle_event_records_delivery_failure(self):
        event = {
            "appName": "测试",
            "title": "标题",
            "text": "正文",
            "privacyMode": "full",
        }
        with mock.patch.object(mac_client, "notify", return_value=False), \
                mock.patch.object(mac_client, "diagnostic_log") as diagnostic, \
                mock.patch("builtins.print"):
            delivered = mac_client.handle_event(event)
        self.assertFalse(delivered)
        diagnostic.assert_called_once_with("error", "NOTIFICATION_FAILED")

    def test_handle_event_records_delivery_success(self):
        event = {
            "appName": "测试",
            "title": "标题",
            "text": "正文",
            "privacyMode": "full",
        }
        with mock.patch.object(mac_client, "notify", return_value=True), \
                mock.patch.object(mac_client, "diagnostic_log") as diagnostic, \
                mock.patch("builtins.print"):
            delivered = mac_client.handle_event(event)
        self.assertTrue(delivered)
        diagnostic.assert_called_once_with("info", "NOTIFICATION_DELIVERED")


if __name__ == "__main__":
    unittest.main()
