#!/usr/bin/env python3
import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / "scripts" / "publish_test_update.py"
VERIFIER = ROOT / "scripts" / "verify_published_update.py"


def load_publisher():
    spec = importlib.util.spec_from_file_location("publish_test_update", PUBLISHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_verifier():
    spec = importlib.util.spec_from_file_location("verify_published_update", VERIFIER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exact_location_block(routes, path):
    marker = f"    location = {path} {{"
    start = routes.find(marker)
    if start < 0:
        raise AssertionError(f"missing exact nginx location: {path}")
    end = routes.find("\n    location ", start + len(marker))
    return routes[start:end if end >= 0 else len(routes)]


class UpdateManifestTests(unittest.TestCase):
    def setUp(self):
        self.publisher = load_publisher()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.private_key = self.root / "private.pem"
        self.public_key = self.root / "public.pem"
        subprocess.run(
            ["/usr/bin/openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(self.private_key)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.chmod(self.private_key, 0o600)
        subprocess.run(
            ["/usr/bin/openssl", "pkey", "-in", str(self.private_key), "-pubout", "-out", str(self.public_key)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.public_key_der = self.root / "public.der"
        subprocess.run(
            [
                "/usr/bin/openssl", "pkey", "-pubin", "-in", str(self.public_key),
                "-outform", "DER", "-out", str(self.public_key_der),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.package = self.root / "candidate.apk"
        self.package.write_bytes(b"test package contents")

    def tearDown(self):
        self.temporary.cleanup()

    def test_manifest_signature_and_package_are_reproducibly_verifiable(self):
        output = self.root / "output"
        manifest, package = self.publisher.build_manifest(
            "android", 13, "0.9.3", "安全更新测试", self.package, self.private_key, output
        )
        stored = json.loads((output / "android.json").read_text("utf-8"))
        self.assertEqual(stored["sha256"], manifest["sha256"])
        self.assertEqual(stored["size"], package.stat().st_size)
        self.assertEqual(package.name, "forwarder-android-0.9.3-test.apk")
        signature = self.root / "signature.bin"
        signature.write_bytes(base64.b64decode(stored.pop("signature")))
        verified = subprocess.run(
            ["/usr/bin/openssl", "dgst", "-sha256", "-verify", str(self.public_key), "-signature", str(signature)],
            input=self.publisher.canonical_payload(stored),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(verified.returncode, 0, verified.stderr.decode("utf-8", "replace"))

    def test_windows_manifest_uses_exact_schema_name_and_canonical_order(self):
        self.package = self.root / "candidate.exe"
        self.package.write_bytes(b"test windows package contents")
        output = self.root / "output"
        manifest, package = self.publisher.build_manifest(
            "windows", 13, "0.3.0", "Windows 安全更新测试",
            self.package, self.private_key, output
        )
        stored = json.loads((output / "windows.json").read_text("utf-8"))
        self.assertEqual(
            set(stored),
            {
                "schema", "channel", "platform", "versionCode", "version", "url",
                "sha256", "size", "publishedAt", "notes", "keyId", "signature",
            },
        )
        self.assertEqual(stored["platform"], "windows")
        self.assertEqual(package.name, "forwarder-windows-0.3.0-test.exe")
        self.assertEqual(
            self.publisher.canonical_payload({
                "schema": 1,
                "channel": "test",
                "platform": "windows",
                "versionCode": 13,
                "version": "0.3.0",
                "url": "https://example.invalid/forwarder-windows-0.3.0-test.exe",
                "sha256": "a" * 64,
                "size": 123,
                "publishedAt": "2026-08-02T00:00:00Z",
                "notes": "test",
                "keyId": "test-key",
            }),
            (
                "1\ntest\nwindows\n13\n0.3.0\n"
                "https://example.invalid/forwarder-windows-0.3.0-test.exe\n"
                f"{'a' * 64}\n123\n2026-08-02T00:00:00Z\ntest\ntest-key"
            ).encode("utf-8"),
        )
        with self.assertRaisesRegex(ValueError, "unsupported platform"):
            self.publisher.build_manifest(
                "ios", 13, "0.3.1", "retired", self.package,
                self.private_key, self.root / "retired-output"
            )

    def test_public_verifier_accepts_windows_and_rejects_platform_filename_mismatch(self):
        verifier = load_verifier()
        verifier.PUBLIC_KEY_DER_BASE64 = base64.b64encode(self.public_key_der.read_bytes()).decode("ascii")
        self.package = self.root / "candidate.exe"
        self.package.write_bytes(b"verified windows package")
        output = self.root / "output"
        manifest, package = self.publisher.build_manifest(
            "windows", 13, "0.3.0", "test", self.package, self.private_key, output
        )
        verified_manifest, verified_package = verifier.verify(output / "windows.json", output)
        self.assertEqual(verified_manifest["platform"], "windows")
        self.assertEqual(verified_package, package)

        mismatched_name = "forwarder-android-0.3.0-test.apk"
        mismatched_package = output / mismatched_name
        mismatched_package.write_bytes(package.read_bytes())
        mismatch = dict(manifest)
        mismatch["url"] = f"https://updates.example.com/downloads/forwarder/test/{mismatched_name}"
        mismatch.pop("signature")
        signed = subprocess.run(
            ["/usr/bin/openssl", "dgst", "-sha256", "-sign", str(self.private_key)],
            input=self.publisher.canonical_payload(mismatch),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        mismatch["signature"] = base64.b64encode(signed.stdout).decode("ascii")
        mismatch_path = output / "mismatch.json"
        mismatch_path.write_text(json.dumps(mismatch), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "does not match manifest platform"):
            verifier.verify(mismatch_path, output)

        extra_field = dict(manifest)
        extra_field["downloadMode"] = "unsupported-extension"
        extra_field_path = output / "extra-field.json"
        extra_field_path.write_text(json.dumps(extra_field), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "fields do not match"):
            verifier.verify(extra_field_path, output)

        oversized = dict(manifest)
        oversized.pop("signature")
        oversized["size"] = 128 * 1024 * 1024 + 1
        signed = subprocess.run(
            ["/usr/bin/openssl", "dgst", "-sha256", "-sign", str(self.private_key)],
            input=self.publisher.canonical_payload(oversized),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        oversized["signature"] = base64.b64encode(signed.stdout).decode("ascii")
        oversized_path = output / "oversized.json"
        oversized_path.write_text(json.dumps(oversized), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "outside the allowed range"):
            verifier.verify(oversized_path, output)

    def test_private_key_permissions_are_enforced(self):
        os.chmod(self.private_key, 0o644)
        with self.assertRaisesRegex(ValueError, "0600"):
            self.publisher.build_manifest(
                "android", 13, "0.9.3", "test", self.package, self.private_key, self.root / "output"
            )

    def test_private_key_and_package_symlinks_are_rejected(self):
        linked_key = self.root / "linked-private.pem"
        linked_key.symlink_to(self.private_key)
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            self.publisher.build_manifest(
                "android", 13, "0.9.3", "test", self.package, linked_key, self.root / "output"
            )
        linked_package = self.root / "linked.apk"
        linked_package.symlink_to(self.package)
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            self.publisher.build_manifest(
                "android", 13, "0.9.3", "test", linked_package, self.private_key, self.root / "output"
            )

    def test_output_root_symlink_is_rejected(self):
        real_output = self.root / "real-output"
        real_output.mkdir()
        linked_output = self.root / "linked-output"
        linked_output.symlink_to(real_output)
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            self.publisher.build_manifest(
                "android", 13, "0.9.3", "test", self.package, self.private_key, linked_output
            )

    def test_invalid_version_and_multiline_notes_are_rejected(self):
        for invalid_version in ("../../bad", "v1.2.3", "1.2_rc1", "1", "1.2-beta_1"):
            with self.subTest(version=invalid_version):
                with self.assertRaisesRegex(ValueError, "invalid version"):
                    self.publisher.build_manifest(
                        "android", 13, invalid_version, "test", self.package,
                        self.private_key, self.root / "output"
                    )
        with self.assertRaisesRegex(ValueError, "notes"):
            self.publisher.build_manifest(
                "android", 13, "0.9.3", "line one\nline two", self.package, self.private_key, self.root / "output"
            )
        with self.assertRaisesRegex(ValueError, "version code"):
            self.publisher.build_manifest(
                "android", 1 << 63, "0.9.3", "test", self.package,
                self.private_key, self.root / "output"
            )

    def test_version_contract_matches_remaining_clients(self):
        expected = r"^[0-9]+(?:\.[0-9]+){1,3}(?:-[A-Za-z0-9.]+)?$"
        verifier = load_verifier()
        self.assertEqual(self.publisher.VERSION_RE.pattern, expected)
        self.assertEqual(verifier.VERSION_RE.pattern, expected)
        self.assertEqual(self.publisher.MAX_VERSION_CODE, (1 << 63) - 1)
        self.assertEqual(verifier.MAX_VERSION_CODE, (1 << 63) - 1)
        self.assertIn(
            r'"[0-9]+(?:\\.[0-9]+){1,3}(?:-[A-Za-z0-9.]+)?"',
            (ROOT / "android" / "src" / "com" / "zundu" / "notifybridge" /
             "UpdateSecurity.java").read_text("utf-8"),
        )
        self.assertIn(
            r'@"^[0-9]+\\.[0-9]+\\.[0-9]+$"',
            (ROOT / "server" / "mac_receiver" / "UpdateManager.m").read_text("utf-8"),
        )
        self.assertIn(
            r'@"^[0-9]+\.[0-9]+\.[0-9]+$"',
            (ROOT / "windows" / "Updater.cs").read_text("utf-8"),
        )

    def test_windows_package_size_limit_is_enforced(self):
        oversized = self.root / "oversized.exe"
        with oversized.open("wb") as handle:
            handle.seek(128 * 1024 * 1024)
            handle.write(b"x")
        with self.assertRaisesRegex(ValueError, "outside the allowed range"):
            self.publisher.build_manifest(
                "windows", 13, "0.3.0", "test", oversized,
                self.private_key, self.root / "output"
            )

    def test_publisher_preserves_immutable_package_bytes_for_repeated_version(self):
        output = self.root / "output"
        first = self.root / "first.dmg"
        first.write_bytes(b"original immutable macos bytes")
        _, published = self.publisher.build_manifest(
            "macos", 13, "1.3.2", "first", first, self.private_key, output
        )
        original_bytes = published.read_bytes()

        identical = self.root / "identical.dmg"
        identical.write_bytes(original_bytes)
        _, repeated = self.publisher.build_manifest(
            "macos", 13, "1.3.2", "repeat", identical, self.private_key, output
        )
        self.assertEqual(repeated.read_bytes(), original_bytes)

        drifted = self.root / "drifted.dmg"
        drifted.write_bytes(b"different bytes for the same immutable version")
        with self.assertRaisesRegex(ValueError, "immutable package collision"):
            self.publisher.build_manifest(
                "macos", 13, "1.3.2", "drift", drifted, self.private_key, output
            )
        self.assertEqual(published.read_bytes(), original_bytes)

    def test_test_channel_uses_new_names_and_keeps_legacy_routes_blocked(self):
        routes = (ROOT / "nginx" / "xxzf_public_routes.inc").read_text("utf-8")
        self.assertIn("return 410;", routes)
        manifest_paths = (
            "/downloads/forwarder/test/android.json",
            "/downloads/forwarder/test/macos.json",
            "/downloads/forwarder/test/windows.json",
        )
        package_paths = (
            "/downloads/forwarder/test/forwarder-android-0.9.16-test.apk",
            "/downloads/forwarder/test/forwarder-macos-1.3.2-test.dmg",
            "/downloads/forwarder/test/forwarder-windows-0.3.0-test.exe",
        )
        for path in manifest_paths + package_paths:
            self.assertIn(f"location = {path}", routes)
        self.assertNotIn("location = /downloads/forwarder/test/ios.json", routes)
        self.assertNotIn("location = /downloads/forwarder/test/forwarder-ios-", routes)
        self.assertNotIn("location = /downloads/forwarder/test/ipa-signer-macos-", routes)
        for bark_path in (
            "/xxzf/v1/bark/enroll/start", "/xxzf/v1/bark/enroll/claim",
            "/xxzf/v1/bark/test", "/xxzf/v1/bark/revoke", "/xxzf/bark",
            "/xxzf/bark/", "/xxzf/bark/index.html",
            "/xxzf/bark/bind.css", "/xxzf/bark/bind.js",
        ):
            self.assertIn(f"location = {bark_path} {{", routes)
        self.assertIn("limit_except GET { deny all; }", routes)
        self.assertIn('X-Content-Type-Options "nosniff"', routes)
        manifest_routes = tuple(exact_location_block(routes, path) for path in manifest_paths)
        package_routes = tuple(exact_location_block(routes, path) for path in package_paths)
        for route in manifest_routes + package_routes:
            self.assertIn("limit_except GET { deny all; }", route)
            self.assertIn("try_files $uri =404;", route)
            self.assertIn('X-Content-Type-Options "nosniff"', route)
            self.assertIn('Referrer-Policy "no-referrer"', route)
            self.assertIn('X-Robots-Tag "noindex, nofollow, noarchive"', route)
        for route in manifest_routes:
            self.assertIn("default_type application/json;", route)
            self.assertIn('Cache-Control "no-store, no-cache, must-revalidate"', route)
        for route in package_routes:
            self.assertIn('Cache-Control "public, max-age=31536000, immutable"', route)
        self.assertIn("default_type application/vnd.android.package-archive;", package_routes[0])
        self.assertIn("default_type application/x-apple-diskimage;", package_routes[1])
        self.assertIn("default_type application/vnd.microsoft.portable-executable;", package_routes[2])
        source = PUBLISHER.read_text("utf-8")
        self.assertIn('f"forwarder-{platform}-{version}-test.{extension}"', source)
        self.assertEqual(
            set(self.publisher.PLATFORMS), {"android", "macos", "windows"}
        )
        self.assertEqual(
            set(load_verifier().PLATFORMS), {"android", "macos", "windows"}
        )

    def test_legacy_server_coupled_compat_installer_is_not_distributed(self):
        installer = ROOT / "scripts" / "install_test_update_routes_compat.sh"
        self.assertFalse(installer.exists())

    def test_public_verifier_contains_no_private_key_material(self):
        verifier = (ROOT / "scripts" / "verify_published_update.py").read_text("utf-8")
        self.assertIn("PUBLIC_KEY_DER_BASE64", verifier)
        self.assertIn("openssl", verifier)
        self.assertIn("package size or digest mismatch", verifier)
        self.assertNotIn("PRIVATE KEY", verifier)


if __name__ == "__main__":
    unittest.main()
