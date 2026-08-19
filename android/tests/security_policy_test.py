import os
import pathlib
import re
import subprocess
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "com" / "zundu" / "notifybridge"


class AndroidSecurityPolicyTest(unittest.TestCase):
    def test_secret_store_is_keystore_aes_gcm_and_has_no_logging(self):
        source = (SRC / "SecretStore.java").read_text(encoding="utf-8")
        self.assertIn('KEYSTORE = "AndroidKeyStore"', source)
        self.assertIn('Cipher.getInstance("AES/GCM/NoPadding")', source)
        self.assertIn("setRandomizedEncryptionRequired(true)", source)
        self.assertNotRegex(source, r"android\.util\.Log|System\.(?:out|err)")

    def test_device_secret_has_no_plaintext_write_or_read_fallback(self):
        prefs = (SRC / "Prefs.java").read_text(encoding="utf-8")
        self.assertNotIn("putString(KEY_DEVICE_SECRET", prefs)
        self.assertNotIn("getString(KEY_DEVICE_SECRET", prefs)
        self.assertIn("SecretStore.read", prefs)
        self.assertIn("SecretStore.stageWrite", prefs)

    def test_receiver_uses_separate_keystore_slot_and_authenticated_official_sse(self):
        prefs = (SRC / "Prefs.java").read_text(encoding="utf-8")
        receiver = (SRC / "ReceiverBridgeService.java").read_text(encoding="utf-8")
        client = (SRC / "ReceiverClient.java").read_text(encoding="utf-8")
        manifest = (ROOT / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn('stageWriteSlot(', prefs)
        self.assertIn('"receiver"', prefs)
        self.assertIn('ServerPolicy.officialBase() + "/v1/events"', receiver)
        self.assertIn('"Authorization", "Bearer "', receiver)
        self.assertIn("setInstanceFollowRedirects(false)", receiver)
        self.assertIn("setInstanceFollowRedirects(false)", client)
        self.assertIn('android:name=".ReceiverBridgeService"', manifest)
        self.assertIn('android:exported="false"', manifest)
        self.assertIn('android:foregroundServiceType="remoteMessaging"', manifest)

    def test_received_notifications_are_not_forwarded_back_into_a_loop(self):
        listener = (SRC / "NotifyBridgeService.java").read_text(encoding="utf-8")
        receiver = (SRC / "ReceiverBridgeService.java").read_text(encoding="utf-8")
        self.assertIn("EXTRA_RECEIVER_DELIVERY", listener)
        self.assertIn("extras.putBoolean(EXTRA_RECEIVER_DELIVERY, true)", receiver)

    def test_update_transport_and_artifact_checks_are_pinned(self):
        security = (SRC / "UpdateSecurity.java").read_text(encoding="utf-8")
        manager = (SRC / "UpdateManager.java").read_text(encoding="utf-8")
        self.assertIn('"https://updates.example.com/downloads/forwarder/test/android.json"', security)
        self.assertIn('"8545bd8392ab5de2"', security)
        self.assertIn('Signature.getInstance("SHA256withRSA")', security)
        self.assertGreaterEqual(manager.count("setInstanceFollowRedirects(false)"), 2)
        self.assertIn("APK signer mismatch", manager)
        self.assertIn("APK digest mismatch", manager)
        self.assertIn("APK version mismatch", manager)

    def test_installer_provider_is_private_and_read_only(self):
        manifest = (ROOT / "AndroidManifest.xml").read_text(encoding="utf-8")
        provider = (SRC / "UpdateFileProvider.java").read_text(encoding="utf-8")
        self.assertIn("android.permission.REQUEST_INSTALL_PACKAGES", manifest)
        block = re.search(r"<provider[\s\S]*?</provider>|<provider[\s\S]*?/>", manifest)
        self.assertIsNotNone(block)
        self.assertIn('android:exported="false"', block.group(0))
        self.assertIn('android:grantUriPermissions="true"', block.group(0))
        self.assertIn('if (!"r".equals(mode))', provider)
        self.assertIn("getCanonicalPath", provider)

    def test_background_check_never_downloads(self):
        manager = (SRC / "UpdateManager.java").read_text(encoding="utf-8")
        body = re.search(
            r"static void checkInBackground\(Context context\) \{([\s\S]*?)\n    \}", manager
        )
        self.assertIsNotNone(body)
        self.assertNotIn("download(", body.group(1))
        self.assertIn("showAvailableNotification", body.group(1))

    def test_update_recovery_is_scheduled_before_the_system_installer(self):
        manager = (SRC / "UpdateManager.java").read_text(encoding="utf-8")
        recovery = (SRC / "UpdateRecovery.java").read_text(encoding="utf-8")
        receiver = (SRC / "UpdateRecoveryReceiver.java").read_text(encoding="utf-8")
        manifest = (ROOT / "AndroidManifest.xml").read_text(encoding="utf-8")

        schedule = manager.index("UpdateRecovery.schedule(activity, data.versionCode);")
        launch = manager.index("activity.startActivity(installer);")
        self.assertLess(schedule, launch)
        self.assertIn("new Intent(context, UpdateRecoveryReceiver.class)", recovery)
        self.assertIn("PendingIntent.getBroadcast", recovery)
        self.assertIn("PendingIntent.FLAG_IMMUTABLE", recovery)
        self.assertIn("AlarmManager.ELAPSED_REALTIME_WAKEUP", recovery)
        delays = re.search(r"RETRY_DELAYS_MS\s*=\s*\{([\s\S]*?)\};", recovery)
        self.assertIsNotNone(delays)
        self.assertGreaterEqual(len([item for item in delays.group(1).split(",") if item.strip()]), 3)
        self.assertIn("for (int index = 0; index < RETRY_DELAYS_MS.length; index++)", recovery)
        self.assertIn("BackgroundRecovery.restoreAfterUpdate", receiver)
        listener = (SRC / "ListenerBinding.java").read_text(encoding="utf-8")
        self.assertIn("request(application, 0);", listener)
        self.assertIn("NotificationListenerService.requestRebind(component);", listener)
        update_repair = re.search(
            r"static void repairAfterUpdate\(Context context\) \{([\s\S]*?)\n    \}",
            listener,
        )
        self.assertIsNotNone(update_repair)
        self.assertIn("ListenerHealth.shouldRequestRebind(", update_repair.group(1))
        self.assertIn("request(application, 0);", update_repair.group(1))
        self.assertNotIn("refreshComponent(", update_repair.group(1))
        force_repair = re.search(
            r"static void forceRepair\(Context context\) \{([\s\S]*?)\n    \}",
            listener,
        )
        self.assertIsNotNone(force_repair)
        self.assertIn("refreshComponent(application);", force_repair.group(1))
        self.assertNotIn("request(application, 0);", force_repair.group(1))
        refresh = re.search(
            r"private static void refreshComponent\(Context context\) "
            r"\{([\s\S]*?)\n    \}\n\n    private static void request",
            listener,
        )
        self.assertIsNotNone(refresh)
        self.assertIn("restoreComponentEnabled(", refresh.group(1))
        self.assertIn("COMPONENT_ENABLED_STATE_DISABLED", refresh.group(1))
        self.assertNotRegex(
            refresh.group(1),
            r"postDelayed\([\s\S]*?COMPONENT_ENABLED_STATE_ENABLED",
        )
        self.assertIn("COMPONENT_ENABLED_STATE_DEFAULT", listener)

        block = re.search(
            r'<receiver\s+android:name="\.UpdateRecoveryReceiver"([\s\S]*?)/>', manifest
        )
        self.assertIsNotNone(block)
        self.assertIn('android:exported="false"', block.group(0))
        self.assertNotIn("intent-filter", block.group(0))

    def test_adb_update_preserves_notification_listener_consent(self):
        deploy = (ROOT.parent / "scripts" / "push_to_phone.sh").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("disallow_listener", deploy)
        self.assertIn("listener_was_enabled=0", deploy)
        self.assertIn("restore_listener_if_previously_allowed", deploy)
        self.assertIn('if [ "$listener_was_enabled" -eq 1 ]', deploy)
        self.assertNotIn("com.zundu.notifybridge/.DebugReceiver", deploy)

    def test_adb_update_is_pinned_to_one_explicit_device(self):
        scripts = ROOT.parent / "scripts"
        deploy = (scripts / "push_to_phone.sh").read_text(encoding="utf-8")
        vivo = (scripts / "confirm_vivo_install.sh").read_text(encoding="utf-8")

        self.assertIn('serial="${1:-}"', deploy)
        self.assertIn('confirm_vivo_install.sh" "$serial"', deploy)
        self.assertGreaterEqual(deploy.count('-s "$serial"'), 10)
        self.assertNotRegex(deploy, r"(?m)^\s*adb(?:\s|$)")
        self.assertIn('serial="${1:-}"', vivo)
        self.assertGreaterEqual(vivo.count('-s "$serial"'), 6)
        self.assertNotRegex(vivo, r"(?m)^\s*adb(?:\s|$)")

    def test_vivo_installer_restores_settings_and_targets_semantic_bounds(self):
        vivo = (
            ROOT.parent / "scripts" / "confirm_vivo_install.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("original_secure_value=", vivo)
        self.assertIn("original_global_value=", vivo)
        self.assertIn("restore_setting secure", vivo)
        self.assertIn("restore_setting global", vivo)
        self.assertRegex(vivo, r"trap ['\"]cleanup['\"] EXIT")
        self.assertIn("xmllint", vivo)
        self.assertIn("deleted_file_state_cb", vivo)
        self.assertRegex(vivo, r"继续安装|android:id/button1")
        self.assertNotIn("input tap 540 2090", vivo)
        self.assertNotIn("input tap 540 2238", vivo)

    def test_vivo_installer_helper_uses_bounds_and_restores_exact_values(self):
        helper = ROOT.parent / "scripts" / "confirm_vivo_install.sh"
        with tempfile.TemporaryDirectory() as directory:
            work = pathlib.Path(directory)
            log = work / "adb.log"
            state = work / "tap-count"
            before = work / "before.xml"
            after = work / "after.xml"
            fake_adb = work / "adb"
            before.write_text(
                """<?xml version="1.0"?><hierarchy><node """
                """package="com.android.packageinstaller" """
                """resource-id="com.android.packageinstaller:id/deleted_file_state_cb" """
                """checked="false" enabled="true" clickable="true" """
                """bounds="[10,20][30,40]" />"""
                """<node package="com.android.packageinstaller" """
                """resource-id="android:id/button1" content-desc="继续安装" """
                """checked="false" enabled="false" clickable="false" """
                """bounds="[100,200][300,400]" />"""
                """</hierarchy>""",
                encoding="utf-8",
            )
            after.write_text(
                """<?xml version="1.0"?><hierarchy><node """
                """package="com.android.packageinstaller" """
                """resource-id="com.android.packageinstaller:id/deleted_file_state_cb" """
                """checked="true" enabled="true" clickable="true" """
                """bounds="[10,20][30,40]" />"""
                """<node package="com.android.packageinstaller" """
                """resource-id="android:id/button1" content-desc="继续安装" """
                """checked="false" enabled="true" clickable="true" """
                """bounds="[100,200][300,400]" />"""
                """</hierarchy>""",
                encoding="utf-8",
            )
            fake_adb.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/python3
                    import os
                    import pathlib
                    import shlex
                    import shutil
                    import sys

                    args = sys.argv[1:]
                    log = pathlib.Path(os.environ["FAKE_ADB_LOG"])
                    with log.open("a", encoding="utf-8") as output:
                        output.write(" ".join(shlex.quote(value) for value in args) + "\\n")
                    if args[:2] != ["-s", "TESTSERIAL"]:
                        raise SystemExit(91)
                    command = args[2:]
                    if command == ["get-state"]:
                        print("device")
                    elif command[:4] == ["shell", "settings", "get", "secure"]:
                        print("7")
                    elif command[:4] == ["shell", "settings", "get", "global"]:
                        print("null")
                    elif command and command[0] == "pull":
                        state_path = pathlib.Path(os.environ["FAKE_ADB_STATE"])
                        count = int(state_path.read_text() or "0") if state_path.exists() else 0
                        source = os.environ[
                            "FAKE_ADB_AFTER" if count else "FAKE_ADB_BEFORE"
                        ]
                        shutil.copyfile(source, command[2])
                    elif command[:3] == ["shell", "input", "tap"]:
                        state_path = pathlib.Path(os.environ["FAKE_ADB_STATE"])
                        count = int(state_path.read_text() or "0") if state_path.exists() else 0
                        state_path.write_text(str(count + 1))
                    """
                ),
                encoding="utf-8",
            )
            fake_adb.chmod(0o700)
            environment = os.environ.copy()
            environment.update(
                {
                    "ADB_BIN": str(fake_adb),
                    "FAKE_ADB_LOG": str(log),
                    "FAKE_ADB_STATE": str(state),
                    "FAKE_ADB_BEFORE": str(before),
                    "FAKE_ADB_AFTER": str(after),
                }
            )
            result = subprocess.run(
                [str(helper), "TESTSERIAL"],
                env=environment,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            calls = log.read_text(encoding="utf-8").splitlines()
            self.assertTrue(calls)
            self.assertTrue(all(call.startswith("-s TESTSERIAL ") for call in calls))
            self.assertIn("-s TESTSERIAL shell input tap 20 30", calls)
            self.assertIn("-s TESTSERIAL shell input tap 200 300", calls)
            self.assertIn(
                "-s TESTSERIAL shell settings put secure vivo_monkey_test 7",
                calls,
            )
            self.assertIn(
                "-s TESTSERIAL shell settings delete global vivo_monkey_test",
                calls,
            )
            self.assertEqual("2", state.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
