#!/usr/bin/env python3
import os
import plistlib
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parent
BACKUP_SCRIPT = SERVER_DIR / "backup_server_data.sh"
PROVISION_SCRIPT = SERVER_DIR.parent / "scripts" / "provision_notify_token.sh"
SERVER_PLIST = (
    SERVER_DIR.parent
    / "deploy/launchd/com.zundu.xxzf.server.plist.example"
)


class ServerConfigurationTests(unittest.TestCase):
    def read_server_host(self, override=None):
        with tempfile.TemporaryDirectory() as temporary:
            token_file = Path(temporary) / "notify-token.txt"
            token_file.write_text(secrets.token_urlsafe(32), encoding="utf-8")
            token_file.chmod(0o600)
            environment = os.environ.copy()
            environment.pop("HOST", None)
            if override is not None:
                environment["HOST"] = override
            environment.update({
                "DATA_DIR": temporary,
                "XXZF_AUDIT_DIR": str(Path(temporary) / "audit"),
                "XXZF_DIAGNOSTIC_DIR": str(Path(temporary) / "diagnostics"),
                "XXZF_BARK_SECRET_FILE": str(Path(temporary) / "bark-secrets.json"),
                "XXZF_TOKEN_FILE": str(token_file),
                "PYTHONDONTWRITEBYTECODE": "1",
            })
            completed = subprocess.run(
                [sys.executable, "-c", "import server; print(server.HOST)"],
                cwd=SERVER_DIR,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
        return completed

    def test_server_defaults_to_loopback(self):
        completed = self.read_server_host()
        self.assertEqual(0, completed.returncode)
        self.assertEqual("127.0.0.1", completed.stdout.strip())

    def test_server_refuses_non_loopback_host_override(self):
        completed = self.read_server_host("0.0.0.0")
        self.assertNotEqual(0, completed.returncode)
        self.assertIn("loopback", completed.stderr.lower())

    def test_default_data_directory_is_private_application_support_not_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            data_dir = home / "Library" / "Application Support" / "XXZF" / "server-data"
            data_dir.mkdir(parents=True)
            token_file = data_dir / "notify-token.txt"
            token_file.write_text(secrets.token_urlsafe(32), encoding="utf-8")
            token_file.chmod(0o600)
            environment = os.environ.copy()
            environment["HOME"] = str(home)
            environment.pop("DATA_DIR", None)
            environment.pop("XXZF_TOKEN_FILE", None)
            environment.pop("XXZF_AUDIT_DIR", None)
            environment.pop("XXZF_DIAGNOSTIC_DIR", None)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            completed = subprocess.run(
                [sys.executable, "-c", "import server; print(server.DATA_DIR)"],
                cwd=SERVER_DIR,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertEqual(str(data_dir), completed.stdout.strip())
        self.assertNotIn(str(SERVER_DIR), completed.stdout.strip())

    def test_server_refuses_to_start_without_legacy_notify_token(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = os.environ.copy()
            environment.update({
                "DATA_DIR": str(root / "data"),
                "XXZF_AUDIT_DIR": str(root / "audit"),
                "XXZF_DIAGNOSTIC_DIR": str(root / "diagnostics"),
                "XXZF_BARK_SECRET_FILE": str(root / "bark-secrets.json"),
                "XXZF_TOKEN_FILE": str(root / "missing-token.txt"),
                "PYTHONDONTWRITEBYTECODE": "1",
            })
            completed = subprocess.run(
                [sys.executable, "-c", "import server"],
                cwd=SERVER_DIR,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(0, completed.returncode)
        self.assertIn("legacy notify token", completed.stderr.lower())

    def test_server_refuses_weak_legacy_notify_token(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            token_file = root / "weak-token.txt"
            token_file.write_text("repeated" * 8, encoding="utf-8")
            environment = os.environ.copy()
            environment.update({
                "DATA_DIR": str(root / "data"),
                "XXZF_AUDIT_DIR": str(root / "audit"),
                "XXZF_DIAGNOSTIC_DIR": str(root / "diagnostics"),
                "XXZF_BARK_SECRET_FILE": str(root / "bark-secrets.json"),
                "XXZF_TOKEN_FILE": str(token_file),
                "PYTHONDONTWRITEBYTECODE": "1",
            })
            completed = subprocess.run(
                [sys.executable, "-c", "import server"],
                cwd=SERVER_DIR,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(0, completed.returncode)
        self.assertIn("weak", completed.stderr.lower())

    def test_launchd_pins_loopback_private_umask_and_dedicated_token_path(self):
        with SERVER_PLIST.open("rb") as source:
            job = plistlib.load(source)
        environment = job["EnvironmentVariables"]

        self.assertEqual("127.0.0.1", environment["HOST"])
        self.assertEqual(63, job["Umask"])
        self.assertEqual(
            environment["DATA_DIR"] + "/notify-token.txt",
            environment["XXZF_TOKEN_FILE"],
        )
        self.assertEqual(
            environment["DATA_DIR"] + "/notification_archive",
            environment["XXZF_AUDIT_DIR"],
        )
        self.assertEqual(
            environment["DATA_DIR"] + "/diagnostics",
            environment["XXZF_DIAGNOSTIC_DIR"],
        )


class BackupScriptTests(unittest.TestCase):
    def test_backup_directory_and_files_are_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            backup = root / "backup"
            source.mkdir()
            database = source / "devices.sqlite3"
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("CREATE TABLE sample (value TEXT)")
            config = source / "config.json"
            config.write_text('{"barkEnabled":false}', encoding="utf-8")
            database.chmod(0o644)
            config.chmod(0o644)

            environment = os.environ.copy()
            environment.update({
                "HOME": str(root / "empty-home"),
                "XXZF_SOURCE_DIR": str(source),
                "XXZF_BACKUP_DIR": str(backup),
            })
            subprocess.run(
                ["/bin/zsh", str(BACKUP_SCRIPT)],
                cwd=SERVER_DIR,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )

            snapshots = list(backup.glob("devices-*.sqlite3"))
            self.assertEqual(1, len(snapshots))
            self.assertEqual(0o700, backup.stat().st_mode & 0o777)
            self.assertEqual(0o600, snapshots[0].stat().st_mode & 0o777)
            self.assertFalse((backup / "config.json").exists())


class NotifyTokenProvisioningTests(unittest.TestCase):
    def test_provisions_private_high_entropy_token_without_printing_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private" / "notify-token.txt"
            completed = subprocess.run(
                ["/bin/zsh", str(PROVISION_SCRIPT), str(path)],
                check=True,
                capture_output=True,
                text=True,
            )
            token = path.read_text("utf-8").strip()

            self.assertRegex(token, r"^[a-f0-9]{64}$")
            self.assertEqual(0o700, path.parent.stat().st_mode & 0o777)
            self.assertEqual(0o600, path.stat().st_mode & 0o777)
            self.assertNotIn(token, completed.stdout)
            self.assertNotIn(token, completed.stderr)

            second = subprocess.run(
                ["/bin/zsh", str(PROVISION_SCRIPT), str(path)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(token, path.read_text("utf-8").strip())
            self.assertNotIn(token, second.stdout + second.stderr)

    def test_existing_weak_token_fails_without_printing_or_overwriting_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "notify-token.txt"
            weak = "repeated" * 8
            path.write_text(weak, encoding="utf-8")
            completed = subprocess.run(
                ["/bin/zsh", str(PROVISION_SCRIPT), str(path)],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(0, completed.returncode)
            self.assertEqual(weak, path.read_text("utf-8"))
            self.assertNotIn(weak, completed.stdout + completed.stderr)
            self.assertIn("weak", completed.stderr.lower())


if __name__ == "__main__":
    unittest.main()
