#!/usr/bin/env python3
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from storage_security import ensure_private_directory, ensure_private_file


DEFAULT_MAX_BYTES = 100 * 1024 * 1024
MAX_ENTRIES = 100
MAX_RECORDS = 10_000


def _now_ms():
    return int(time.time() * 1000)


def _text(value, limit):
    return " ".join(str(value or "").replace("\x00", " ").split())[:limit]


def _token(value, limit=48):
    return re.sub(r"[^A-Za-z0-9._+:-]", "_", str(value or ""))[:limit]


def _enum(value, allowed, default="unknown"):
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else default


def _bounded_integer(value, maximum):
    try:
        return max(0, min(int(value or 0), maximum))
    except (TypeError, ValueError):
        return 0


def _bounded_timestamp(value):
    try:
        timestamp = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(timestamp, _now_ms() + 86_400_000))


def _normalized_entry(raw):
    if not isinstance(raw, dict):
        return None
    entry = {
        "at": _bounded_timestamp(raw.get("at")),
        "level": _enum(raw.get("level"), {"info", "warning", "error"}, "info"),
        "code": _token(raw.get("code") or "UNKNOWN", 48).upper() or "UNKNOWN",
    }
    http_status = _bounded_integer(raw.get("httpStatus"), 999)
    if http_status:
        entry["httpStatus"] = http_status
    return entry


def _normalized_entries(raw_entries):
    entries = []
    for raw in (raw_entries or [])[:MAX_ENTRIES]:
        entry = _normalized_entry(raw)
        if entry is not None:
            entries.append(entry)
    return entries


class DiagnosticStore:
    def __init__(self, directory, max_bytes=None):
        self.directory = Path(directory)
        ensure_private_directory(self.directory)
        self.database_path = self.directory / "diagnostics.sqlite3"
        self.max_bytes = int(max_bytes or os.environ.get(
            "XXZF_DIAGNOSTIC_MAX_BYTES", DEFAULT_MAX_BYTES
        ))
        self.target_bytes = max(64 * 1024, int(self.max_bytes * 0.9))
        self.lock = threading.RLock()
        self._harden_storage_permissions()
        self._initialize()
        self._harden_storage_permissions()

    @contextmanager
    def _connect(self):
        self._harden_storage_permissions()
        connection = sqlite3.connect(str(self.database_path), timeout=15)
        try:
            ensure_private_file(self.database_path)
        except Exception:
            connection.close()
            raise
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
            self._harden_storage_permissions()

    def _harden_storage_permissions(self):
        ensure_private_directory(self.directory)
        for path in [
            self.database_path,
            Path(str(self.database_path) + "-journal"),
            Path(str(self.database_path) + "-wal"),
            Path(str(self.database_path) + "-shm"),
        ]:
            ensure_private_file(path, required=False)

    def _initialize(self):
        new_database = not self.database_path.exists()
        with self.lock, self._connect() as connection:
            if new_database:
                connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
            auto_vacuum = int(connection.execute("PRAGMA auto_vacuum").fetchone()[0])
            if auto_vacuum != 2:
                raise RuntimeError(
                    "diagnostic database requires offline auto_vacuum migration; "
                    "stop the service and run scripts/migrate_sqlite_autovacuum.py --apply"
                )
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS diagnostic_uploads (
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    diagnostic_id TEXT NOT NULL UNIQUE,
                    device_id TEXT NOT NULL,
                    device_name TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    role TEXT NOT NULL,
                    app_version TEXT NOT NULL,
                    platform_version TEXT NOT NULL,
                    network_status TEXT NOT NULL,
                    server_status TEXT NOT NULL,
                    paired INTEGER NOT NULL,
                    listener_enabled INTEGER NOT NULL,
                    background_restricted INTEGER NOT NULL,
                    entries_json TEXT NOT NULL,
                    received_at INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS diagnostic_received_idx
                    ON diagnostic_uploads(received_at DESC, row_id DESC);
                CREATE INDEX IF NOT EXISTS diagnostic_device_idx
                    ON diagnostic_uploads(device_id, received_at DESC);
                """
            )

    def record(self, payload, device):
        payload = payload if isinstance(payload, dict) else {}
        device = device if isinstance(device, dict) else {}
        entries = _normalized_entries(payload.get("entries"))

        diagnostic_id = "D-" + secrets.token_hex(6).upper()
        values = (
            diagnostic_id,
            _text(device.get("device_id") or device.get("deviceId"), 96),
            _text(device.get("name") or "未知设备", 160),
            _token(device.get("fingerprint"), 32),
            _token(device.get("platform"), 32).lower(),
            _enum(device.get("role"), {"sender", "receiver"}, "unknown"),
            _token(payload.get("appVersion"), 32),
            _token(payload.get("platformVersion"), 64),
            _enum(payload.get("networkStatus"), {"online", "offline", "unknown"}),
            _enum(
                payload.get("serverStatus"),
                {"online", "unreachable", "auth_failed", "unknown"},
            ),
            1 if payload.get("paired") is True else 0,
            1 if payload.get("listenerEnabled") is True else 0,
            1 if payload.get("backgroundRestricted") is True else 0,
            json.dumps(entries, ensure_ascii=True, separators=(",", ":")),
            _now_ms(),
        )
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO diagnostic_uploads (
                    diagnostic_id, device_id, device_name, fingerprint,
                    platform, role, app_version, platform_version,
                    network_status, server_status, paired, listener_enabled,
                    background_restricted, entries_json, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
        self.enforce_limit()
        return {"diagnosticId": diagnostic_id}

    def query(self, limit=100, device_id=""):
        limit = max(1, min(int(limit or 100), 200))
        device_id = _text(device_id, 96)
        where = "WHERE device_id=?" if device_id else ""
        parameters = (device_id, limit) if device_id else (limit,)
        with self.lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT diagnostic_id, device_id, device_name, fingerprint, platform, role,
                       app_version, platform_version, network_status,
                       server_status, paired, listener_enabled,
                       background_restricted, entries_json, received_at
                FROM diagnostic_uploads
                {where}
                ORDER BY row_id DESC LIMIT ?
                """,
                parameters,
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["entries"] = json.loads(item.pop("entries_json") or "[]")
            item["paired"] = bool(item["paired"])
            item["listener_enabled"] = bool(item["listener_enabled"])
            item["background_restricted"] = bool(item["background_restricted"])
            result.append(item)
        return result

    def device_groups(self):
        with self.lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT device_id, device_name, fingerprint, platform,
                       COUNT(*) AS count, MAX(received_at) AS last_received_at
                FROM diagnostic_uploads
                GROUP BY device_id, device_name, fingerprint, platform
                ORDER BY last_received_at DESC, device_name
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self):
        with self.lock, self._connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM diagnostic_uploads"
            ).fetchone()["count"]
        return {"count": count, "bytes": self._storage_bytes(), "maxBytes": self.max_bytes}

    def _storage_bytes(self):
        total = 0
        for suffix in ("", "-journal", "-wal", "-shm"):
            path = Path(str(self.database_path) + suffix)
            try:
                total += path.stat().st_size
            except FileNotFoundError:
                pass
        return total

    def enforce_limit(self):
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                DELETE FROM diagnostic_uploads WHERE row_id IN (
                    SELECT row_id FROM diagnostic_uploads
                    ORDER BY row_id DESC LIMIT -1 OFFSET ?
                )
                """,
                (MAX_RECORDS,),
            )
            connection.commit()
            while self._storage_bytes() > self.max_bytes:
                deleted = connection.execute(
                    """
                    DELETE FROM diagnostic_uploads WHERE row_id IN (
                        SELECT row_id FROM diagnostic_uploads ORDER BY row_id ASC LIMIT 500
                    )
                    """
                ).rowcount
                connection.commit()
                if deleted <= 0:
                    break
                connection.execute("PRAGMA incremental_vacuum(1000)")
            connection.commit()
