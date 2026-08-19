#!/usr/bin/env python3
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleasePolicyTests(unittest.TestCase):
    def test_android_release_requires_external_pinned_signing_identity(self):
        script = (ROOT / "android" / "build.sh").read_text(encoding="utf-8")
        self.assertIn("XXZF_ANDROID_KEYSTORE", script)
        self.assertIn("XXZF_ANDROID_EXPECTED_CERT_SHA256", script)
        self.assertIn("NotifyBridge-release.apk", script)
        self.assertIn("A debug certificate cannot be used for a release APK", script)
        self.assertNotIn('KEYSTORE="$ROOT_DIR/debug.keystore"', script)

    def test_debug_signing_material_is_outside_the_source_tree(self):
        for relative in ("android/build.sh", "test_source/build.sh"):
            script = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("Library/Application Support/XXZF/signing", script)
            self.assertNotIn('KEYSTORE="$ROOT_DIR/debug.keystore"', script)

    def test_android_manifest_disables_cleartext_transport(self):
        manifest = (ROOT / "android" / "AndroidManifest.xml").read_text(
            encoding="utf-8"
        )
        self.assertIn('android:usesCleartextTraffic="false"', manifest)
        self.assertNotIn('android:usesCleartextTraffic="true"', manifest)

    def test_server_never_defaults_public_download_to_debug_apk(self):
        source = (ROOT / "server" / "server.py").read_text(encoding="utf-8")
        self.assertIn("XXZF_APK_FILE", source)
        self.assertIn("NotifyBridge-release.apk", source)
        self.assertNotIn(
            'dist" / "NotifyBridge-debug.apk',
            source,
        )

    def test_macos_release_requires_developer_id_and_notarization(self):
        signer = (ROOT / "scripts" / "sign_macos_app.sh").read_text(encoding="utf-8")
        notarizer = (ROOT / "scripts" / "notarize_macos_release.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("Developer ID Application", signer)
        self.assertIn("XXZF_MAC_EXPECTED_TEAM_ID", signer)
        self.assertIn("--options runtime", signer)
        self.assertIn("notarytool submit", notarizer)
        self.assertIn("stapler validate", notarizer)

    def test_windows_release_requires_pinned_authenticode_identity(self):
        signer = (ROOT / "windows" / "sign-release.ps1").read_text(encoding="utf-8")
        builder = (ROOT / "windows" / "build-installer.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("XXZF_WINDOWS_SIGN_CERT_SHA256", signer)
        self.assertIn("Get-AuthenticodeSignature", signer)
        self.assertIn("signtool verify", signer)
        self.assertIn('if ($buildVariant -eq "Release")', builder)

    def test_authoritative_routes_do_not_republish_legacy_unsigned_packages(self):
        routes = (ROOT / "nginx" / "xxzf_public_routes.inc").read_text(
            encoding="utf-8"
        )
        for legacy_name in (
            "forwarder-android-0.9.2.apk",
            "forwarder-macos-1.2.1.dmg",
            "forwarder-windows-0.2-setup.exe",
        ):
            block = routes.split(f"location = /downloads/forwarder/{legacy_name} {{", 1)[1]
            block = block.split("\n    }", 1)[0]
            self.assertIn("return 410;", block)
            self.assertNotIn("alias ", block)


if __name__ == "__main__":
    unittest.main()
