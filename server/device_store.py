#!/usr/bin/env python3
import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from storage_security import ensure_private_directory, ensure_private_file


PAIR_TTL_SECONDS = 5 * 60
PAIR_HISTORY_RETENTION_SECONDS = 7 * 24 * 60 * 60
PAIR_CLAIM_FAILURE_LIMIT = 40
PAIR_CLAIM_FAILURE_WINDOW_SECONDS = 5 * 60
BARK_ENROLL_TTL_SECONDS = 5 * 60


def _now_ms():
    return int(time.time() * 1000)


def _clean(value, limit=80):
    text = " ".join(str(value or "").replace("\x00", " ").split())
    return text[:limit]


def _secret_hash(secret):
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _fingerprint(device_id):
    return hashlib.sha256(device_id.encode("utf-8")).hexdigest()[:10].upper()


class PairingClaimRateLimited(ValueError):
    def __init__(self, retry_after):
        self.retry_after = max(1, int(retry_after))
        super().__init__("pairing claim temporarily locked")


class DeviceStore:
    def __init__(self, database_path):
        self.path = Path(database_path)
        ensure_private_directory(self.path.parent)
        self.lock = threading.RLock()
        self._harden_storage_permissions()
        self._initialize()
        self._harden_storage_permissions()

    def _harden_storage_permissions(self):
        ensure_private_directory(self.path.parent)
        for path in [
            self.path,
            Path(str(self.path) + "-journal"),
            Path(str(self.path) + "-wal"),
            Path(str(self.path) + "-shm"),
        ]:
            ensure_private_file(path, required=False)

    @contextmanager
    def _connect(self):
        self._harden_storage_permissions()
        connection = sqlite3.connect(str(self.path), timeout=10)
        try:
            ensure_private_file(self.path)
        except Exception:
            connection.close()
            raise
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
            self._harden_storage_permissions()

    def _initialize(self):
        with self.lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    role TEXT NOT NULL,
                    secret_hash TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    rate_limit INTEGER NOT NULL DEFAULT 120,
                    created_at INTEGER NOT NULL,
                    last_seen_at INTEGER
                );

                CREATE TABLE IF NOT EXISTS pairings (
                    pairing_id TEXT PRIMARY KEY,
                    code TEXT NOT NULL UNIQUE,
                    receiver_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    claimed_at INTEGER,
                    sender_id TEXT,
                    FOREIGN KEY(receiver_id) REFERENCES devices(device_id),
                    FOREIGN KEY(sender_id) REFERENCES devices(device_id)
                );

                CREATE TABLE IF NOT EXISTS routes (
                    sender_id TEXT NOT NULL,
                    receiver_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY(sender_id, receiver_id),
                    FOREIGN KEY(sender_id) REFERENCES devices(device_id),
                    FOREIGN KEY(receiver_id) REFERENCES devices(device_id)
                );

                CREATE TABLE IF NOT EXISTS bark_enrollments (
                    enrollment_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    code TEXT NOT NULL UNIQUE,
                    sender_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    claimed_at INTEGER,
                    destination_id TEXT,
                    FOREIGN KEY(sender_id) REFERENCES devices(device_id)
                );

                CREATE TABLE IF NOT EXISTS bark_destinations (
                    destination_id TEXT PRIMARY KEY,
                    sender_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    server_url TEXT NOT NULL,
                    key_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at INTEGER NOT NULL,
                    last_success_at INTEGER,
                    last_failure_at INTEGER,
                    FOREIGN KEY(sender_id) REFERENCES devices(device_id)
                );

                CREATE TABLE IF NOT EXISTS pair_claim_budget (
                    scope TEXT PRIMARY KEY,
                    window_started_at INTEGER NOT NULL,
                    failed_attempts INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS pairings_code_idx ON pairings(code);
                CREATE INDEX IF NOT EXISTS routes_sender_idx ON routes(sender_id, active);
                CREATE INDEX IF NOT EXISTS bark_enrollments_token_idx
                    ON bark_enrollments(token_hash);
                CREATE INDEX IF NOT EXISTS bark_enrollments_code_idx
                    ON bark_enrollments(code);
                CREATE INDEX IF NOT EXISTS bark_destinations_sender_idx
                    ON bark_destinations(sender_id, status);
                """
            )

    def _new_device(self, connection, name, platform, role):
        device_id = f"{role[:1]}_{secrets.token_hex(12)}"
        secret = secrets.token_urlsafe(32)
        now = _now_ms()
        connection.execute(
            """
            INSERT INTO devices (
                device_id, name, platform, role, secret_hash, fingerprint,
                status, rate_limit, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'active', 120, ?)
            """,
            (
                device_id,
                _clean(name) or ("Mac 接收端" if role == "receiver" else "Android 手机"),
                _clean(platform, 32) or "unknown",
                role,
                _secret_hash(secret),
                _fingerprint(device_id),
                now,
            ),
        )
        return device_id, secret

    def _new_code(self, connection):
        for _ in range(30):
            code = f"{secrets.randbelow(1_000_000):06d}"
            exists = connection.execute(
                """
                SELECT 1 FROM pairings WHERE code=? AND expires_at>?
                UNION ALL
                SELECT 1 FROM bark_enrollments WHERE code=? AND expires_at>?
                LIMIT 1
                """,
                (code, _now_ms(), code, _now_ms()),
            ).fetchone()
            if not exists:
                return code
        raise RuntimeError("unable to allocate pairing code")

    def _insert_pairing(self, connection, pairing_id, receiver_id, now, expires_at):
        for _ in range(30):
            code = self._new_code(connection)
            try:
                connection.execute(
                    """
                    INSERT INTO pairings (
                        pairing_id, code, receiver_id, created_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (pairing_id, code, receiver_id, now, expires_at),
                )
                return code
            except sqlite3.IntegrityError as exc:
                if "UNIQUE constraint failed: pairings.code" not in str(exc):
                    raise
        raise RuntimeError("unable to allocate pairing code")

    def _insert_bark_enrollment(
        self, connection, enrollment_id, token_hash, sender_id, now, expires_at
    ):
        for _ in range(30):
            code = self._new_code(connection)
            try:
                connection.execute(
                    """
                    INSERT INTO bark_enrollments (
                        enrollment_id, token_hash, code, sender_id, created_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (enrollment_id, token_hash, code, sender_id, now, expires_at),
                )
                return code
            except sqlite3.IntegrityError as exc:
                if "UNIQUE constraint failed: bark_enrollments.code" not in str(exc):
                    raise
        raise RuntimeError("unable to allocate pairing code")

    def purge_expired(self):
        now = _now_ms()
        with self.lock, self._connect() as connection:
            stale_receivers = connection.execute(
                """
                SELECT receiver_id FROM pairings
                WHERE claimed_at IS NULL AND expires_at < ?
                """,
                (now,),
            ).fetchall()
            connection.execute(
                "DELETE FROM pairings WHERE claimed_at IS NULL AND expires_at < ?",
                (now,),
            )
            connection.execute(
                "DELETE FROM pairings WHERE claimed_at IS NOT NULL AND claimed_at < ?",
                (now - PAIR_HISTORY_RETENTION_SECONDS * 1000,),
            )
            connection.execute(
                "DELETE FROM bark_enrollments WHERE claimed_at IS NULL AND expires_at < ?",
                (now,),
            )
            connection.execute(
                "DELETE FROM bark_enrollments WHERE claimed_at IS NOT NULL AND created_at < ?",
                (now - 7 * 24 * 60 * 60 * 1000,),
            )
            for row in stale_receivers:
                connection.execute(
                    """
                    DELETE FROM devices
                    WHERE device_id=? AND role='receiver'
                      AND NOT EXISTS (SELECT 1 FROM routes WHERE receiver_id=devices.device_id)
                      AND NOT EXISTS (
                          SELECT 1 FROM pairings WHERE receiver_id=devices.device_id
                      )
                    """,
                    (row["receiver_id"],),
                )

    def start_pairing(self, receiver_name, platform="macos"):
        self.purge_expired()
        now = _now_ms()
        with self.lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            receiver_id, receiver_secret = self._new_device(
                connection, receiver_name, platform, "receiver"
            )
            pairing_id = f"p_{secrets.token_hex(12)}"
            expires_at = now + PAIR_TTL_SECONDS * 1000
            code = self._insert_pairing(
                connection, pairing_id, receiver_id, now, expires_at
            )
            connection.commit()
        return {
            "pairingId": pairing_id,
            "code": code,
            "expiresAt": expires_at,
            "receiverId": receiver_id,
            "receiverSecret": receiver_secret,
            "receiverFingerprint": _fingerprint(receiver_id),
        }

    def start_pairing_for_receiver(self, receiver_id):
        self.purge_expired()
        now = _now_ms()
        with self.lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            receiver = connection.execute(
                "SELECT * FROM devices WHERE device_id=? AND role='receiver' AND status='active'",
                (str(receiver_id or ""),),
            ).fetchone()
            if receiver is None:
                connection.rollback()
                raise ValueError("接收设备不可用")
            pairing_id = f"p_{secrets.token_hex(12)}"
            expires_at = now + PAIR_TTL_SECONDS * 1000
            code = self._insert_pairing(
                connection, pairing_id, receiver["device_id"], now, expires_at
            )
            connection.commit()
        return {
            "pairingId": pairing_id,
            "code": code,
            "expiresAt": expires_at,
            "receiverId": receiver["device_id"],
            "receiverFingerprint": receiver["fingerprint"],
        }

    def pairing_status(self, receiver_id, pairing_id):
        self.purge_expired()
        with self.lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT pairing_id, receiver_id, sender_id, claimed_at, expires_at
                FROM pairings
                WHERE pairing_id=? AND receiver_id=?
                """,
                (str(pairing_id or ""), str(receiver_id or "")),
            ).fetchone()
        if row is None:
            return None
        return {
            "pairingId": row["pairing_id"],
            "claimed": row["claimed_at"] is not None,
            "expired": row["expires_at"] < _now_ms(),
            "senderId": row["sender_id"] or "",
        }

    def claim_pairing(self, code, sender_name, platform="android"):
        return self._claim_pairing(code, sender_name, platform, sender_id=None)

    def claim_pairing_for_sender(self, code, sender_id):
        return self._claim_pairing(code, "", "", sender_id=str(sender_id or ""))

    def _claim_pairing(self, code, sender_name, platform, sender_id):
        normalized_code = "".join(char for char in str(code or "") if char.isdigit())
        now = _now_ms()
        with self.lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_pair_claim_allowed(connection, now)
            if len(normalized_code) != 6:
                self._reject_pair_claim(connection, now, "配对码应为 6 位数字")
            pairing = connection.execute(
                """
                SELECT pairing_id, receiver_id, expires_at, claimed_at
                FROM pairings WHERE code=?
                """,
                (normalized_code,),
            ).fetchone()
            if pairing is None:
                self._reject_pair_claim(connection, now, "配对码不存在")
            if pairing["claimed_at"] is not None:
                self._reject_pair_claim(connection, now, "配对码已使用")
            if pairing["expires_at"] < now:
                self._reject_pair_claim(connection, now, "配对码已过期")

            receiver = connection.execute(
                "SELECT * FROM devices WHERE device_id=? AND status='active'",
                (pairing["receiver_id"],),
            ).fetchone()
            if receiver is None:
                self._reject_pair_claim(connection, now, "接收设备不可用")

            sender_secret = None
            if sender_id:
                sender = connection.execute(
                    "SELECT * FROM devices WHERE device_id=? AND role='sender' AND status='active'",
                    (sender_id,),
                ).fetchone()
                if sender is None:
                    self._reject_pair_claim(connection, now, "发送设备不可用")
            else:
                sender_id, sender_secret = self._new_device(
                    connection, sender_name, platform, "sender"
                )
            connection.execute(
                """
                INSERT INTO routes (sender_id, receiver_id, created_at, active)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(sender_id, receiver_id)
                DO UPDATE SET active=1, created_at=excluded.created_at
                """,
                (sender_id, receiver["device_id"], now),
            )
            connection.execute(
                """
                UPDATE pairings SET claimed_at=?, sender_id=? WHERE pairing_id=?
                """,
                (now, sender_id, pairing["pairing_id"]),
            )
            connection.commit()

        result = {
            "senderId": sender_id,
            "senderFingerprint": _fingerprint(sender_id),
            "receiver": self._public_device(receiver),
        }
        if sender_secret:
            result["senderSecret"] = sender_secret
        return result

    @staticmethod
    def _pair_claim_budget_state(connection, now):
        row = connection.execute(
            """
            SELECT window_started_at, failed_attempts
            FROM pair_claim_budget WHERE scope='global'
            """
        ).fetchone()
        if row is None:
            return now, 0
        window_ends_at = (
            row["window_started_at"] + PAIR_CLAIM_FAILURE_WINDOW_SECONDS * 1000
        )
        if now >= window_ends_at:
            return now, 0
        return row["window_started_at"], row["failed_attempts"]

    @classmethod
    def _ensure_pair_claim_allowed(cls, connection, now):
        window_started_at, failed_attempts = cls._pair_claim_budget_state(
            connection, now
        )
        if failed_attempts < PAIR_CLAIM_FAILURE_LIMIT:
            return
        remaining_ms = (
            window_started_at + PAIR_CLAIM_FAILURE_WINDOW_SECONDS * 1000 - now
        )
        raise PairingClaimRateLimited(max(1, (remaining_ms + 999) // 1000))

    @classmethod
    def _reject_pair_claim(cls, connection, now, message):
        window_started_at, failed_attempts = cls._pair_claim_budget_state(
            connection, now
        )
        failed_attempts += 1
        connection.execute(
            """
            INSERT INTO pair_claim_budget (
                scope, window_started_at, failed_attempts
            ) VALUES ('global', ?, ?)
            ON CONFLICT(scope) DO UPDATE SET
                window_started_at=excluded.window_started_at,
                failed_attempts=excluded.failed_attempts
            """,
            (window_started_at, failed_attempts),
        )
        connection.commit()
        if failed_attempts >= PAIR_CLAIM_FAILURE_LIMIT:
            remaining_ms = (
                window_started_at + PAIR_CLAIM_FAILURE_WINDOW_SECONDS * 1000 - now
            )
            raise PairingClaimRateLimited(max(1, (remaining_ms + 999) // 1000))
        raise ValueError(message)

    def authenticate(self, device_id, secret, role=None):
        if not device_id or not secret:
            return None
        with self.lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM devices WHERE device_id=? AND status='active'",
                (str(device_id),),
            ).fetchone()
            if row is None or (role and row["role"] != role):
                return None
            if not hmac.compare_digest(row["secret_hash"], _secret_hash(str(secret))):
                return None
            connection.execute(
                "UPDATE devices SET last_seen_at=? WHERE device_id=?",
                (_now_ms(), row["device_id"]),
            )
            return dict(row)

    def destinations_for_sender(self, sender_id):
        with self.lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT d.* FROM routes r
                JOIN devices d ON d.device_id=r.receiver_id
                WHERE r.sender_id=? AND r.active=1 AND d.status='active'
                ORDER BY d.created_at
                """,
                (sender_id,),
            ).fetchall()
            return [self._public_device(row) for row in rows]

    def receiver_has_active_route(self, receiver_id):
        """Return whether an active receiver is paired to an active sender.

        Anonymous pair-start creates a pending receiver credential before a
        sender claims the code.  That credential must not be able to consume
        an event-stream slot until the route is actually established.
        """
        with self.lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM routes r
                JOIN devices receiver ON receiver.device_id=r.receiver_id
                JOIN devices sender ON sender.device_id=r.sender_id
                WHERE r.receiver_id=? AND r.active=1
                  AND receiver.role='receiver' AND receiver.status='active'
                  AND sender.role='sender' AND sender.status='active'
                LIMIT 1
                """,
                (str(receiver_id or ""),),
            ).fetchone()
            return row is not None

    def revoke_sender_route(self, receiver_id, sender_id):
        """Deactivate exactly one sender-to-receiver route.

        Device credentials and pairing history remain intact.  Returning
        ``False`` means the requested active route does not belong to the
        active receiver/sender pair, which keeps repeated and cross-receiver
        requests fail-closed.
        """
        with self.lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE routes SET active=0
                WHERE receiver_id=? AND sender_id=? AND active=1
                  AND EXISTS (
                      SELECT 1 FROM devices receiver
                      WHERE receiver.device_id=routes.receiver_id
                        AND receiver.role='receiver'
                        AND receiver.status='active'
                  )
                  AND EXISTS (
                      SELECT 1 FROM devices sender
                      WHERE sender.device_id=routes.sender_id
                        AND sender.role='sender'
                        AND sender.status='active'
                  )
                """,
                (str(receiver_id or ""), str(sender_id or "")),
            )
            return cursor.rowcount == 1

    def start_bark_enrollment(self, sender_id):
        self.purge_expired()
        now = _now_ms()
        token = secrets.token_urlsafe(32)
        with self.lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            sender = connection.execute(
                "SELECT 1 FROM devices WHERE device_id=? AND role='sender' AND status='active'",
                (str(sender_id or ""),),
            ).fetchone()
            if sender is None:
                connection.rollback()
                raise ValueError("发送设备不可用")
            enrollment_id = f"be_{secrets.token_hex(12)}"
            expires_at = now + BARK_ENROLL_TTL_SECONDS * 1000
            code = self._insert_bark_enrollment(
                connection,
                enrollment_id,
                _secret_hash(token),
                str(sender_id),
                now,
                expires_at,
            )
            connection.commit()
        return {
            "enrollmentId": enrollment_id,
            "token": token,
            "code": code,
            "expiresAt": expires_at,
        }

    def claim_bark_enrollment(
        self, token=None, code=None, name="iPhone", server_url="https://api.day.app",
        key_fingerprint="",
    ):
        where, value = self._bark_enrollment_selector(token, code)

        now = _now_ms()
        with self.lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            enrollment = self._checked_bark_enrollment(connection, where, value, now)

            destination_id = f"b_{secrets.token_hex(12)}"
            connection.execute(
                """
                INSERT INTO bark_destinations (
                    destination_id, sender_id, name, server_url, key_fingerprint,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    destination_id,
                    enrollment["sender_id"],
                    _clean(name) or "iPhone",
                    _clean(server_url, 512),
                    _clean(key_fingerprint, 32),
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE bark_enrollments
                SET claimed_at=?, destination_id=?
                WHERE enrollment_id=? AND claimed_at IS NULL
                """,
                (now, destination_id, enrollment["enrollment_id"]),
            )
            row = connection.execute(
                "SELECT * FROM bark_destinations WHERE destination_id=?",
                (destination_id,),
            ).fetchone()
            connection.commit()
        return self._public_bark_destination(row)

    def validate_bark_enrollment(self, token=None, code=None):
        where, value = self._bark_enrollment_selector(token, code)
        with self.lock, self._connect() as connection:
            row = self._checked_bark_enrollment(connection, where, value, _now_ms())
            return {
                "enrollmentId": row["enrollment_id"],
                "senderId": row["sender_id"],
                "expiresAt": row["expires_at"],
            }

    @staticmethod
    def _bark_enrollment_selector(token, code):
        raw_token = str(token or "").strip()
        normalized_code = "".join(char for char in str(code or "") if char.isdigit())
        if raw_token:
            if len(raw_token) < 32 or len(raw_token) > 256:
                raise ValueError("绑定凭证无效")
            return "token_hash=?", _secret_hash(raw_token)
        if len(normalized_code) != 6:
            raise ValueError("绑定码应为 6 位数字")
        return "code=?", normalized_code

    @staticmethod
    def _checked_bark_enrollment(connection, where, value, now):
        enrollment = connection.execute(
            f"SELECT * FROM bark_enrollments WHERE {where}",
            (value,),
        ).fetchone()
        if enrollment is None:
            raise ValueError("绑定凭证不存在")
        if enrollment["claimed_at"] is not None:
            raise ValueError("绑定凭证已使用")
        if enrollment["expires_at"] < now:
            raise ValueError("绑定凭证已过期")
        sender = connection.execute(
            "SELECT 1 FROM devices WHERE device_id=? AND role='sender' AND status='active'",
            (enrollment["sender_id"],),
        ).fetchone()
        if sender is None:
            raise ValueError("发送设备不可用")
        return enrollment

    def bark_destinations_for_sender(self, sender_id):
        with self.lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM bark_destinations
                WHERE sender_id=? AND status='active'
                ORDER BY created_at
                """,
                (str(sender_id or ""),),
            ).fetchall()
            return [self._public_bark_destination(row) for row in rows]

    def bark_destination_for_sender(self, sender_id, destination_id):
        with self.lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM bark_destinations
                WHERE sender_id=? AND destination_id=? AND status='active'
                """,
                (str(sender_id or ""), str(destination_id or "")),
            ).fetchone()
            return self._public_bark_destination(row) if row is not None else None

    def revoke_bark_destination_with_secrets(self, sender_id, destination_id):
        """Revoke one Bark destination and return secret IDs to erase.

        The database transition is atomic.  Secret-file cleanup deliberately
        happens after this transaction in the service layer: a cleanup error
        therefore leaves a safe, unusable revoked destination which startup
        reconciliation can finish, rather than an active route without its
        credential.
        """
        with self.lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT destination_id FROM bark_destinations
                WHERE sender_id=? AND destination_id=? AND status='active'
                """,
                (str(sender_id or ""), str(destination_id or "")),
            ).fetchone()
            if row is None:
                connection.rollback()
                return []
            cursor = connection.execute(
                """
                UPDATE bark_destinations SET status='revoked'
                WHERE sender_id=? AND destination_id=? AND status='active'
                """,
                (str(sender_id or ""), str(destination_id or "")),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return []
            connection.commit()
            return [row["destination_id"]]

    def revoke_bark_destination(self, sender_id, destination_id):
        return bool(
            self.revoke_bark_destination_with_secrets(sender_id, destination_id)
        )

    def revoked_bark_destination_ids(self):
        """Return only IDs whose secret must no longer exist."""
        with self.lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT destination_id FROM bark_destinations
                WHERE status='revoked'
                ORDER BY destination_id
                """
            ).fetchall()
            return [row["destination_id"] for row in rows]

    def mark_bark_delivery(self, destination_id, success):
        column = "last_success_at" if success else "last_failure_at"
        with self.lock, self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE bark_destinations SET {column}=? WHERE destination_id=? AND status='active'",
                (_now_ms(), str(destination_id or "")),
            )
            return cursor.rowcount > 0

    def list_devices(self):
        self.purge_expired()
        with self.lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT d.*,
                    (SELECT COUNT(*) FROM routes r
                     WHERE (r.sender_id=d.device_id OR r.receiver_id=d.device_id)
                       AND r.active=1)
                    + (SELECT COUNT(*) FROM bark_destinations b
                       WHERE b.sender_id=d.device_id AND b.status='active') AS route_count
                FROM devices d ORDER BY d.created_at DESC
                """
            ).fetchall()
            return [self._public_device(row, include_status=True) for row in rows]

    def update_rate_limit(self, device_id, rate_limit):
        value = max(10, min(int(rate_limit), 600))
        with self.lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE devices SET rate_limit=? WHERE device_id=? AND status='active'",
                (value, str(device_id)),
            )
            return cursor.rowcount > 0, value

    def revoke_with_secrets(self, device_id):
        """Atomically revoke a device and return Bark secret IDs to erase.

        ``None`` means there was no active device.  An empty list is a
        successful revocation which had no Bark credentials.
        """
        with self.lock, self._connect() as connection:
            normalized_id = str(device_id or "")
            connection.execute("BEGIN IMMEDIATE")
            device = connection.execute(
                """
                SELECT device_id, role FROM devices
                WHERE device_id=? AND status='active'
                """,
                (normalized_id,),
            ).fetchone()
            if device is None:
                connection.rollback()
                return None
            destination_rows = connection.execute(
                """
                SELECT destination_id FROM bark_destinations
                WHERE sender_id=? AND status='active'
                ORDER BY destination_id
                """,
                (normalized_id,),
            ).fetchall()
            cursor = connection.execute(
                """
                UPDATE devices SET status='revoked'
                WHERE device_id=? AND status='active'
                """,
                (normalized_id,),
            )
            connection.execute(
                "UPDATE routes SET active=0 WHERE sender_id=? OR receiver_id=?",
                (normalized_id, normalized_id),
            )
            connection.execute(
                "UPDATE bark_destinations SET status='revoked' WHERE sender_id=?",
                (normalized_id,),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return None
            connection.commit()
            return [row["destination_id"] for row in destination_rows]

    def revoke(self, device_id):
        return self.revoke_with_secrets(device_id) is not None

    @staticmethod
    def _public_device(row, include_status=False):
        data = {
            "deviceId": row["device_id"],
            "name": row["name"],
            "platform": row["platform"],
            "role": row["role"],
            "fingerprint": row["fingerprint"],
            "createdAt": row["created_at"],
            "lastSeenAt": row["last_seen_at"],
        }
        if include_status:
            data["status"] = row["status"]
            data["rateLimit"] = row["rate_limit"]
            if "route_count" in row.keys():
                data["routeCount"] = row["route_count"]
        return data

    @staticmethod
    def _public_bark_destination(row):
        return {
            "destinationId": row["destination_id"],
            "deviceId": row["destination_id"],
            "senderId": row["sender_id"],
            "name": row["name"],
            "platform": "ios",
            "role": "receiver",
            "type": "bark",
            "fingerprint": row["key_fingerprint"],
            "serverUrl": row["server_url"],
            "createdAt": row["created_at"],
            "lastSuccessAt": row["last_success_at"],
            "lastFailureAt": row["last_failure_at"],
        }
