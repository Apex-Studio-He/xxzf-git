#!/usr/bin/env python3
import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / "scripts" / "publish_test_update.py"
VERIFIER = ROOT / "scripts" / "verify_published_update.py"
DEPLOYER = ROOT / "scripts" / "deploy_test_updates.sh"
REMOTE_INSTALLER = ROOT / "scripts" / "install_test_update_set_remote.sh"
REMOTE_ROUTE_CHECKER = ROOT / "scripts" / "verify_remote_update_routes.sh"


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

    def test_deployer_keeps_private_key_local_and_installs_atomically(self):
        deployer = DEPLOYER.read_text("utf-8")
        self.assertIn("publish_test_update.py", deployer)
        self.assertIn("verify_published_update.py", deployer)
        self.assertIn("install_test_update_set_remote.sh", deployer)
        self.assertIn("verify_remote_update_routes.sh", deployer)
        self.assertIn("shasum -a 256", deployer)
        self.assertIn("REMOTE_UPLOAD_STARTED", deployer)
        self.assertNotIn("--ios", deployer)
        self.assertIn('publish android "$ANDROID_VERSION" "$ANDROID_CODE" "$ANDROID_PACKAGE"', deployer)
        self.assertIn('publish macos "$MACOS_VERSION" "$MACOS_CODE" "$MACOS_PACKAGE"', deployer)
        self.assertIn('publish windows "$WINDOWS_VERSION" "$WINDOWS_CODE" "$WINDOWS_PACKAGE"', deployer)
        self.assertIn("--preflight-only", deployer)
        self.assertIn("require_exact_route", deployer)
        self.assertIn("COPYFILE_DISABLE=1", deployer)
        self.assertLess(
            deployer.index('"$REMOTE_ROUTE_CHECKER"'),
            deployer.index('/usr/bin/scp -q'),
        )
        self.assertNotIn("update-private.pem", deployer)

    def test_deployer_archive_excludes_macos_appledouble_entries(self):
        staging = self.root / "archive-staging"
        staging.mkdir()
        (staging / "macos.json").write_text("{}", encoding="utf-8")
        (staging / "forwarder-macos-1.3.2-test.dmg").write_bytes(b"fixture dmg")
        subprocess.run(
            [
                "/usr/bin/xattr", "-w", "com.zundu.xxzf.fixture", "value",
                str(staging / "macos.json"),
            ],
            check=True,
        )
        archive = self.root / "updates.tar.gz"
        subprocess.run(
            [
                "/usr/bin/env", "COPYFILE_DISABLE=1", "/usr/bin/tar",
                "-C", str(staging), "-czf", str(archive),
                "macos.json", "forwarder-macos-1.3.2-test.dmg",
            ],
            check=True,
        )
        with tarfile.open(archive, "r:gz") as bundle:
            self.assertEqual(
                [member.name for member in bundle.getmembers()],
                ["macos.json", "forwarder-macos-1.3.2-test.dmg"],
            )

    def test_remote_active_nginx_route_gate_rejects_missing_artifact_before_upload(self):
        package_name = "forwarder-windows-0.3.0-test.exe"
        nginx_dump = self.root / "nginx-dump.txt"
        nginx_dump.write_text(
            "# configuration file /usr/local/etc/nginx/xxzf_public_routes.inc:\n"
            "    location = /downloads/forwarder/test/windows.json {\n",
            encoding="utf-8",
        )
        fake_ssh = self.root / "fake-ssh.sh"
        fake_ssh.write_text(
            "#!/usr/bin/env bash\n/bin/cat \"$XXZF_FAKE_NGINX_DUMP\"\n",
            encoding="utf-8",
        )
        os.chmod(fake_ssh, 0o755)
        environment = dict(os.environ)
        environment["XXZF_FAKE_NGINX_DUMP"] = str(nginx_dump)
        command = [
            "/bin/bash", str(REMOTE_ROUTE_CHECKER), str(fake_ssh), "fixture-host",
            "windows", package_name,
        ]
        rejected = subprocess.run(
            command,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("missing or duplicated active nginx route", rejected.stderr)

        with nginx_dump.open("a", encoding="utf-8") as handle:
            handle.write(
                "    location = /downloads/forwarder/test/"
                f"{package_name} {{\n"
            )
        accepted = subprocess.run(
            command,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

        retired = subprocess.run(
            command[:-2] + ["ios", "forwarder-ios-0.3.1-test.ipa"],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertNotEqual(retired.returncode, 0)
        self.assertIn("Unsupported route platform", retired.stderr)

    def test_deployer_accepts_macos_only_and_rejects_unrouted_version(self):
        package = self.root / "candidate.dmg"
        package.write_bytes(b"macos package")
        common = [
            "/bin/bash", str(DEPLOYER), "--preflight-only", "--macos", str(package),
            "--macos-code", "13",
        ]
        accepted = subprocess.run(
            common + ["--macos-version", "1.3.2"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertIn("platforms=macos", accepted.stdout)

        rejected = subprocess.run(
            common + ["--macos-version", "9.9.9"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("exact nginx route", rejected.stderr)

        retired = subprocess.run(
            [
                "/bin/bash", str(DEPLOYER), "--preflight-only", "--ios", str(package),
                "--ios-version", "0.3.1", "--ios-code", "13",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(retired.returncode, 2)

    def test_deployer_rejects_wrong_private_key_before_remote_upload(self):
        package = self.root / "candidate.apk"
        package.write_bytes(b"android package signed by the wrong key")
        environment = dict(os.environ)
        environment["XXZF_UPDATE_PRIVATE_KEY"] = str(self.private_key)
        environment["XXZF_UPDATE_SSH_TARGET"] = "must-not-connect.invalid"
        rejected = subprocess.run(
            [
                "/bin/bash", str(DEPLOYER), "--android", str(package),
                "--android-version", "0.9.11", "--android-code", "13",
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("manifest signature verification failed", rejected.stderr)
        self.assertNotIn("must-not-connect.invalid", rejected.stderr)

    def _remote_installer_fixture(self, name):
        parent = self.root / name
        remote_root = parent / "test"
        remote_root.mkdir(parents=True)
        originals = {
            "android.json": b"old android manifest",
            "forwarder-android-0.9.11-test.apk": b"old android package",
            "macos.json": b"old macos manifest",
            "forwarder-macos-1.3.2-test.dmg": b"old macos package",
        }
        for filename, contents in originals.items():
            (remote_root / filename).write_bytes(contents)

        incoming = self.root / f"{name}-incoming"
        incoming.mkdir()
        manifest_text = (
            '{"url":"https://updates.example.com/downloads/forwarder/test/'
            'forwarder-windows-0.3.0-test.exe"}'
        )
        (incoming / "windows.json").write_text(manifest_text, encoding="utf-8")
        (incoming / "forwarder-windows-0.3.0-test.exe").write_bytes(b"new windows package")
        archive = self.root / f"{name}.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            for path in sorted(incoming.iterdir()):
                bundle.add(path, arcname=path.name)

        verifier = self.root / f"{name}-verifier.py"
        verifier.write_text(
            "#!/usr/bin/env python3\n"
            "import pathlib, sys\n"
            "manifest = pathlib.Path(sys.argv[1])\n"
            "root = pathlib.Path(sys.argv[sys.argv.index('--package-root') + 1])\n"
            "assert 'forwarder-windows-0.3.0-test.exe' in manifest.read_text(encoding='utf-8')\n"
            "assert (root / 'forwarder-windows-0.3.0-test.exe').is_file()\n",
            encoding="utf-8",
        )
        os.chmod(verifier, 0o755)
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        command = [
            "/bin/bash", str(REMOTE_INSTALLER), str(archive), digest(archive),
            str(remote_root), str(verifier), digest(verifier), "windows",
        ]
        return remote_root, originals, command

    def test_remote_installer_preserves_existing_files_for_single_platform_update(self):
        remote_root, originals, command = self._remote_installer_fixture("merge")
        identical_package = remote_root / "forwarder-windows-0.3.0-test.exe"
        identical_package.write_bytes(b"new windows package")
        originals[identical_package.name] = b"new windows package"
        installed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        self.assertEqual(installed.returncode, 0, installed.stderr)
        for filename, contents in originals.items():
            self.assertEqual((remote_root / filename).read_bytes(), contents)
        self.assertIn(
            "forwarder-windows-0.3.0-test.exe",
            (remote_root / "windows.json").read_text("utf-8"),
        )
        self.assertEqual(
            (remote_root / "forwarder-windows-0.3.0-test.exe").read_bytes(),
            b"new windows package",
        )

        _, _, retired_command = self._remote_installer_fixture("retired-platform")
        retired = subprocess.run(
            retired_command[:-1] + ["ios"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        self.assertNotEqual(retired.returncode, 0)
        self.assertIn("unsupported update platform", retired.stderr)

    def test_remote_installer_rejects_immutable_package_byte_drift(self):
        remote_root, originals, command = self._remote_installer_fixture("immutable-drift")
        immutable_package = remote_root / "forwarder-windows-0.3.0-test.exe"
        immutable_package.write_bytes(b"different bytes under the same immutable URL")
        originals[immutable_package.name] = immutable_package.read_bytes()
        rejected = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("immutable package collision", rejected.stderr)
        self.assertEqual(
            {path.name: path.read_bytes() for path in remote_root.iterdir()},
            originals,
        )

    def test_remote_installer_keeps_download_root_path_stable(self):
        installer = REMOTE_INSTALLER.read_text("utf-8")
        self.assertNotIn('swap_move "$REMOTE_ROOT"', installer)
        self.assertNotIn('/bin/mv "$REMOTE_ROOT"', installer)
        self.assertIn("MANIFEST_STAGED", installer)
        self.assertIn("rollback_manifests", installer)
        self.assertIn("immutable package collision", installer)

    def test_remote_installer_restores_root_when_either_swap_move_fails(self):
        for failed_move in (1, 2):
            with self.subTest(failed_move=failed_move):
                remote_root, originals, command = self._remote_installer_fixture(
                    f"fail-move-{failed_move}"
                )
                old_manifest = remote_root / "windows.json"
                old_manifest.write_bytes(b"previous signed windows manifest")
                originals[old_manifest.name] = old_manifest.read_bytes()
                environment = dict(os.environ)
                environment["XXZF_UPDATE_TEST_MODE"] = "1"
                environment["XXZF_UPDATE_TEST_FAIL_MOVE"] = str(failed_move)
                failed = subprocess.run(
                    command,
                    env=environment,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=10,
                )
                self.assertNotEqual(failed.returncode, 0)
                self.assertIn("INJECTED_SWAP_FAILURE", failed.stderr)
                self.assertTrue(remote_root.is_dir())
                self.assertEqual(
                    {path.name: path.read_bytes() for path in remote_root.iterdir()},
                    originals,
                )
                self.assertEqual([], list(remote_root.parent.glob(".test-*")))

    def test_remote_installer_rejects_unsafe_existing_root_entries(self):
        remote_root, originals, command = self._remote_installer_fixture("unsafe-root")
        nested = remote_root / "unexpected-directory"
        nested.mkdir()
        rejected = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("symlink, directory, or special file", rejected.stderr)
        self.assertTrue(nested.is_dir())
        for filename, contents in originals.items():
            self.assertEqual((remote_root / filename).read_bytes(), contents)

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
