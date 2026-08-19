#!/usr/bin/env python3
import io
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android" / "src" / "com" / "zundu" / "notifybridge"

sys.path.insert(0, str(ROOT / "server"))
import mac_client  # noqa: E402


class AndroidCredentialRecoveryPolicyTests(unittest.TestCase):
    def test_clear_requires_an_explicit_positive_confirmation(self):
        source = (ANDROID / "CredentialRecovery.java").read_text("utf-8")
        self.assertIn('.setNegativeButton("取消", null)', source)
        self.assertIn('.setPositiveButton("清除并重新配对"', source)
        self.assertLess(source.index(".setPositiveButton"), source.index("Prefs.clearPairing"))
        self.assertIn('"CREDENTIAL_RESET_CONFIRMED"', source)

    def test_auth_failure_exposes_recovery_without_automatic_clear(self):
        main = (ANDROID / "MainActivity.java").read_text("utf-8")
        pair = (ANDROID / "PairActivity.java").read_text("utf-8")
        server = (ANDROID / "ServerClient.java").read_text("utf-8")
        self.assertIn("ServerClient.AUTH_FAILED.equals(status)", main)
        self.assertIn("credentialRecoveryRequired && Prefs.paired", main)
        self.assertIn("updateCredentialRecoveryVisibility()", main)
        self.assertIn("CredentialRecovery.confirmAndClear(MainActivity.this", main)
        self.assertIn("CredentialRecovery.confirmAndClear(PairActivity.this", pair)
        self.assertNotIn("Prefs.clearPairing", server)


class MacCredentialRecoveryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.gui = (ROOT / "server" / "mac_receiver" / "Receiver.m").read_text("utf-8")

    def test_auth_failed_button_uses_cancel_default_before_local_clear(self):
        confirmation = self.gui.split("- (void)confirmCredentialRecovery {", 1)[1].split(
            "- (BOOL)clearCredentialForRecovery {", 1
        )[0]
        self.assertIn('[alert addButtonWithTitle:@"取消"]', confirmation)
        self.assertIn('[alert addButtonWithTitle:@"清除并重新配对"]', confirmation)
        self.assertIn("response != NSAlertSecondButtonReturn", confirmation)
        self.assertLess(
            confirmation.index("response != NSAlertSecondButtonReturn"),
            confirmation.index("clearCredentialForRecovery"),
        )

    def test_reset_preserves_privacy_mode_but_not_credentials(self):
        reset = self.gui.split("- (BOOL)clearCredentialForRecovery {", 1)[1].split(
            "- (void)acceptPairing", 1
        )[0]
        persisted = reset.split("NSDictionary *value", 1)[1].split("NSData *data", 1)[0]
        self.assertIn('@"contentMode"', persisted)
        self.assertIn('@"showContent"', persisted)
        self.assertIn('@"servers"', persisted)
        self.assertNotIn('@"receiverId"', persisted)
        self.assertNotIn('@"receiverSecret"', persisted)
        self.assertIn('self.receiverSecret = @""', reset)

    def test_background_receiver_refuses_anonymous_event_fallback(self):
        source = (ROOT / "server" / "mac_client.py").read_text("utf-8")
        self.assertNotIn('server + "/events"', source)
        with self.assertRaisesRegex(RuntimeError, "explicit pairing"):
            mac_client.stream(mac_client.OFFICIAL_SERVER, {}, credentials=None)

    def test_background_receiver_waits_for_a_different_confirmed_credential(self):
        rejected = {"receiverId": "old", "receiverSecret": "old-secret"}
        replacement = {"receiverId": "new", "receiverSecret": "new-secret"}
        with mock.patch.object(mac_client.time, "sleep"), mock.patch.object(
            mac_client,
            "load_receiver_credentials",
            side_effect=[None, dict(rejected), replacement],
        ):
            self.assertEqual(
                replacement,
                mac_client.wait_for_replacement_credentials(rejected),
            )

    def test_background_receiver_closes_http_error_response(self):
        response_body = io.BytesIO(b'{"error":"unavailable"}')
        upstream_error = urllib.error.HTTPError(
            mac_client.OFFICIAL_SERVER,
            500,
            "unavailable",
            {},
            response_body,
        )
        credentials = {
            "receiverId": "receiver-test",
            "receiverSecret": "secret-test",
            "servers": [mac_client.OFFICIAL_SERVER],
        }
        with mock.patch.object(
            mac_client,
            "load_receiver_credentials",
            return_value=credentials,
        ), mock.patch.object(
            mac_client,
            "stream",
            side_effect=[upstream_error, KeyboardInterrupt()],
        ), mock.patch.object(
            mac_client.time,
            "sleep",
        ), mock.patch.object(
            mac_client,
            "diagnostic_log",
        ), mock.patch(
            "builtins.print"
        ):
            with self.assertRaises(KeyboardInterrupt):
                mac_client.run()

        self.assertTrue(response_body.closed)


class WindowsCredentialRecoveryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "windows" / "Forwarder.cs").read_text("utf-8")

    def test_recovery_is_confirmation_gated_and_cancel_is_default(self):
        flow = self.source.split("private async Task BeginPairingOrRecoveryAsync", 1)[1].split(
            "private bool ClearLocalCredentialForRecovery", 1
        )[0]
        self.assertIn("MessageBoxButtons.YesNo", flow)
        self.assertIn("MessageBoxDefaultButton.Button2", flow)
        self.assertIn("if (answer != DialogResult.Yes) return", flow)
        self.assertLess(
            flow.index("if (answer != DialogResult.Yes) return"),
            flow.index("ClearLocalCredentialForRecovery"),
        )
        self.assertIn("Application.Restart()", flow)

    def test_auth_failure_stops_startup_and_pairing_from_silent_retry(self):
        startup = self.source.split("private async Task BeginStartupAsync", 1)[1].split(
            "private async Task BeginPairingOrRecoveryAsync", 1
        )[0]
        pairing = self.source.split("private async Task StartPairingAsync", 1)[1].split(
            "private void BeginPairingPoll", 1
        )[0]
        polling = self.source.split("private void BeginPairingPoll", 1)[1].split(
            "private async Task<bool> CheckPairingStatusAsync", 1
        )[0]
        self.assertIn("if (credentialRecoveryRequired)", startup)
        self.assertIn("MarkAuthenticationFailed(401);\n                    return;", startup)
        self.assertIn("HasCredential() && credentialRecoveryRequired", pairing)
        self.assertIn("MarkAuthenticationFailed(401);\n                return;", pairing)
        self.assertIn("if (credentialRecoveryRequired) return;", polling)
        self.assertNotIn("private async void BeginStartup", self.source)
        self.assertIn("await BeginStartupAsync()", self.source)

    def test_local_reset_preserves_content_preferences_and_restores_on_failure(self):
        reset = self.source.split("private bool ClearLocalCredentialForRecovery", 1)[1].split(
            "private bool HasCredential", 1
        )[0]
        self.assertNotIn("state.ContentMode =", reset)
        self.assertNotIn("state.ShowContent =", reset)
        self.assertIn("oldProtectedSecret", reset)
        self.assertIn("state.ProtectedSecret = oldProtectedSecret", reset)
        self.assertIn("return false", reset)


if __name__ == "__main__":
    unittest.main()
