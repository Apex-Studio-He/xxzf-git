#!/usr/bin/env python3
import tempfile
import threading
import unittest
import sqlite3
from contextlib import closing
from unittest import mock
from pathlib import Path

import device_store
from audit_store import AuditStore, MAX_BODY_BYTES
from device_store import DeviceStore, PAIR_TTL_SECONDS
from diagnostic_store import DiagnosticStore


class DeviceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "devices.sqlite3"
        self.store = DeviceStore(self.database)

    def tearDown(self):
        self.temporary.cleanup()

    def test_every_managed_connection_is_closed(self):
        actual_connect = sqlite3.connect
        connections = []

        class TrackedConnection(sqlite3.Connection):
            was_closed = False

            def close(self):
                self.was_closed = True
                return super().close()

        def tracked_connect(*args, **kwargs):
            kwargs["factory"] = TrackedConnection
            connection = actual_connect(*args, **kwargs)
            connections.append(connection)
            return connection

        database = Path(self.temporary.name) / "tracked.sqlite3"
        with mock.patch("device_store.sqlite3.connect", side_effect=tracked_connect):
            store = DeviceStore(database)
            pairing = store.start_pairing("Air", "macos")
            store.claim_pairing(pairing["code"], "测试手机", "android")
            store.list_devices()

        self.assertGreaterEqual(len(connections), 4)
        self.assertTrue(all(connection.was_closed for connection in connections))

    def test_pair_authenticate_route_and_revoke(self):
        pairing = self.store.start_pairing("Air", "macos")
        self.assertFalse(
            self.store.receiver_has_active_route(pairing["receiverId"])
        )
        self.assertRegex(pairing["code"], r"^\d{6}$")
        receiver = self.store.authenticate(
            pairing["receiverId"], pairing["receiverSecret"], "receiver"
        )
        self.assertIsNotNone(receiver)

        claimed = self.store.claim_pairing(pairing["code"], "测试手机", "android")
        sender = self.store.authenticate(
            claimed["senderId"], claimed["senderSecret"], "sender"
        )
        self.assertIsNotNone(sender)
        destinations = self.store.destinations_for_sender(claimed["senderId"])
        self.assertEqual([pairing["receiverId"]], [item["deviceId"] for item in destinations])
        self.assertTrue(
            self.store.receiver_has_active_route(pairing["receiverId"])
        )

        updated, value = self.store.update_rate_limit(claimed["senderId"], 75)
        self.assertTrue(updated)
        self.assertEqual(75, value)
        self.assertEqual(75, self.store.authenticate(
            claimed["senderId"], claimed["senderSecret"], "sender"
        )["rate_limit"])

        with self.assertRaisesRegex(ValueError, "已使用"):
            self.store.claim_pairing(pairing["code"], "另一台手机", "android")

        windows_pairing = self.store.start_pairing("Windows", "windows")
        attached = self.store.claim_pairing_for_sender(
            windows_pairing["code"], claimed["senderId"]
        )
        self.assertNotIn("senderSecret", attached)
        destinations = self.store.destinations_for_sender(claimed["senderId"])
        self.assertEqual(
            [pairing["receiverId"], windows_pairing["receiverId"]],
            [item["deviceId"] for item in destinations],
        )
        self.assertEqual(
            1,
            len([item for item in self.store.list_devices() if item["role"] == "sender"]),
        )

        another_code = self.store.start_pairing_for_receiver(pairing["receiverId"])
        self.assertEqual(pairing["receiverId"], another_code["receiverId"])
        self.assertNotIn("receiverSecret", another_code)
        pending = self.store.pairing_status(
            pairing["receiverId"], another_code["pairingId"]
        )
        self.assertFalse(pending["claimed"])
        self.assertIsNone(self.store.pairing_status(
            windows_pairing["receiverId"], another_code["pairingId"]
        ))
        second_sender = self.store.claim_pairing(another_code["code"], "第二台手机", "android")
        self.assertTrue(self.store.pairing_status(
            pairing["receiverId"], another_code["pairingId"]
        )["claimed"])
        self.assertEqual(
            [pairing["receiverId"]],
            [item["deviceId"] for item in self.store.destinations_for_sender(second_sender["senderId"])],
        )

        raw_database = self.database.read_bytes()
        self.assertNotIn(pairing["receiverSecret"].encode(), raw_database)
        self.assertNotIn(claimed["senderSecret"].encode(), raw_database)

        self.assertTrue(self.store.revoke(claimed["senderId"]))
        self.assertIsNone(
            self.store.authenticate(claimed["senderId"], claimed["senderSecret"], "sender")
        )
        self.assertEqual([], self.store.destinations_for_sender(claimed["senderId"]))
        self.assertFalse(
            self.store.receiver_has_active_route(windows_pairing["receiverId"])
        )
        self.assertTrue(self.store.receiver_has_active_route(pairing["receiverId"]))

    def test_receiver_can_revoke_only_one_sender_route(self):
        primary_receiver = self.store.start_pairing("主接收端", "android")
        first_sender = self.store.claim_pairing(
            primary_receiver["code"], "发送设备一", "android"
        )

        secondary_receiver = self.store.start_pairing("另一个接收端", "macos")
        self.store.claim_pairing_for_sender(
            secondary_receiver["code"], first_sender["senderId"]
        )

        second_code = self.store.start_pairing_for_receiver(
            primary_receiver["receiverId"]
        )
        second_sender = self.store.claim_pairing(
            second_code["code"], "发送设备二", "android"
        )

        self.assertTrue(
            self.store.revoke_sender_route(
                primary_receiver["receiverId"], first_sender["senderId"]
            )
        )

        reopened = DeviceStore(self.database)
        self.assertEqual(
            [],
            [
                item["deviceId"]
                for item in reopened.destinations_for_sender(first_sender["senderId"])
                if item["deviceId"] == primary_receiver["receiverId"]
            ],
        )
        self.assertEqual(
            [secondary_receiver["receiverId"]],
            [
                item["deviceId"]
                for item in reopened.destinations_for_sender(first_sender["senderId"])
            ],
        )
        self.assertEqual(
            [primary_receiver["receiverId"]],
            [
                item["deviceId"]
                for item in reopened.destinations_for_sender(second_sender["senderId"])
            ],
        )
        self.assertTrue(reopened.receiver_has_active_route(primary_receiver["receiverId"]))
        self.assertTrue(reopened.receiver_has_active_route(secondary_receiver["receiverId"]))
        self.assertIsNotNone(reopened.authenticate(
            primary_receiver["receiverId"],
            primary_receiver["receiverSecret"],
            "receiver",
        ))
        self.assertIsNotNone(reopened.authenticate(
            secondary_receiver["receiverId"],
            secondary_receiver["receiverSecret"],
            "receiver",
        ))
        self.assertIsNotNone(reopened.authenticate(
            first_sender["senderId"], first_sender["senderSecret"], "sender"
        ))
        self.assertIsNotNone(reopened.authenticate(
            second_sender["senderId"], second_sender["senderSecret"], "sender"
        ))
        self.assertTrue(reopened.pairing_status(
            primary_receiver["receiverId"], primary_receiver["pairingId"]
        )["claimed"])
        self.assertTrue(reopened.pairing_status(
            primary_receiver["receiverId"], second_code["pairingId"]
        )["claimed"])
        self.assertFalse(reopened.revoke_sender_route(
            primary_receiver["receiverId"], first_sender["senderId"]
        ))

    def test_storage_and_sqlite_sidecars_are_private(self):
        directory = self.database.parent
        sidecars = [
            Path(str(self.database) + suffix)
            for suffix in ("-journal", "-wal", "-shm")
        ]
        directory.chmod(0o755)
        self.database.chmod(0o644)
        for sidecar in sidecars:
            sidecar.touch()
            sidecar.chmod(0o644)

        reopened = DeviceStore(self.database)
        reopened.list_devices()

        self.assertEqual(0o700, directory.stat().st_mode & 0o777)
        self.assertEqual(0o600, self.database.stat().st_mode & 0o777)
        for sidecar in sidecars:
            if sidecar.exists():
                self.assertEqual(0o600, sidecar.stat().st_mode & 0o777)

    def test_bad_pairing_code_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "6 位"):
            self.store.claim_pairing("12AB", "手机")
        with self.assertRaisesRegex(ValueError, "不存在"):
            self.store.claim_pairing("123456", "手机")

    def test_expiring_an_old_code_keeps_a_new_code_for_the_same_receiver(self):
        started_at = 1_000
        with mock.patch("device_store.time.time", return_value=started_at):
            first = self.store.start_pairing("测试电脑", "macos")
        with mock.patch(
            "device_store.time.time",
            return_value=started_at + PAIR_TTL_SECONDS - 60,
        ):
            second = self.store.start_pairing_for_receiver(first["receiverId"])
        with mock.patch(
            "device_store.time.time",
            return_value=started_at + PAIR_TTL_SECONDS + 1,
        ):
            status = self.store.pairing_status(
                first["receiverId"], second["pairingId"]
            )

        self.assertIsNotNone(status)
        self.assertFalse(status["claimed"])
        self.assertFalse(status["expired"])

    def test_claimed_pairing_history_expires_after_seven_days(self):
        started_at = 2_000
        with mock.patch("device_store.time.time", return_value=started_at):
            pairing = self.store.start_pairing("测试电脑", "macos")
            self.store.claim_pairing(pairing["code"], "测试手机", "android")
        with mock.patch(
            "device_store.time.time",
            return_value=started_at + 7 * 24 * 60 * 60 + 1,
        ):
            status = self.store.pairing_status(
                pairing["receiverId"], pairing["pairingId"]
            )

        self.assertIsNone(status)

    def test_historical_code_collision_is_retried(self):
        started_at = 3_000
        with mock.patch("device_store.time.time", return_value=started_at):
            historical = self.store.start_pairing("旧电脑", "macos")
            self.store.claim_pairing(historical["code"], "测试手机", "android")
        old_value = int(historical["code"])
        new_value = (old_value + 1) % 1_000_000

        with mock.patch(
            "device_store.time.time",
            return_value=started_at + PAIR_TTL_SECONDS + 1,
        ), mock.patch(
            "device_store.secrets.randbelow",
            side_effect=[old_value, new_value],
        ):
            fresh = self.store.start_pairing("新电脑", "macos")

        self.assertEqual(f"{new_value:06d}", fresh["code"])

    def test_global_claim_failure_budget_survives_store_restart(self):
        with mock.patch("device_store.time.time", return_value=5_000):
            pairing = self.store.start_pairing("测试电脑", "macos")
            failures = 0
            candidate = 0
            while failures < 40:
                code = f"{candidate:06d}"
                candidate += 1
                if code == pairing["code"]:
                    continue
                try:
                    self.store.claim_pairing(code, "攻击者", "android")
                except ValueError:
                    failures += 1

            restarted = DeviceStore(self.database)
            with self.assertRaises(device_store.PairingClaimRateLimited):
                restarted.claim_pairing(pairing["code"], "合法手机", "android")

    def test_global_claim_failure_budget_recovers_after_five_minutes(self):
        started_at = 6_000
        with mock.patch("device_store.time.time", return_value=started_at):
            failures = 0
            candidate = 100
            while failures < 40:
                code = f"{candidate:06d}"
                candidate += 1
                try:
                    self.store.claim_pairing(code, "攻击者", "android")
                except ValueError:
                    failures += 1

        with mock.patch(
            "device_store.time.time", return_value=started_at + 5 * 60 + 1
        ):
            restarted = DeviceStore(self.database)
            pairing = restarted.start_pairing("测试电脑", "macos")
            claimed = restarted.claim_pairing(
                pairing["code"], "合法手机", "android"
            )

        self.assertEqual(pairing["receiverId"], claimed["receiver"]["deviceId"])

    def test_successful_claim_does_not_clear_global_attack_history(self):
        with mock.patch("device_store.time.time", return_value=7_000):
            first = self.store.start_pairing("第一台电脑", "macos")
            second = self.store.start_pairing("第二台电脑", "macos")
            valid_codes = {first["code"], second["code"]}
            failures = 0
            candidate = 200
            while failures < 39:
                code = f"{candidate:06d}"
                candidate += 1
                if code in valid_codes:
                    continue
                with self.assertRaises(ValueError):
                    self.store.claim_pairing(code, "攻击者", "android")
                failures += 1

            self.store.claim_pairing(first["code"], "合法手机", "android")
            with self.assertRaises(device_store.PairingClaimRateLimited):
                self.store.claim_pairing(f"{candidate:06d}", "攻击者", "android")
            with self.assertRaises(device_store.PairingClaimRateLimited):
                self.store.claim_pairing(second["code"], "另一台合法手机", "android")

    def test_concurrent_success_and_failure_update_budget_atomically(self):
        with mock.patch("device_store.time.time", return_value=8_000):
            successful_pairing = self.store.start_pairing("第一台电脑", "macos")
            later_pairing = self.store.start_pairing("第二台电脑", "macos")
            locked_pairing = self.store.start_pairing("第三台电脑", "macos")
            other_store = DeviceStore(self.database)
            barrier = threading.Barrier(3)
            outcomes = []
            outcome_lock = threading.Lock()

            def claim_valid():
                barrier.wait()
                try:
                    self.store.claim_pairing(
                        successful_pairing["code"], "合法手机", "android"
                    )
                    outcome = "success"
                except Exception as exc:
                    outcome = exc.__class__.__name__
                with outcome_lock:
                    outcomes.append(outcome)

            def claim_invalid():
                barrier.wait()
                try:
                    other_store.claim_pairing("900001", "攻击者", "android")
                    outcome = "unexpected-success"
                except Exception as exc:
                    outcome = exc.__class__.__name__
                with outcome_lock:
                    outcomes.append(outcome)

            threads = [
                threading.Thread(target=claim_valid),
                threading.Thread(target=claim_invalid),
            ]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join()

            self.assertEqual(["ValueError", "success"], sorted(outcomes))
            valid_codes = {
                successful_pairing["code"],
                later_pairing["code"],
                locked_pairing["code"],
            }
            failures = 0
            candidate = 900002
            while failures < 38:
                code = f"{candidate:06d}"
                candidate += 1
                if code in valid_codes:
                    continue
                with self.assertRaises(ValueError):
                    self.store.claim_pairing(code, "攻击者", "android")
                failures += 1

            self.store.claim_pairing(later_pairing["code"], "第二台手机", "android")
            with self.assertRaises(device_store.PairingClaimRateLimited):
                self.store.claim_pairing(f"{candidate:06d}", "攻击者", "android")
            with self.assertRaises(device_store.PairingClaimRateLimited):
                self.store.claim_pairing(
                    locked_pairing["code"], "第三台手机", "android"
                )

    def test_existing_database_is_migrated_without_losing_devices(self):
        pairing = self.store.start_pairing("旧电脑", "macos")
        sender = self.store.claim_pairing(pairing["code"], "旧手机", "android")
        with closing(sqlite3.connect(str(self.database))) as connection, connection:
            connection.execute("DROP TABLE pair_claim_budget")

        migrated = DeviceStore(self.database)
        authenticated = migrated.authenticate(
            sender["senderId"], sender["senderSecret"], "sender"
        )
        self.assertIsNotNone(authenticated)
        with self.assertRaises(ValueError):
            migrated.claim_pairing("999998", "攻击者", "android")
        fresh = migrated.start_pairing("新电脑", "macos")
        claimed = migrated.claim_pairing(fresh["code"], "新手机", "android")
        self.assertEqual(fresh["receiverId"], claimed["receiver"]["deviceId"])

    def _new_sender(self, name="测试手机"):
        pairing = self.store.start_pairing("测试电脑", "macos")
        return self.store.claim_pairing(pairing["code"], name, "android")

    def test_bark_enrollment_is_single_use_and_scoped_to_sender(self):
        first = self._new_sender("第一台手机")
        second = self._new_sender("第二台手机")

        enrollment = self.store.start_bark_enrollment(first["senderId"])
        self.assertRegex(enrollment["code"], r"^\d{6}$")
        self.assertGreaterEqual(len(enrollment["token"]), 32)
        self.assertNotIn(enrollment["token"].encode(), self.database.read_bytes())

        destination = self.store.claim_bark_enrollment(
            token=enrollment["token"],
            name="我的 iPhone",
            server_url="https://api.day.app",
            key_fingerprint="A1B2C3D4E5",
        )
        self.assertEqual(first["senderId"], destination["senderId"])
        self.assertEqual("ios", destination["platform"])
        self.assertEqual("bark", destination["type"])
        self.assertNotIn("key", destination)

        listed = self.store.bark_destinations_for_sender(first["senderId"])
        self.assertEqual([destination["destinationId"]], [item["destinationId"] for item in listed])
        self.assertEqual([], self.store.bark_destinations_for_sender(second["senderId"]))
        self.assertFalse(self.store.revoke_bark_destination(
            second["senderId"], destination["destinationId"]
        ))
        self.assertTrue(self.store.revoke_bark_destination(
            first["senderId"], destination["destinationId"]
        ))
        self.assertEqual([], self.store.bark_destinations_for_sender(first["senderId"]))

        with self.assertRaisesRegex(ValueError, "已使用"):
            self.store.claim_bark_enrollment(
                token=enrollment["token"],
                name="重复绑定",
                server_url="https://api.day.app",
                key_fingerprint="FFFFFFFFFF",
            )

    def test_transactional_revocation_returns_bark_secret_ids(self):
        sender = self._new_sender()
        enrollment = self.store.start_bark_enrollment(sender["senderId"])
        destination = self.store.claim_bark_enrollment(
            token=enrollment["token"],
            name="待撤销 iPhone",
            server_url="https://api.day.app",
            key_fingerprint="ABCDEF1234",
        )

        cleanup_ids = self.store.revoke_with_secrets(sender["senderId"])

        self.assertEqual([destination["destinationId"]], cleanup_ids)
        self.assertEqual(
            [destination["destinationId"]],
            self.store.revoked_bark_destination_ids(),
        )
        self.assertIsNone(self.store.revoke_with_secrets(sender["senderId"]))

    def test_bark_enrollment_code_expires(self):
        sender = self._new_sender()
        enrollment = self.store.start_bark_enrollment(sender["senderId"])
        with closing(sqlite3.connect(str(self.database))) as connection, connection:
            connection.execute(
                "UPDATE bark_enrollments SET expires_at=0 WHERE code=?",
                (enrollment["code"],),
            )

        with self.assertRaisesRegex(ValueError, "已过期"):
            self.store.claim_bark_enrollment(
                code=enrollment["code"],
                name="过期 iPhone",
                server_url="https://api.day.app",
                key_fingerprint="1234567890",
            )

    def test_historical_bark_code_collision_is_retried(self):
        started_at = 4_000
        with mock.patch("device_store.time.time", return_value=started_at):
            sender = self._new_sender()
            historical = self.store.start_bark_enrollment(sender["senderId"])
            self.store.claim_bark_enrollment(
                token=historical["token"],
                name="旧 iPhone",
                server_url="https://api.day.app",
                key_fingerprint="1234567890",
            )
        old_value = int(historical["code"])
        new_value = (old_value + 1) % 1_000_000

        with mock.patch(
            "device_store.time.time",
            return_value=started_at + PAIR_TTL_SECONDS + 1,
        ), mock.patch(
            "device_store.secrets.randbelow",
            side_effect=[old_value, new_value],
        ):
            fresh = self.store.start_bark_enrollment(sender["senderId"])

        self.assertEqual(f"{new_value:06d}", fresh["code"])


class AuditStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name) / "通知记录"
        self.template = Path(self.temporary.name) / "viewer.html"
        self.template.write_text("<!doctype html><title>viewer</title>", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def test_viewer_record_and_body_limit(self):
        store = AuditStore(self.directory, self.template, max_bytes=1024 * 1024)
        body = "正" * (MAX_BODY_BYTES * 2)
        store.record(
            {
                "id": "event-1",
                "device": "手机",
                "packageName": "com.example",
                "appName": "示例",
                "title": "标题",
                "text": body,
                "privacyMode": "full",
                "postTime": 1,
            },
            sender={"device_id": "s_1", "name": "手机", "fingerprint": "ABC123"},
            destinations=[{"deviceId": "r_1", "name": "Air", "fingerprint": "DEF456"}],
        )
        records = store.query()
        self.assertEqual(1, len(records))
        self.assertLessEqual(len(records[0]["body"].encode("utf-8")), MAX_BODY_BYTES)
        self.assertEqual("DEF456", records[0]["destinations"][0]["fingerprint"])
        self.assertTrue(store.viewer_path.is_file())

    def test_storage_and_sqlite_sidecars_are_private(self):
        store = AuditStore(self.directory, self.template, max_bytes=1024 * 1024)
        sidecars = [
            Path(str(store.database_path) + suffix)
            for suffix in ("-journal", "-wal", "-shm")
        ]
        self.directory.chmod(0o755)
        store.database_path.chmod(0o644)
        for sidecar in sidecars:
            sidecar.touch()
            sidecar.chmod(0o644)

        reopened = AuditStore(self.directory, self.template, max_bytes=1024 * 1024)
        reopened.stats()

        self.assertEqual(0o700, self.directory.stat().st_mode & 0o777)
        self.assertEqual(0o600, store.database_path.stat().st_mode & 0o777)
        for sidecar in sidecars:
            if sidecar.exists():
                self.assertEqual(0o600, sidecar.stat().st_mode & 0o777)

    def test_small_capacity_deletes_oldest_records(self):
        store = AuditStore(self.directory, self.template, max_bytes=128 * 1024)
        for index in range(180):
            store.record({
                "id": f"event-{index}",
                "device": "phone",
                "packageName": "com.example",
                "appName": "Example",
                "title": str(index),
                "text": "x" * 4096,
                "privacyMode": "full",
                "postTime": index,
            })
        records = store.query(limit=500)
        self.assertGreater(len(records), 0)
        self.assertLess(len(records), 180)
        self.assertEqual("event-179", records[0]["event_id"])
        self.assertLessEqual(store.stats()["bytes"], 128 * 1024)

    def test_query_supports_stable_offset_pagination_and_search_count(self):
        store = AuditStore(self.directory, self.template, max_bytes=1024 * 1024)
        for index in range(45):
            store.record({
                "id": f"event-{index:02d}",
                "device": "phone",
                "packageName": "com.example",
                "appName": "微信" if index < 23 else "QQ",
                "title": f"标题 {index:02d}",
                "text": f"正文 {index:02d}",
                "privacyMode": "full",
                "postTime": index,
            })

        first_page = store.query(limit=20, offset=0)
        second_page = store.query(limit=20, offset=20)

        self.assertEqual("event-44", first_page[0]["event_id"])
        self.assertEqual("event-25", first_page[-1]["event_id"])
        self.assertEqual("event-24", second_page[0]["event_id"])
        self.assertEqual("event-05", second_page[-1]["event_id"])
        self.assertTrue(
            set(item["event_id"] for item in first_page).isdisjoint(
                item["event_id"] for item in second_page
            )
        )
        self.assertEqual(45, store.count())
        self.assertEqual(23, store.count(search="微信"))

    def test_device_groups_and_sender_filter(self):
        store = AuditStore(self.directory, self.template, max_bytes=1024 * 1024)
        for index in range(5):
            sender = {
                "device_id": "s_phone_a" if index < 3 else "s_phone_b",
                "name": "红米手机" if index < 3 else "vivo 手机",
                "fingerprint": "AAAA111111" if index < 3 else "BBBB222222",
            }
            store.record({
                "id": f"device-event-{index}",
                "appName": "微信",
                "title": f"标题 {index}",
                "text": "正文",
                "privacyMode": "full",
                "postTime": index,
            }, sender=sender)

        groups = store.device_groups()
        self.assertEqual(
            [("s_phone_a", 3), ("s_phone_b", 2)],
            sorted((item["sender_id"], item["count"]) for item in groups),
        )
        self.assertEqual(3, store.count(sender_id="s_phone_a"))
        self.assertEqual(
            ["device-event-2", "device-event-1", "device-event-0"],
            [item["event_id"] for item in store.query(sender_id="s_phone_a")],
        )


class DiagnosticStoreTests(unittest.TestCase):
    def test_storage_and_sqlite_sidecars_are_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "diagnostics"
            store = DiagnosticStore(directory)
            sidecars = [
                Path(str(store.database_path) + suffix)
                for suffix in ("-journal", "-wal", "-shm")
            ]
            directory.chmod(0o755)
            store.database_path.chmod(0o644)
            for sidecar in sidecars:
                sidecar.touch()
                sidecar.chmod(0o644)

            reopened = DiagnosticStore(directory)
            reopened.stats()

            self.assertEqual(0o700, directory.stat().st_mode & 0o777)
            self.assertEqual(0o600, store.database_path.stat().st_mode & 0o777)
            for sidecar in sidecars:
                if sidecar.exists():
                    self.assertEqual(0o600, sidecar.stat().st_mode & 0o777)

    def test_query_and_groups_are_scoped_by_device(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = DiagnosticStore(Path(temporary) / "diagnostics")
            payload = {
                "appVersion": "0.8",
                "platformVersion": "14",
                "networkStatus": "online",
                "serverStatus": "online",
                "paired": True,
                "listenerEnabled": True,
                "backgroundRestricted": False,
                "entries": [{"at": 10, "level": "info", "code": "SSE_CONNECTED"}],
            }
            first = {"device_id": "s_phone", "name": "手机", "fingerprint": "AAA", "platform": "android", "role": "sender"}
            second = {"device_id": "r_air", "name": "Air", "fingerprint": "BBB", "platform": "macos", "role": "receiver"}
            store.record(payload, first)
            store.record(payload, first)
            store.record(payload, second)

            self.assertEqual(2, len(store.query(device_id="s_phone")))
            self.assertEqual("s_phone", store.query(device_id="s_phone")[0]["device_id"])
            groups = {item["device_id"]: item["count"] for item in store.device_groups()}
            self.assertEqual({"s_phone": 2, "r_air": 1}, groups)


if __name__ == "__main__":
    unittest.main()
