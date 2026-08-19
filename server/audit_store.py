#!/usr/bin/env python3
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from storage_security import (
    atomic_write_private,
    ensure_private_directory,
    ensure_private_file,
)


DEFAULT_MAX_BYTES = 10 * 1024 * 1024 * 1024
MAX_BODY_BYTES = 8 * 1024
MAX_TITLE_BYTES = 1024


def bounded_text(value, max_bytes):
    raw = str(value or "").replace("\x00", "").encode("utf-8", "replace")
    if len(raw) <= max_bytes:
        return raw.decode("utf-8", "replace")
    return raw[:max_bytes].decode("utf-8", "ignore")


def _now_ms():
    return int(time.time() * 1000)


class AuditStore:
    def __init__(self, archive_dir, template_path=None, max_bytes=None):
        self.directory = Path(archive_dir)
        ensure_private_directory(self.directory)
        self.database_path = self.directory / "notifications.sqlite3"
        self.viewer_path = self.directory / "index.html"
        self.max_bytes = int(max_bytes or os.environ.get("XXZF_AUDIT_MAX_BYTES", DEFAULT_MAX_BYTES))
        self.target_bytes = max(64 * 1024, int(self.max_bytes * 0.95))
        self.lock = threading.RLock()
        self._harden_storage_permissions()
        self._initialize()
        if template_path:
            self.install_viewer(template_path)
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
        connection.execute("PRAGMA foreign_keys=ON")
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
            self.viewer_path,
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
                    "audit database requires offline auto_vacuum migration; "
                    "stop the service and run scripts/migrate_sqlite_autovacuum.py --apply"
                )
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    sender_id TEXT,
                    sender_name TEXT NOT NULL,
                    sender_fingerprint TEXT,
                    destinations_json TEXT NOT NULL,
                    package_name TEXT,
                    app_name TEXT NOT NULL,
                    title TEXT,
                    body TEXT,
                    privacy_mode TEXT NOT NULL,
                    post_time INTEGER,
                    received_at INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS notifications_received_idx
                    ON notifications(received_at DESC, row_id DESC);
                CREATE INDEX IF NOT EXISTS notifications_sender_idx
                    ON notifications(sender_id, received_at DESC);
                """
            )

    def install_viewer(self, template_path):
        source = Path(template_path)
        if not source.is_file():
            return
        ensure_private_file(self.viewer_path, required=False)
        if self.viewer_path.exists() and self.viewer_path.read_bytes() == source.read_bytes():
            return
        atomic_write_private(self.viewer_path, source.read_bytes())

    def record(self, event, sender=None, destinations=None, archive_title=None, archive_body=None):
        sender = sender or {}
        destinations = destinations or []
        compact_destinations = []
        for device in destinations[:32]:
            compact_destinations.append({
                "deviceId": bounded_text(device.get("deviceId"), 96),
                "name": bounded_text(device.get("name"), 160),
                "fingerprint": bounded_text(device.get("fingerprint"), 32),
            })

        values = (
            bounded_text(event.get("id"), 256),
            bounded_text(sender.get("device_id") or sender.get("deviceId"), 96),
            bounded_text(sender.get("name") or event.get("device") or "Android", 160),
            bounded_text(sender.get("fingerprint"), 32),
            bounded_text(json.dumps(compact_destinations, ensure_ascii=False, separators=(",", ":")), 4096),
            bounded_text(event.get("packageName"), 256),
            bounded_text(event.get("appName") or event.get("packageName") or "Unknown App", 160),
            bounded_text(archive_title if archive_title is not None else event.get("title"), MAX_TITLE_BYTES),
            bounded_text(archive_body if archive_body is not None else event.get("text"), MAX_BODY_BYTES),
            bounded_text(event.get("privacyMode") or "full", 16),
            int(event.get("postTime") or 0),
            _now_ms(),
        )
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO notifications (
                    event_id, sender_id, sender_name, sender_fingerprint,
                    destinations_json, package_name, app_name, title, body,
                    privacy_mode, post_time, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
        self.enforce_limit()

    @staticmethod
    def _search_filter(search):
        search = bounded_text(search, 256).strip()
        if not search:
            return "", []
        like = f"%{search}%"
        return (
            "(sender_name LIKE ? OR app_name LIKE ? OR title LIKE ? OR body LIKE ?)",
            [like, like, like, like],
        )

    def query(self, limit=100, before=None, search="", offset=0, sender_id=""):
        limit = max(1, min(int(limit or 100), 500))
        offset = max(0, int(offset or 0))
        clauses = []
        values = []
        if before:
            clauses.append("row_id < ?")
            values.append(int(before))
        sender_id = bounded_text(sender_id, 96).strip()
        if sender_id:
            clauses.append("sender_id = ?")
            values.append(sender_id)
        search_clause, search_values = self._search_filter(search)
        if search_clause:
            clauses.append(search_clause)
            values.extend(search_values)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        values.extend([limit, offset])
        with self.lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT row_id, event_id, sender_id, sender_name,
                       sender_fingerprint, destinations_json, package_name,
                       app_name, title, body, privacy_mode, post_time, received_at
                FROM notifications
                """ + where + " ORDER BY row_id DESC LIMIT ? OFFSET ?",
                values,
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["destinations"] = json.loads(item.pop("destinations_json") or "[]")
            result.append(item)
        return result

    def count(self, search="", sender_id=""):
        clauses = []
        values = []
        sender_id = bounded_text(sender_id, 96).strip()
        if sender_id:
            clauses.append("sender_id = ?")
            values.append(sender_id)
        search_clause, search_values = self._search_filter(search)
        if search_clause:
            clauses.append(search_clause)
            values.extend(search_values)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.lock, self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM notifications" + where,
                values,
            ).fetchone()
        return row["count"]

    def device_groups(self, search=""):
        search_clause, values = self._search_filter(search)
        where = (" WHERE " + search_clause) if search_clause else ""
        with self.lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT sender_id, MAX(sender_name) AS sender_name,
                       MAX(sender_fingerprint) AS sender_fingerprint,
                       COUNT(*) AS count, MAX(received_at) AS newest
                FROM notifications
                """ + where + """
                GROUP BY sender_id
                ORDER BY newest DESC
                """,
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self):
        with self.lock, self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count, MIN(received_at) AS oldest, MAX(received_at) AS newest FROM notifications"
            ).fetchone()
        return {
            "count": row["count"],
            "oldest": row["oldest"],
            "newest": row["newest"],
            "bytes": self._storage_bytes(),
            "maxBytes": self.max_bytes,
        }

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
        if self._storage_bytes() <= self.max_bytes:
            return
        with self.lock, self._connect() as connection:
            while self._storage_bytes() > self.target_bytes:
                deleted = connection.execute(
                    """
                    DELETE FROM notifications WHERE row_id IN (
                        SELECT row_id FROM notifications ORDER BY row_id ASC LIMIT 1000
                    )
                    """
                ).rowcount
                connection.commit()
                if deleted <= 0:
                    break
                connection.execute("PRAGMA incremental_vacuum(2000)")
            connection.commit()
