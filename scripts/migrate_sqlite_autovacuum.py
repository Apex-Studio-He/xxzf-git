#!/usr/bin/env python3
"""Offline, backup-first migration to SQLite INCREMENTAL auto-vacuum.

The XXZF service must be stopped before this tool is run.  Migration happens
on a private temporary copy and is atomically installed only after a second
integrity check.  The pre-migration backup is intentionally retained on both
success and failure.
"""

import argparse
import os
import secrets
import shutil
import sqlite3
import sys
import time
import urllib.parse
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


os.umask(0o077)


SERVER_DIR = Path(__file__).resolve().parent.parent / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from storage_security import (  # noqa: E402
    ensure_private_directory,
    ensure_private_file,
    secure_private_file_descriptor,
)


SAFETY_MARGIN_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class MigrationResult:
    changed: bool
    backup_path: object = None


def _readonly_uri(path):
    encoded = urllib.parse.quote(str(Path(path).resolve()), safe="/")
    return f"file:{encoded}?mode=ro"


def _database_checks(path):
    with closing(
        sqlite3.connect(_readonly_uri(path), uri=True, timeout=5)
    ) as connection:
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        auto_vacuum = int(connection.execute("PRAGMA auto_vacuum").fetchone()[0])
    if integrity != ["ok"]:
        raise RuntimeError("SQLite integrity_check failed")
    return auto_vacuum


def _refuse_live_sidecars(path):
    present = [
        candidate.name
        for candidate in (
            Path(str(path) + "-journal"),
            Path(str(path) + "-wal"),
            Path(str(path) + "-shm"),
        )
        if candidate.exists() or candidate.is_symlink()
    ]
    if present:
        raise RuntimeError(
            "SQLite sidecar files are present; stop the service and checkpoint/close the database"
        )


def _copy_private(source, destination):
    source = Path(source)
    destination = Path(destination)
    ensure_private_file(source)
    ensure_private_directory(destination.parent)
    source_descriptor = os.open(
        source,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    destination_descriptor = None
    try:
        destination_descriptor = os.open(
            destination,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        secure_private_file_descriptor(destination_descriptor, destination)
        while True:
            chunk = os.read(source_descriptor, 1024 * 1024)
            if not chunk:
                break
            view = memoryview(chunk)
            while view:
                written = os.write(destination_descriptor, view)
                if written <= 0:  # pragma: no cover - defensive POSIX guard
                    raise OSError("short write while copying SQLite database")
                view = view[written:]
        os.fsync(destination_descriptor)
    except Exception:
        if destination_descriptor is not None:
            os.close(destination_descriptor)
            destination_descriptor = None
        try:
            destination.unlink()
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(source_descriptor)
        if destination_descriptor is not None:
            os.close(destination_descriptor)
    ensure_private_file(destination)


def _migrate_working_copy(path):
    path = Path(path)
    ensure_private_file(path)
    connection = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    try:
        before = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        if before != ["ok"]:
            raise RuntimeError("working-copy integrity_check failed before migration")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
        connection.execute("VACUUM")
        auto_vacuum = int(connection.execute("PRAGMA auto_vacuum").fetchone()[0])
        after = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        if auto_vacuum != 2:
            raise RuntimeError("SQLite did not enable INCREMENTAL auto_vacuum")
        if after != ["ok"]:
            raise RuntimeError("working-copy integrity_check failed after migration")
    finally:
        connection.close()
    ensure_private_file(path)
    _refuse_live_sidecars(path)


def _fsync_directory(path):
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _database_identity(path):
    status = os.lstat(path)
    return (
        status.st_dev,
        status.st_ino,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def migrate_database(database_path, *, apply=False, disk_usage=shutil.disk_usage):
    """Migrate a stopped SQLite database, returning its retained backup path."""

    if not apply:
        raise RuntimeError("migration requires explicit apply=True")
    database_path = Path(database_path).expanduser()
    ensure_private_directory(database_path.parent)
    ensure_private_file(database_path)
    _refuse_live_sidecars(database_path)
    original_identity = _database_identity(database_path)
    auto_vacuum = _database_checks(database_path)
    if auto_vacuum == 2:
        return MigrationResult(changed=False)
    if auto_vacuum not in (0, 1):
        raise RuntimeError("unsupported SQLite auto_vacuum mode")

    database_bytes = database_path.stat().st_size
    required_free = database_bytes * 3 + SAFETY_MARGIN_BYTES
    available = disk_usage(database_path.parent).free
    if available < required_free:
        raise RuntimeError(
            f"insufficient free space: need at least {required_free} bytes for safe migration"
        )

    stamp = time.strftime("%Y%m%d-%H%M%S")
    nonce = secrets.token_hex(4)
    backup_path = database_path.with_name(
        f"{database_path.name}.pre-autovacuum-{stamp}-{nonce}.bak"
    )
    working_path = database_path.with_name(
        f".{database_path.name}.autovacuum-{os.getpid()}-{nonce}.tmp"
    )

    _copy_private(database_path, backup_path)
    try:
        if _database_checks(backup_path) != auto_vacuum:
            raise RuntimeError("pre-migration backup does not match database settings")
        _copy_private(backup_path, working_path)
        _migrate_working_copy(working_path)
        if _database_checks(working_path) != 2:
            raise RuntimeError("migrated copy failed final auto_vacuum verification")
        _refuse_live_sidecars(database_path)
        if _database_identity(database_path) != original_identity:
            raise RuntimeError(
                "source database changed during migration; keep the backup and retry offline"
            )
        os.replace(working_path, database_path)
        ensure_private_file(database_path)
        _fsync_directory(database_path.parent)
    except Exception:
        for candidate in (
            working_path,
            Path(str(working_path) + "-journal"),
            Path(str(working_path) + "-wal"),
            Path(str(working_path) + "-shm"),
        ):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
        raise

    return MigrationResult(changed=True, backup_path=backup_path)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Offline migration of an XXZF SQLite database to INCREMENTAL auto-vacuum"
    )
    parser.add_argument("database", type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="confirm that the XXZF service is stopped and perform the migration",
    )
    args = parser.parse_args(argv)

    database = args.database.expanduser()
    if not args.apply:
        ensure_private_directory(database.parent)
        ensure_private_file(database)
        _refuse_live_sidecars(database)
        mode = _database_checks(database)
        print(f"database integrity is valid; auto_vacuum mode={mode}")
        print("no changes made; stop XXZF and add --apply to migrate")
        return 0

    result = migrate_database(database, apply=True)
    if not result.changed:
        print("database already uses INCREMENTAL auto_vacuum; no changes made")
    else:
        print(f"migration complete; retained backup: {result.backup_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"migration failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
