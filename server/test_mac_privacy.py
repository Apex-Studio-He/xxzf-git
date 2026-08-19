import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parent))
import mac_client  # noqa: E402


class MacPrivacyTests(unittest.TestCase):
    EVENT = {
        "appName": "微信",
        "title": "何昊",
        "text": "晚上一起吃饭吗",
        "privacyMode": "full",
    }

    @mock.patch.object(mac_client, "notify")
    def test_receiver_source_mode_hides_title_and_body(self, notify):
        mac_client.handle_event(self.EVENT, content_mode="source")

        notify.assert_called_once_with("微信", "转发：微信", "")

    @mock.patch.object(mac_client, "notify")
    def test_receiver_title_mode_hides_body(self, notify):
        mac_client.handle_event(self.EVENT, content_mode="title")

        notify.assert_called_once_with("微信", "转发：微信", "何昊")

    @mock.patch.object(mac_client, "notify")
    def test_phone_source_mode_is_never_weakened_by_receiver(self, notify):
        event = dict(self.EVENT, privacyMode="source")
        mac_client.handle_event(event, content_mode="full")

        notify.assert_called_once_with("微信", "转发：微信", "")

    def test_server_list_is_pinned_to_exact_official_https_base(self):
        values = [
            "http://192.0.2.10:8787",
            "http://100.64.0.10:8787",
            "https://example.com/xxzf/",
            "https://user@example.com:8443/xxzf",
            mac_client.OFFICIAL_SERVER,
        ]

        self.assertEqual(
            [mac_client.OFFICIAL_SERVER],
            mac_client.parse_servers(values),
        )

    @mock.patch.object(mac_client, "notify")
    @mock.patch.object(mac_client, "diagnostic_log")
    def test_delivery_stdout_does_not_contain_notification_content(
            self, diagnostic_log, notify):
        output = io.StringIO()
        with redirect_stdout(output):
            mac_client.handle_event(self.EVENT, content_mode="full")

        rendered = output.getvalue()
        self.assertNotIn(self.EVENT["title"], rendered)
        self.assertNotIn(self.EVENT["text"], rendered)
        self.assertNotIn(self.EVENT["appName"], rendered)
        self.assertIn("notification delivered", rendered)

    def test_loading_credentials_migrates_only_server_list(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "receiver.json"
            original = {
                "receiverId": "r_test",
                "receiverSecret": "secret_test_value",
                "receiverFingerprint": "ABC123",
                "contentMode": "title",
                "servers": ["http://192.0.2.10:8787"],
            }
            path.write_text(json.dumps(original), encoding="utf-8")

            with mock.patch.object(mac_client, "CREDENTIAL_FILE", path):
                loaded = mac_client.load_receiver_credentials()

            migrated = json.loads(path.read_text("utf-8"))
            self.assertEqual(original["receiverId"], loaded["receiverId"])
            self.assertEqual(original["receiverSecret"], loaded["receiverSecret"])
            self.assertEqual(original["receiverSecret"], migrated["receiverSecret"])
            self.assertEqual([mac_client.OFFICIAL_SERVER], migrated["servers"])
            self.assertEqual(0o600, path.stat().st_mode & 0o777)


if __name__ == "__main__":
    unittest.main()
