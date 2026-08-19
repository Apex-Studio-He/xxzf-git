#!/usr/bin/env python3
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WindowsUpdateSecurityTests(unittest.TestCase):
    def setUp(self):
        self.updater = (ROOT / "windows" / "Updater.cs").read_text("utf-8")
        self.forwarder = (ROOT / "windows" / "Forwarder.cs").read_text("utf-8")
        self.installer = (ROOT / "windows" / "install.ps1").read_text("utf-8")
        self.installer_builder = (ROOT / "windows" / "build-installer.ps1").read_text(
            "utf-8"
        )
        self.installer_verifier = (ROOT / "windows" / "verify-installer.ps1").read_text(
            "utf-8"
        )

    def test_update_transport_and_signature_are_pinned(self):
        self.assertIn(
            '"https://updates.example.com/downloads/forwarder/test/windows.json"',
            self.updater,
        )
        self.assertIn('ExpectedKeyId = "8545bd8392ab5de2"', self.updater)
        self.assertIn("AllowAutoRedirect = false", self.updater)
        self.assertIn("AutomaticDecompression = DecompressionMethods.None", self.updater)
        self.assertIn("RSACryptoServiceProvider(3072)", self.updater)
        self.assertIn("VerifyData", self.updater)
        self.assertIn("FixedTimeEquals", self.updater)

    def test_download_is_bounded_hashed_and_smartscreen_marked(self):
        self.assertIn("total > manifest.Size", self.updater)
        self.assertIn("total > MaximumPackageBytes", self.updater)
        self.assertIn("FileMode.CreateNew", self.updater)
        self.assertIn("SHA256.Create()", self.updater)
        self.assertIn('path + ":Zone.Identifier"', self.updater)
        self.assertNotIn("ServicePointManager.ServerCertificateValidationCallback", self.updater)

    def test_private_files_use_dpapi_acl_and_reparse_rejection(self):
        self.assertIn("ProtectedData.Protect", self.forwarder)
        self.assertIn("ProtectedData.Unprotect", self.forwarder)
        self.assertIn("SetAccessRuleProtection(true, false)", self.updater)
        self.assertIn("WellKnownSidType.LocalSystemSid", self.updater)
        self.assertIn("FileAttributes.ReparsePoint", self.updater)
        self.assertGreaterEqual(self.forwarder.count("WindowsFileSecurity.ProtectFile"), 4)

    def test_installer_is_fixed_path_verified_and_rolls_back(self):
        for required in (
            "Assert-NoReparsePath",
            "Get-ExpectedPayload",
            "Assert-PayloadFile",
            'Join-Path $env:LOCALAPPDATA "XXZF\\Forwarder"',
            ".Forwarder.exe.previous",
            "安装来源文件 SHA-256 校验失败",
        ):
            self.assertIn(required, self.installer)
        self.assertRegex(self.installer, r"catch \{[\s\S]*backupExe[\s\S]*throw")

    def test_installer_builder_and_verifier_use_the_same_release(self):
        package_name = "Forwarder-Windows-0.3.0-Test-Setup.exe"
        self.assertIn(package_name, self.installer_builder)
        self.assertIn(package_name, self.installer_verifier)
        self.assertIn('expectedVersion = "0.3.0.0"', self.installer_verifier)
        self.assertIn("GetFullPath($installed)", self.installer_verifier)
        self.assertIn("Remove-Item -LiteralPath $sed", self.installer_builder)

    def test_ui_has_manual_startup_and_six_hour_checks(self):
        self.assertIn('NewButton("检查更新"', self.forwarder)
        self.assertIn("6 * 60 * 60 * 1000", self.forwarder)
        self.assertIn("await CheckForUpdatesAsync(false)", self.forwarder)
        self.assertIn("MessageBoxButtons.YesNoCancel", self.forwarder)
        self.assertIn("SkippedUpdateVersionCode", self.forwarder)

    def test_update_check_accepts_an_older_signed_manifest_without_installing_it(self):
        self.assertIn("manifest.VersionCode <= CurrentVersionCode", self.updater)
        self.assertIn(
            "(!allowCurrent && versionCode <= CurrentVersionCode)", self.updater
        )
        self.assertNotIn(
            "versionCode < CurrentVersionCode || versionCode > Int32.MaxValue",
            self.updater,
        )


if __name__ == "__main__":
    unittest.main()
