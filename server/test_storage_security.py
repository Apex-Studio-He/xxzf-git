#!/usr/bin/env python3
import importlib.util
import os
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from collections import namedtuple
from contextlib import closing
from pathlib import Path
from unittest import mock

from audit_store import AuditStore
from diagnostic_store import DiagnosticStore
from storage_security import (
    StorageSecurityError,
    atomic_write_private,
    ensure_private_directory,
    ensure_private_file,
)


SERVER_DIR = Path(__file__).resolve().parent
MIGRATION_SCRIPT = SERVER_DIR.parent / "scripts" / "migrate_sqlite_autovacuum.py"
_MIGRATION_SPEC = importlib.util.spec_from_file_location(
    "xxzf_migrate_sqlite_autovacuum", MIGRATION_SCRIPT
)
migration = importlib.util.module_from_spec(_MIGRATION_SPEC)
sys.modules[_MIGRATION_SPEC.name] = migration
_MIGRATION_SPEC.loader.exec_module(migration)


def _create_database(path, auto_vacuum=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(path))) as connection, connection:
        connection.execute(f"PRAGMA auto_vacuum={int(auto_vacuum)}")
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample(value) VALUES ('preserved')")
    path.chmod(0o600)


def _database_mode(path):
    with closing(sqlite3.connect(str(path))) as connection:
        return int(connection.execute("PRAGMA auto_vacuum").fetchone()[0])


class PrivateStorageHelperTests(unittest.TestCase):
    def test_private_directory_and_file_modes_are_repaired_and_verified(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "runtime"
            directory.mkdir(mode=0o755)
            private_file = directory / "secret.json"
            private_file.write_text("{}", encoding="utf-8")
            private_file.chmod(0o644)

            ensure_private_directory(directory)
            ensure_private_file(private_file)

            self.assertEqual(0o700, directory.stat().st_mode & 0o777)
            self.assertEqual(0o600, private_file.stat().st_mode & 0o777)

    def test_directory_and_file_symbolic_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_directory = root / "real"
            real_directory.mkdir()
            directory_link = root / "directory-link"
            directory_link.symlink_to(real_directory, target_is_directory=True)
            real_file = real_directory / "secret"
            real_file.write_text("secret", encoding="utf-8")
            file_link = root / "file-link"
            file_link.symlink_to(real_file)

            with self.assertRaisesRegex(StorageSecurityError, "symbolic link"):
                ensure_private_directory(directory_link)
            with self.assertRaisesRegex(StorageSecurityError, "non-link"):
                ensure_private_file(file_link)

    def test_wrong_owner_is_rejected_before_chmod(self):
        with tempfile.TemporaryDirectory() as temporary:
            private_file = Path(temporary) / "secret"
            private_file.write_text("secret", encoding="utf-8")
            with mock.patch(
                "storage_security._current_uid", return_value=os.geteuid() + 1
            ):
                with self.assertRaisesRegex(StorageSecurityError, "not owned"):
                    ensure_private_file(private_file)

    def test_filesystem_that_ignores_chmod_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            private_file = Path(temporary) / "secret"
            private_file.write_text("secret", encoding="utf-8")
            private_file.chmod(0o644)

            with mock.patch("storage_security.os.fchmod", return_value=None):
                with self.assertRaisesRegex(StorageSecurityError, "cannot enforce mode"):
                    ensure_private_file(private_file)

    def test_directory_filesystem_that_ignores_chmod_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "runtime"
            directory.mkdir(mode=0o755)
            directory.chmod(0o755)

            with mock.patch("storage_security.os.fchmod", return_value=None):
                with self.assertRaisesRegex(StorageSecurityError, "cannot enforce mode"):
                    ensure_private_directory(directory)

    def test_atomic_private_write_rejects_existing_link_and_keeps_target_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "outside"
            target.write_bytes(b"outside")
            link = root / "config.json"
            link.symlink_to(target)

            with self.assertRaises(StorageSecurityError):
                atomic_write_private(link, b"replacement")
            self.assertEqual(b"outside", target.read_bytes())


class StoreAutoVacuumTests(unittest.TestCase):
    def test_audit_store_rejects_legacy_none_auto_vacuum_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "audit"
            database = directory / "notifications.sqlite3"
            _create_database(database, auto_vacuum=0)

            with self.assertRaisesRegex(RuntimeError, "offline auto_vacuum migration"):
                AuditStore(directory)

            self.assertEqual(0, _database_mode(database))

    def test_diagnostic_store_rejects_legacy_full_auto_vacuum_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "diagnostics"
            database = directory / "diagnostics.sqlite3"
            _create_database(database, auto_vacuum=1)

            with self.assertRaisesRegex(RuntimeError, "offline auto_vacuum migration"):
                DiagnosticStore(directory)

            self.assertEqual(1, _database_mode(database))


class AutoVacuumMigrationTests(unittest.TestCase):
    def test_temporary_copy_is_verified_migrated_and_atomically_installed(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "notifications.sqlite3"
            _create_database(database, auto_vacuum=0)

            result = migration.migrate_database(database, apply=True)

            self.assertTrue(result.changed)
            self.assertTrue(result.backup_path.is_file())
            self.assertEqual(2, _database_mode(database))
            self.assertEqual(0, _database_mode(result.backup_path))
            self.assertEqual(0o600, database.stat().st_mode & 0o777)
            self.assertEqual(0o600, result.backup_path.stat().st_mode & 0o777)
            self.assertEqual(0o700, database.parent.stat().st_mode & 0o777)
            with closing(sqlite3.connect(str(database))) as connection:
                self.assertEqual(
                    "preserved",
                    connection.execute("SELECT value FROM sample").fetchone()[0],
                )

    def test_full_auto_vacuum_database_is_migrated_to_incremental(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "diagnostics.sqlite3"
            _create_database(database, auto_vacuum=1)

            result = migration.migrate_database(database, apply=True)

            self.assertTrue(result.changed)
            self.assertEqual(2, _database_mode(database))
            self.assertEqual(1, _database_mode(result.backup_path))

    def test_failed_migration_preserves_original_and_retained_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "diagnostics.sqlite3"
            _create_database(database, auto_vacuum=0)
            original = database.read_bytes()

            with mock.patch.object(
                migration,
                "_migrate_working_copy",
                side_effect=RuntimeError("simulated migration failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "simulated migration failure"):
                    migration.migrate_database(database, apply=True)

            self.assertEqual(original, database.read_bytes())
            backups = list(database.parent.glob(
                "diagnostics.sqlite3.pre-autovacuum-*.bak"
            ))
            self.assertEqual(1, len(backups))
            self.assertEqual(0, _database_mode(backups[0]))
            self.assertEqual([], list(database.parent.glob(".*.autovacuum-*.tmp*")))

    def test_insufficient_space_is_rejected_before_creating_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "notifications.sqlite3"
            _create_database(database, auto_vacuum=0)
            usage = namedtuple("usage", "total used free")

            with self.assertRaisesRegex(RuntimeError, "insufficient free space"):
                migration.migrate_database(
                    database,
                    apply=True,
                    disk_usage=lambda _path: usage(100, 100, 0),
                )

            self.assertEqual(
                [],
                list(database.parent.glob(
                    "notifications.sqlite3.pre-autovacuum-*.bak"
                )),
            )


class ServerRuntimeStorageTests(unittest.TestCase):
    def _server_import(self, root, **overrides):
        data_dir = root / "data"
        data_dir.mkdir(mode=0o700, exist_ok=True)
        token_file = data_dir / "notify-token.txt"
        if not token_file.exists():
            token_file.write_text(secrets.token_urlsafe(32), encoding="utf-8")
            token_file.chmod(0o600)
        environment = os.environ.copy()
        environment.update({
            "DATA_DIR": str(data_dir),
            "XXZF_TOKEN_FILE": str(token_file),
            "XXZF_AUDIT_DIR": str(root / "audit"),
            "XXZF_DIAGNOSTIC_DIR": str(root / "diagnostics"),
            "XXZF_BARK_SECRET_FILE": str(data_dir / "bark-secrets.json"),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        environment.update({key: str(value) for key, value in overrides.items()})
        return subprocess.run(
            [sys.executable, "-c", "import server"],
            cwd=SERVER_DIR,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_server_rejects_symbolic_link_config_and_error_log(self):
        for filename in ("config.json", "server-errors.log"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                data_dir = root / "data"
                data_dir.mkdir(mode=0o700)
                outside = root / "outside"
                outside.write_text("{}", encoding="utf-8")
                (data_dir / filename).symlink_to(outside)

                completed = self._server_import(root)

                self.assertNotEqual(0, completed.returncode)
                self.assertIn("private file", completed.stderr.lower())

    def test_server_rejects_symbolic_link_legacy_token(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "data"
            data_dir.mkdir(mode=0o700)
            outside = root / "outside-token"
            outside.write_text(secrets.token_urlsafe(32), encoding="utf-8")
            outside.chmod(0o600)
            (data_dir / "notify-token.txt").symlink_to(outside)

            completed = self._server_import(root)

            self.assertNotEqual(0, completed.returncode)
            self.assertIn("private file", completed.stderr.lower())


if __name__ == "__main__":
    unittest.main()
