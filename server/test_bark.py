#!/usr/bin/env python3
import base64
import hashlib
import io
import http.client
import json
import os
import plistlib
import re
import secrets
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock
from contextlib import closing, redirect_stdout
from pathlib import Path


_temporary = tempfile.TemporaryDirectory()
unittest.addModuleCleanup(_temporary.cleanup)
os.environ["DATA_DIR"] = _temporary.name
os.environ["XXZF_AUDIT_DIR"] = os.path.join(_temporary.name, "audit")
os.environ["XXZF_DIAGNOSTIC_DIR"] = os.path.join(_temporary.name, "diagnostics")
_token_file = Path(_temporary.name) / "notify-token.txt"
_token_file.write_text(secrets.token_urlsafe(32), encoding="utf-8")
_token_file.chmod(0o600)
os.environ["XXZF_TOKEN_FILE"] = str(_token_file)

import server  # noqa: E402
from bark_secret_store import BarkSecretStore  # noqa: E402
from audit_store import AuditStore  # noqa: E402
from device_store import DeviceStore  # noqa: E402


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return b'{"code":200}'


class _SilentHandler(server.Handler):
    def log_message(self, _fmt, *_args):
        pass


class BarkForwardingTests(unittest.TestCase):
    def setUp(self):
        server.config.update({
            "barkEnabled": True,
            "barkServer": "https://api.day.app",
            "barkKey": "private-device-key",
            "ownerSenderIds": [],
        })

    def forward(self, privacy, text="何昊: 正文"):
        event = {
            "appName": "微信",
            "title": "何昊",
            "text": text,
            "privacyMode": privacy,
        }
        with mock.patch("urllib.request.urlopen", return_value=_Response()) as opened:
            result = server.forward_bark(event)
        request = opened.call_args.args[0]
        return result, request, json.loads(request.data.decode("utf-8"))

    def test_title_mode_uses_post_and_does_not_put_key_in_url(self):
        result, request, payload = self.forward("title")
        self.assertEqual(200, result["status"])
        self.assertEqual("https://api.day.app/push", request.full_url)
        self.assertNotIn("private-device-key", request.full_url)
        self.assertEqual("微信", payload["title"])
        self.assertEqual("何昊", payload["body"])

    def test_source_mode_uses_notification_title_but_not_notification_text(self):
        _, _, payload = self.forward("source")
        self.assertEqual("何昊", payload["body"])
        self.assertNotIn("正文", payload["body"])

    def test_full_mode_uses_notification_title_but_not_notification_text(self):
        _, _, payload = self.forward("full")
        self.assertEqual("何昊", payload["body"])

    def test_every_privacy_mode_excludes_notification_text_from_bark_post(self):
        marker = "PRIVATE_BODY_MUST_NEVER_LEAVE_SERVER"
        for privacy in ("full", "title", "source"):
            with self.subTest(privacy=privacy):
                _, request, payload = self.forward(privacy, text=marker)
                self.assertEqual("微信", payload["title"])
                self.assertEqual("何昊", payload["body"])
                self.assertNotIn(marker, request.data.decode("utf-8"))

    def test_empty_notification_title_uses_fixed_generic_body(self):
        event = {
            "appName": "微信",
            "title": "",
            "text": "PRIVATE_BODY_MUST_NEVER_LEAVE_SERVER",
            "privacyMode": "full",
        }
        with mock.patch("urllib.request.urlopen", return_value=_Response()) as opened:
            result = server.forward_bark(event)
        payload = json.loads(opened.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(200, result["status"])
        self.assertEqual("微信", payload["title"])
        self.assertEqual("收到一条新通知", payload["body"])

    def test_notification_text_is_absent_from_bark_failure_log(self):
        marker = "PRIVATE_BODY_MUST_NEVER_REACH_ERROR_LOG"

        def fail_delivery(request, **_kwargs):
            request_data = request.data.decode("utf-8")
            if marker in request_data:
                raise RuntimeError(marker)
            raise urllib.error.URLError("offline")

        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            server, "ERROR_LOG", Path(temporary) / "server-errors.log"
        ), mock.patch("urllib.request.urlopen", side_effect=fail_delivery):
            result = server.forward_bark({
                "appName": "微信",
                "title": "何昊",
                "text": marker,
                "privacyMode": "full",
            })
            logged = server.ERROR_LOG.read_text("utf-8")

        self.assertEqual({"error": "delivery_failed"}, result)
        self.assertNotIn(marker, logged)

    def test_default_bind_page_uses_dedicated_xxzf_route(self):
        self.assertEqual(
            "https://example.com/xxzf/bark/",
            server.BARK_BIND_PAGE,
        )

    def test_launch_agent_configures_dedicated_bark_bind_page(self):
        launch_agent = plistlib.loads(
            (
                Path(server.__file__).parent.parent
                / "deploy/launchd/com.zundu.xxzf.server.plist.example"
            ).read_bytes()
        )
        self.assertEqual(
            "https://example.com/xxzf/bark/",
            launch_agent["EnvironmentVariables"]["XXZF_BARK_BIND_PAGE"],
        )

    def test_official_test_url_is_reduced_to_origin_and_key(self):
        base, key = server.parse_bark_test_url(
            "https://api.day.app/AbCdEf0123456789_test/测试标题/测试正文?group=x"
        )
        self.assertEqual("https://api.day.app", base)
        self.assertEqual("AbCdEf0123456789_test", key)

    def test_untrusted_bark_urls_are_rejected(self):
        invalid = [
            "http://api.day.app/" + "x" * 16,
            "https://api.day.app.evil.example/" + "x" * 16,
            "https://user@api.day.app/" + "x" * 16,
            "https://api.day.app:444/" + "x" * 16,
            "https://api.day.app/short",
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                server.parse_bark_test_url(value)

    def test_delivery_refuses_non_allowlisted_or_cleartext_bark_servers(self):
        event = {
            "appName": "test",
            "title": "test",
            "text": "test",
            "privacyMode": "full",
        }
        for value in ("http://api.day.app", "https://127.0.0.1", "https://evil.example"):
            with self.subTest(value=value), mock.patch("urllib.request.urlopen") as opened:
                result = server.send_bark(value, "per-device-private-key", event)
                self.assertIn("error", result)
                opened.assert_not_called()

    def test_per_destination_sender_uses_post_without_key_in_url(self):
        with mock.patch("urllib.request.urlopen", return_value=_Response()) as opened:
            result = server.send_bark(
                "https://api.day.app",
                "per-device-private-key",
                {
                    "appName": "微信",
                    "title": "何昊",
                    "text": "何昊: 正文",
                    "privacyMode": "full",
                },
            )
        request = opened.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(200, result["status"])
        self.assertEqual("https://api.day.app/push", request.full_url)
        self.assertNotIn("per-device-private-key", request.full_url)
        self.assertEqual("per-device-private-key", payload["device_key"])

    def test_android_source_uses_platform_prefix_and_content_addressed_icon(self):
        icon_id = "a" * 64
        with mock.patch("urllib.request.urlopen", return_value=_Response()) as opened:
            result = server.send_bark(
                "https://api.day.app",
                "per-device-private-key",
                {
                    "packageName": "com.example.chat",
                    "appName": "微信",
                    "title": "新消息",
                    "text": "正文不会发送给 Bark",
                    "privacyMode": "full",
                    "appIconId": icon_id,
                },
            )
        payload = json.loads(opened.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(200, result["status"])
        self.assertEqual("安卓-微信", payload["title"])
        self.assertEqual(
            "https://example.com/xxzf/v1/bark/icons/" + icon_id + ".png",
            payload["icon"],
        )
        self.assertNotIn("正文不会发送给 Bark", opened.call_args.args[0].data.decode("utf-8"))

    def test_valid_png_is_stored_by_hash_without_retaining_base64(self):
        png = (
            b"\x89PNG\r\n\x1a\n"
            + (13).to_bytes(4, "big")
            + b"IHDR"
            + (1).to_bytes(4, "big")
            + (1).to_bytes(4, "big")
            + b"\x08\x06\x00\x00\x00"
            + b"\x00\x00\x00\x00"
            + b"\x00\x00\x00\x00IEND\x00\x00\x00\x00"
        )
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            server, "BARK_ICON_DIR", Path(temporary)
        ):
            event = server.normalize_event({
                "packageName": "com.example.chat",
                "appName": "微信",
                "title": "测试",
                "appIconPng": base64.b64encode(png).decode("ascii"),
            })
            icon_id = hashlib.sha256(png).hexdigest()
            self.assertEqual(icon_id, event["appIconId"])
            self.assertEqual(png, (Path(temporary) / (icon_id + ".png")).read_bytes())
            self.assertNotIn("appIconPng", event)

    def test_provider_http_error_is_classified_without_internal_log(self):
        error = urllib.error.HTTPError(
            "https://api.day.app/push", 400, "bad request", {}, io.BytesIO(b'{"code":400}')
        )
        with mock.patch("urllib.request.urlopen", side_effect=error), mock.patch.object(
            server, "record_internal_error"
        ) as logged:
            result = server.send_bark(
                "https://api.day.app",
                "per-device-private-key",
                {"appName": "测试", "title": "通知"},
            )
        self.assertEqual(400, result["status"])
        self.assertEqual('{"code":400}', result["body"])
        logged.assert_not_called()

    def test_allowlisted_prefixed_bark_server_extracts_key_after_prefix(self):
        with mock.patch.object(
            server, "BARK_ALLOWED_BASES", frozenset({"https://push.example.com/bark-api"})
        ):
            base, key = server.parse_bark_test_url(
                "https://push.example.com/bark-api/AbCdEf0123456789_test/标题/正文"
            )
        self.assertEqual("https://push.example.com/bark-api", base)
        self.assertEqual("AbCdEf0123456789_test", key)

    def test_bark_only_sender_is_routed_without_global_duplicate(self):
        sender = {"device_id": "s_customer", "name": "客户手机", "fingerprint": "ABC"}
        destination = {
            "destinationId": "b_iphone",
            "deviceId": "b_iphone",
            "name": "客户的 iPhone",
            "platform": "ios",
            "type": "bark",
            "fingerprint": "DEF",
            "serverUrl": "https://api.day.app",
        }
        server.config["ownerSenderIds"] = [sender["device_id"]]
        with mock.patch.object(
            server.device_store, "destinations_for_sender", return_value=[]
        ), mock.patch.object(
            server.device_store, "bark_destinations_for_sender", return_value=[destination]
        ), mock.patch.object(
            server.audit_store, "record"
        ), mock.patch.object(
            server, "push_event"
        ), mock.patch.object(
            server, "queue_local_mac_notify"
        ), mock.patch.object(
            server, "queue_bark_destination"
        ) as per_destination, mock.patch.object(
            server, "queue_bark"
        ) as global_bark:
            _, destinations, bark = server.process_event(
                {
                    "appName": "微信",
                    "title": "测试",
                    "text": "正文",
                    "privacyMode": "full",
                },
                sender=sender,
                legacy=False,
            )
        self.assertEqual([destination], destinations)
        self.assertEqual({"queued": True, "destinations": 1}, bark)
        per_destination.assert_called_once()
        global_bark.assert_not_called()


class BarkSecretStoreTests(unittest.TestCase):
    def test_secret_file_is_private_and_supports_revocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bark-secrets.json"
            store = BarkSecretStore(path)
            store.put("b_destination", "private-device-key")
            self.assertEqual("private-device-key", store.get("b_destination"))
            self.assertEqual(0o600, path.stat().st_mode & 0o777)
            self.assertTrue(store.delete("b_destination"))
            self.assertIsNone(store.get("b_destination"))


class BarkApiLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        with server.rate_lock:
            server.rate_windows.clear()
        with server.lock:
            for stream in list(server.clients):
                stream.close()
            for streams in server.receiver_clients.values():
                for stream in list(streams):
                    if hasattr(stream, "close"):
                        stream.close()
            server.clients.clear()
            server.receiver_clients.clear()
        self.previous_secret_store = server.bark_secret_store
        self.previous_audit_store = server.audit_store
        self.previous_device_store = server.device_store
        self.previous_device_db = server.DEVICE_DB
        self.previous_config = dict(server.config)
        server.config.update({
            "barkEnabled": False,
            "barkKey": "",
            "localMacNotify": False,
            "ownerSenderIds": [],
        })
        server.DEVICE_DB = Path(self.temporary.name) / "devices.sqlite3"
        server.device_store = DeviceStore(server.DEVICE_DB)
        server.bark_secret_store = BarkSecretStore(
            Path(self.temporary.name) / "bark-secrets.json"
        )
        server.audit_store = AuditStore(
            Path(self.temporary.name) / "audit", server.AUDIT_TEMPLATE
        )
        pairing = server.device_store.start_pairing("API 测试电脑", "macos")
        sender = server.device_store.claim_pairing(
            pairing["code"], "API 测试手机", "android"
        )
        self.sender = sender
        self.authorization = "Bearer " + sender["senderId"] + "." + sender["senderSecret"]
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), _SilentHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.httpd.server_port)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        with server.rate_lock:
            server.rate_windows.clear()
        server.bark_secret_store = self.previous_secret_store
        server.audit_store = self.previous_audit_store
        server.device_store = self.previous_device_store
        server.DEVICE_DB = self.previous_device_db
        server.config.clear()
        server.config.update(self.previous_config)
        self.temporary.cleanup()

    def create_sender_with_bark(self, name="撤销测试手机"):
        pairing = server.device_store.start_pairing(name + "的电脑", "macos")
        sender = server.device_store.claim_pairing(
            pairing["code"], name, "android"
        )
        enrollment = server.device_store.start_bark_enrollment(sender["senderId"])
        destination = server.device_store.claim_bark_enrollment(
            token=enrollment["token"],
            name=name + "的 iPhone",
            server_url="https://api.day.app",
            key_fingerprint="ABCDEF1234",
        )
        server.bark_secret_store.put(
            destination["destinationId"], "RevokeTestSecret_0123456789"
        )
        authorization = "Bearer " + sender["senderId"] + "." + sender["senderSecret"]
        return sender, destination, authorization

    def request(
        self, method, path, payload=None, authenticated=False, extra_headers=None
    ):
        status, body, _ = self.request_with_headers(
            method,
            path,
            payload=payload,
            authenticated=authenticated,
            extra_headers=extra_headers,
        )
        return status, body

    def request_with_headers(
        self, method, path, payload=None, authenticated=False, extra_headers=None
    ):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if authenticated:
            headers["Authorization"] = self.authorization
        headers.update(extra_headers or {})
        request = urllib.request.Request(
            self.base + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return (
                    response.status,
                    json.loads(response.read().decode("utf-8")),
                    response.headers,
                )
        except urllib.error.HTTPError as error:
            with closing(error):
                return (
                    error.code,
                    json.loads(error.read().decode("utf-8")),
                    error.headers,
                )

    def test_self_service_lifecycle_and_replay_rejection(self):
        status, started = self.request(
            "POST", "/api/v1/bark/enroll/start", {}, authenticated=True
        )
        self.assertEqual(201, status)
        enrollment = started["enrollment"]
        self.assertNotIn("token", enrollment)
        fragment = urllib.parse.urlparse(enrollment["bindUrl"]).fragment
        token = urllib.parse.parse_qs(fragment)["token"][0]
        device_key = "ApiLifecycleKey_0123456789"
        claim_payload = {
            "token": token,
            "barkUrl": "https://api.day.app/" + device_key + "/title/body",
            "deviceName": "测试 iPhone",
        }

        successful_push = {"status": 200, "body": '{"code":200}'}
        with mock.patch.object(server, "send_bark", return_value=successful_push) as delivered:
            status, claimed = self.request(
                "POST", "/api/v1/bark/enroll/claim", claim_payload
            )
            self.assertEqual(201, status)
            delivered.assert_called_once()
        destination = claimed["destination"]
        self.assertNotIn("key", json.dumps(destination).lower())
        self.assertEqual(
            device_key,
            server.bark_secret_store.get(destination["destinationId"]),
        )
        self.assertNotIn(device_key.encode(), server.DEVICE_DB.read_bytes())

        status, listed = self.request(
            "GET", "/api/v1/destinations", authenticated=True
        )
        self.assertEqual(200, status)
        self.assertNotIn(device_key, json.dumps(listed))
        self.assertTrue(any(
            item.get("destinationId") == destination["destinationId"]
            for item in listed["destinations"]
        ))

        with mock.patch.object(server, "send_bark", return_value=successful_push) as delivered:
            status, replayed = self.request(
                "POST", "/api/v1/bark/enroll/claim", claim_payload
            )
            self.assertEqual(400, status)
            self.assertEqual(server.BARK_ENROLLMENT_PUBLIC_ERROR, replayed["error"])
            delivered.assert_not_called()

        status, revoked = self.request(
            "POST",
            "/api/v1/bark/revoke",
            {"destinationId": destination["destinationId"]},
            authenticated=True,
        )
        self.assertEqual(200, status)
        self.assertTrue(revoked["ok"])
        self.assertIsNone(server.bark_secret_store.get(destination["destinationId"]))

    def test_receiver_revokes_only_its_selected_sender_route(self):
        receiver = server.device_store.start_pairing("Android 接收端", "android")
        first_sender = server.device_store.claim_pairing(
            receiver["code"], "发送设备一", "android"
        )
        second_code = server.device_store.start_pairing_for_receiver(
            receiver["receiverId"]
        )
        second_sender = server.device_store.claim_pairing(
            second_code["code"], "发送设备二", "android"
        )
        other_receiver = server.device_store.start_pairing("其他接收端", "macos")
        server.device_store.claim_pairing_for_sender(
            other_receiver["code"], first_sender["senderId"]
        )
        receiver_auth = "Bearer " + receiver["receiverId"] + "." + receiver["receiverSecret"]
        other_receiver_auth = (
            "Bearer " + other_receiver["receiverId"] + "."
            + other_receiver["receiverSecret"]
        )
        stream, reason = server.register_receiver_stream(
            object(), receiver["receiverId"], "203.0.113.61"
        )
        self.assertIsNone(reason)

        status, body = self.request(
            "POST",
            "/api/v1/receiver/senders/revoke",
            {"senderId": first_sender["senderId"]},
            extra_headers={"Authorization": receiver_auth},
        )
        self.assertEqual(200, status)
        self.assertTrue(body["ok"])
        self.assertFalse(stream.closed.is_set())

        status, listed = self.request(
            "GET",
            "/api/pair/status",
            extra_headers={"Authorization": receiver_auth},
        )
        self.assertEqual(200, status)
        self.assertEqual(
            [second_sender["senderId"]],
            [item["deviceId"] for item in listed["senders"]],
        )

        status, denied = self.request(
            "POST",
            "/api/v1/receiver/senders/revoke",
            {"senderId": first_sender["senderId"]},
            extra_headers={"Authorization": receiver_auth},
        )
        self.assertEqual(404, status)
        self.assertFalse(denied["ok"])

        status, other_listed = self.request(
            "GET",
            "/api/pair/status",
            extra_headers={"Authorization": other_receiver_auth},
        )
        self.assertEqual(200, status)
        self.assertEqual(
            [first_sender["senderId"]],
            [item["deviceId"] for item in other_listed["senders"]],
        )
        self.assertIsNotNone(server.device_store.authenticate(
            first_sender["senderId"], first_sender["senderSecret"], "sender"
        ))
        self.assertIsNotNone(server.device_store.authenticate(
            second_sender["senderId"], second_sender["senderSecret"], "sender"
        ))
        self.assertIsNotNone(server.device_store.authenticate(
            receiver["receiverId"], receiver["receiverSecret"], "receiver"
        ))
        server.unregister_event_stream(stream)

    def test_receiver_sender_revoke_rejects_missing_or_wrong_role_credentials(self):
        status, _ = self.request(
            "POST", "/api/v1/receiver/senders/revoke", {"senderId": "s_unknown"}
        )
        self.assertEqual(401, status)

    def test_receiver_sender_revoke_rejects_other_methods_and_adjacent_paths(self):
        status, _ = self.request(
            "GET", "/api/v1/receiver/senders/revoke", authenticated=True
        )
        self.assertEqual(404, status)
        status, _ = self.request(
            "POST",
            "/api/v1/receiver/senders/revoke/extra",
            {"senderId": self.sender["senderId"]},
            authenticated=True,
        )
        self.assertEqual(404, status)

        status, _ = self.request(
            "POST",
            "/api/v1/receiver/senders/revoke",
            {"senderId": self.sender["senderId"]},
            authenticated=True,
        )
        self.assertEqual(401, status)

    def test_pair_claim_errors_are_uniform(self):
        pairing = server.device_store.start_pairing("错误测试电脑", "macos")
        server.device_store.claim_pairing(pairing["code"], "已连接手机", "android")

        malformed_status, malformed = self.request(
            "POST", "/api/pair/claim", {"code": "12AB"}
        )
        used_status, used = self.request(
            "POST", "/api/pair/claim", {"code": pairing["code"]}
        )
        start_shape_status, start_shape = self.request(
            "POST", "/api/pair/start", []
        )
        claim_shape_status, claim_shape = self.request(
            "POST", "/api/pair/claim", []
        )

        self.assertEqual(400, malformed_status)
        self.assertEqual(400, used_status)
        self.assertEqual(400, start_shape_status)
        self.assertEqual(400, claim_shape_status)
        self.assertEqual(server.PAIRING_PUBLIC_ERROR, malformed["error"])
        self.assertEqual(malformed["error"], used["error"])
        self.assertEqual(malformed["error"], start_shape["error"])
        self.assertEqual(malformed["error"], claim_shape["error"])

    def test_pair_claim_returns_only_official_https_notify_url(self):
        pairing = server.device_store.start_pairing("安全链路测试", "macos")

        status, body = self.request(
            "POST",
            "/api/pair/claim",
            {"code": pairing["code"], "deviceName": "测试手机"},
        )

        self.assertEqual(200, status)
        device = body["device"]
        self.assertEqual(server.PUBLIC_BASE, device["serverBase"])
        self.assertEqual(
            [server.PUBLIC_BASE + "/v1/notify"], device["notifyUrls"]
        )

    def test_self_revoke_immediately_invalidates_device_credential(self):
        enrollment = server.device_store.start_bark_enrollment(
            self.sender["senderId"]
        )
        destination = server.device_store.claim_bark_enrollment(
            token=enrollment["token"], key_fingerprint="ABCDEF1234"
        )
        server.bark_secret_store.put(
            destination["destinationId"], "TestSecret_0123456789"
        )

        status, body = self.request(
            "POST", "/api/v1/device/revoke", {}, authenticated=True
        )
        self.assertEqual(200, status)
        self.assertTrue(body["ok"])

        status, body = self.request(
            "GET", "/api/v1/device-status", authenticated=True
        )
        self.assertEqual(401, status)
        self.assertFalse(body["ok"])
        self.assertIsNone(
            server.bark_secret_store.get(destination["destinationId"])
        )

    def test_bark_revoke_delete_failure_is_not_reported_as_success(self):
        enrollment = server.device_store.start_bark_enrollment(
            self.sender["senderId"]
        )
        destination = server.device_store.claim_bark_enrollment(
            token=enrollment["token"], key_fingerprint="ABCDEF1234"
        )
        server.bark_secret_store.put(
            destination["destinationId"], "DeleteFailureSecret_0123456789"
        )
        marker = "SECRET_DELETE_FAILURE_MUST_NOT_REFLECT"

        with mock.patch.object(
            server.bark_secret_store, "delete", side_effect=RuntimeError(marker)
        ):
            status, body, headers = self.request_with_headers(
                "POST",
                "/api/v1/bark/revoke",
                {"destinationId": destination["destinationId"]},
                authenticated=True,
            )

        self.assertEqual(500, status)
        self.assertEqual("request failed", body["error"])
        self.assertEqual(body["requestId"], headers["X-Request-ID"])
        self.assertNotIn(marker, json.dumps(body))
        self.assertEqual(
            [],
            server.device_store.bark_destinations_for_sender(
                self.sender["senderId"]
            ),
        )
        self.assertEqual(
            "DeleteFailureSecret_0123456789",
            server.bark_secret_store.get(destination["destinationId"]),
        )

    def test_self_revoke_delete_failure_returns_500_and_revokes_device(self):
        sender, destination, authorization = self.create_sender_with_bark(
            "自撤销失败测试"
        )
        marker = "SELF_REVOKE_DELETE_FAILURE"
        with mock.patch.object(
            server.bark_secret_store, "delete", side_effect=RuntimeError(marker)
        ):
            status, body = self.request(
                "POST",
                "/api/v1/device/revoke",
                {},
                extra_headers={"Authorization": authorization},
            )

        self.assertEqual(500, status)
        self.assertEqual("request failed", body["error"])
        self.assertNotIn(marker, json.dumps(body))
        self.assertIsNone(server.device_store.authenticate(
            sender["senderId"], sender["senderSecret"], "sender"
        ))
        self.assertEqual(
            "RevokeTestSecret_0123456789",
            server.bark_secret_store.get(destination["destinationId"]),
        )

    def test_local_revoke_delete_failure_returns_500_and_revokes_device(self):
        sender, destination, _authorization = self.create_sender_with_bark(
            "本地撤销失败测试"
        )
        marker = "LOCAL_REVOKE_DELETE_FAILURE"
        with mock.patch.object(
            server.bark_secret_store, "delete", side_effect=RuntimeError(marker)
        ):
            status, body = self.request(
                "POST",
                "/api/devices/revoke",
                {"deviceId": sender["senderId"]},
            )

        self.assertEqual(500, status)
        self.assertEqual("request failed", body["error"])
        self.assertNotIn(marker, json.dumps(body))
        self.assertIsNone(server.device_store.authenticate(
            sender["senderId"], sender["senderSecret"], "sender"
        ))
        self.assertEqual(
            "RevokeTestSecret_0123456789",
            server.bark_secret_store.get(destination["destinationId"]),
        )

    def test_startup_reconciliation_erases_revoked_bark_orphan(self):
        sender, destination, _authorization = self.create_sender_with_bark(
            "启动清理测试"
        )
        cleanup_ids = server.device_store.revoke_with_secrets(sender["senderId"])
        self.assertEqual([destination["destinationId"]], cleanup_ids)
        self.assertIsNotNone(
            server.bark_secret_store.get(destination["destinationId"])
        )

        server.reconcile_revoked_bark_secrets()

        self.assertIsNone(
            server.bark_secret_store.get(destination["destinationId"])
        )

    def test_unexpected_and_expected_errors_do_not_reflect_exception_text(self):
        unexpected_marker = "UNEXPECTED_PRIVATE_EXCEPTION_DETAIL"
        with mock.patch.object(
            server.device_store,
            "update_rate_limit",
            side_effect=RuntimeError(unexpected_marker),
        ):
            status, unexpected, headers = self.request_with_headers(
                "POST",
                "/api/devices/rate",
                {"deviceId": self.sender["senderId"], "rateLimit": 50},
            )
        self.assertEqual(500, status)
        self.assertEqual("request failed", unexpected["error"])
        self.assertNotIn(unexpected_marker, json.dumps(unexpected))
        self.assertEqual(unexpected["requestId"], headers["X-Request-ID"])
        self.assertIn(unexpected_marker, server.ERROR_LOG.read_text("utf-8"))

        status, invalid = self.request(
            "POST",
            "/api/config",
            {"barkServer": "https://not-allowlisted.invalid"},
        )
        self.assertEqual(400, status)
        self.assertEqual("invalid request", invalid["error"])
        self.assertNotIn("allowlist", json.dumps(invalid).lower())

        permission_marker = "PRIVATE_PERMISSION_DETAIL"
        with mock.patch.object(
            server, "process_event", side_effect=PermissionError(permission_marker)
        ):
            status, denied = self.request(
                "POST",
                "/api/notify",
                {"title": "test"},
                extra_headers={"Authorization": "Bearer " + server.NOTIFY_TOKEN},
            )
        self.assertEqual(403, status)
        self.assertEqual("operation not permitted", denied["error"])
        self.assertNotIn(permission_marker, json.dumps(denied))

    def test_legacy_bark_response_exposes_only_delivery_state(self):
        upstream_marker = "UPSTREAM_BODY_AND_NETWORK_DETAIL"
        with mock.patch.object(
            server,
            "forward_bark",
            return_value={"status": 502, "body": upstream_marker},
        ), mock.patch.object(
            server.audit_store, "record"
        ), mock.patch.object(
            server, "push_event"
        ), mock.patch.object(
            server, "queue_local_mac_notify"
        ):
            status, body = self.request(
                "POST",
                "/api/notify",
                {"appName": "测试", "title": "标题", "text": "正文"},
                extra_headers={"Authorization": "Bearer " + server.NOTIFY_TOKEN},
            )

        self.assertEqual(200, status)
        self.assertEqual({"delivered": False}, body["bark"])
        self.assertNotIn(upstream_marker, json.dumps(body))

    def test_archive_ignores_client_supplied_unredacted_fields(self):
        marker = "PRIVATE_ARCHIVE_BYPASS_MARKER"
        status, _ = self.request(
            "POST",
            "/api/v1/notify",
            {
                "appName": "测试",
                "title": "",
                "text": "",
                "privacyMode": "source",
                "archiveTitle": marker,
                "archiveText": marker,
            },
            authenticated=True,
        )

        self.assertEqual(200, status)
        archived = json.dumps(server.audit_store.query(limit=10), ensure_ascii=False)
        self.assertNotIn(marker, archived)

    def test_persistent_pair_claim_lock_returns_retry_after(self):
        pairing = server.device_store.start_pairing("等待连接的电脑", "macos")
        failures = 0
        candidate = 300
        while failures < 40:
            code = f"{candidate:06d}"
            candidate += 1
            if code == pairing["code"]:
                continue
            try:
                server.device_store.claim_pairing(code, "攻击者", "android")
            except ValueError:
                failures += 1

        status, body, headers = self.request_with_headers(
            "POST", "/api/pair/claim", {"code": pairing["code"]}
        )

        self.assertEqual(429, status)
        self.assertEqual(server.PAIRING_RATE_LIMIT_ERROR, body["error"])
        self.assertGreaterEqual(int(headers["Retry-After"]), 1)

    def test_ip_pair_claim_limit_uses_same_retryable_error(self):
        status = 0
        body = {}
        headers = {}
        for _ in range(21):
            status, body, headers = self.request_with_headers(
                "POST", "/api/pair/claim", {"code": "bad"}
            )

        self.assertEqual(429, status)
        self.assertEqual(server.PAIRING_RATE_LIMIT_ERROR, body["error"])
        self.assertGreaterEqual(int(headers["Retry-After"]), 1)

    def test_ip_pair_start_limit_uses_same_retryable_error(self):
        status = 0
        body = {}
        headers = {}
        for _ in range(9):
            status, body, headers = self.request_with_headers(
                "POST", "/api/pair/start", {"deviceName": "测试电脑"}
            )

        self.assertEqual(429, status)
        self.assertEqual(server.PAIRING_RATE_LIMIT_ERROR, body["error"])
        self.assertGreaterEqual(int(headers["Retry-After"]), 1)

    def test_global_pair_start_budget_applies_across_client_ips(self):
        responses = []
        with mock.patch.object(server, "PAIR_START_GLOBAL_LIMIT", 2):
            for index in range(3):
                responses.append(self.request_with_headers(
                    "POST",
                    "/api/pair/start",
                    {"deviceName": f"测试电脑 {index}"},
                    extra_headers={"X-Real-IP": f"203.0.113.{index + 1}"},
                ))

        self.assertEqual([201, 201, 429], [item[0] for item in responses])
        self.assertEqual(server.PAIRING_RATE_LIMIT_ERROR, responses[-1][1]["error"])
        self.assertGreaterEqual(int(responses[-1][2]["Retry-After"]), 1)

    def test_unexpected_pair_error_uses_request_id_without_internal_details(self):
        server.device_store.path.unlink()
        server.device_store.path.mkdir()

        start_status, start_body, start_headers = self.request_with_headers(
            "POST", "/api/pair/start", {"deviceName": "测试电脑"}
        )
        claim_status, claim_body, claim_headers = self.request_with_headers(
            "POST", "/api/pair/claim", {"code": "123456"}
        )

        for status, body, headers in (
            (start_status, start_body, start_headers),
            (claim_status, claim_body, claim_headers),
        ):
            self.assertEqual(500, status)
            self.assertEqual(server.PAIRING_INTERNAL_ERROR, body["error"])
            self.assertRegex(body["requestId"], r"^[a-f0-9]{16}$")
            self.assertEqual(body["requestId"], headers["X-Request-ID"])
            self.assertNotIn("database", json.dumps(body).lower())
        self.assertNotEqual(start_body["requestId"], claim_body["requestId"])
        self.assertEqual(0o600, server.ERROR_LOG.stat().st_mode & 0o777)
        private_log = server.ERROR_LOG.read_text("utf-8")
        self.assertIn(start_body["requestId"], private_log)
        self.assertIn(claim_body["requestId"], private_log)
        self.assertIn("StorageSecurityError", private_log)

    def test_json_security_headers_do_not_advertise_cross_origin_access(self):
        allowed = urllib.request.Request(
            self.base + "/api/v1/health",
            headers={"Origin": server.PUBLIC_ORIGIN},
            method="GET",
        )
        with urllib.request.urlopen(allowed, timeout=5) as response:
            self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))
            self.assertIsNone(response.headers.get("Vary"))
            self.assertEqual("nosniff", response.headers.get("X-Content-Type-Options"))
            self.assertEqual("DENY", response.headers.get("X-Frame-Options"))
            self.assertEqual("no-referrer", response.headers.get("Referrer-Policy"))

        denied = urllib.request.Request(
            self.base + "/api/v1/health",
            headers={"Origin": "https://evil.example"},
            method="GET",
        )
        with urllib.request.urlopen(denied, timeout=5) as response:
            self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))

    def test_cross_site_simple_pair_post_is_rejected_before_state_change(self):
        before = len(server.device_store.list_devices())
        request = urllib.request.Request(
            self.base + "/api/pair/start",
            data=b"{}",
            headers={
                "Content-Type": "text/plain",
                "Origin": "https://evil.example",
            },
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request, timeout=5)
        with closing(raised.exception):
            self.assertEqual(403, raised.exception.code)
        self.assertEqual(before, len(server.device_store.list_devices()))

    def test_pair_post_requires_json_even_without_origin(self):
        before = len(server.device_store.list_devices())
        request = urllib.request.Request(
            self.base + "/api/pair/start",
            data=b"{}",
            headers={"Content-Type": "text/plain"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request, timeout=5)
        with closing(raised.exception):
            self.assertEqual(415, raised.exception.code)
        self.assertEqual(before, len(server.device_store.list_devices()))

    def test_receiver_stream_limit_rejects_before_opening_another_stream(self):
        receiver_id = "r_stream_limit_test"
        handler = server.Handler.__new__(server.Handler)
        handler.wfile = object()
        handler.client_ip = lambda: "203.0.113.10"
        responses = []
        handler.send_json = lambda status, body, headers=None: responses.append((status, body))
        streams = []
        with mock.patch.object(
            server.device_store, "receiver_has_active_route", return_value=True
        ):
            for index in range(server.MAX_RECEIVER_STREAMS_PER_DEVICE):
                stream, limit = server.register_receiver_stream(
                    object(), receiver_id, f"203.0.113.{index + 1}"
                )
                self.assertIsNone(limit)
                streams.append(stream)
            try:
                handler.send_receiver_stream(receiver_id)
            finally:
                for stream in streams:
                    server.unregister_event_stream(stream)

        self.assertEqual(429, responses[0][0])
        self.assertEqual("too many receiver streams", responses[0][1]["error"])

    def test_pending_receiver_cannot_open_public_event_stream(self):
        pairing = server.device_store.start_pairing("尚未配对电脑", "macos")
        request = urllib.request.Request(
            self.base + "/api/v1/events",
            headers={
                "Authorization": "Bearer "
                + pairing["receiverId"]
                + "."
                + pairing["receiverSecret"]
            },
            method="GET",
        )

        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request, timeout=5)
        with closing(raised.exception):
            body = json.loads(raised.exception.read().decode("utf-8"))

            self.assertEqual(409, raised.exception.code)
        self.assertEqual("receiver is not paired", body["error"])
        with server.lock:
            self.assertNotIn(pairing["receiverId"], server.receiver_clients)

    def test_stream_registry_enforces_client_ip_and_global_limits(self):
        streams = []
        with mock.patch.object(server, "MAX_RECEIVER_STREAMS_PER_CLIENT_IP", 1), \
             mock.patch.object(server, "MAX_EVENT_STREAMS_GLOBAL", 2):
            first, reason = server.register_receiver_stream(
                object(), "r_one", "203.0.113.1"
            )
            self.assertIsNone(reason)
            streams.append(first)

            denied_ip, reason = server.register_receiver_stream(
                object(), "r_two", "203.0.113.1"
            )
            self.assertIsNone(denied_ip)
            self.assertEqual("client_ip", reason)

            second, reason = server.register_receiver_stream(
                object(), "r_two", "203.0.113.2"
            )
            self.assertIsNone(reason)
            streams.append(second)

            denied_global, reason = server.register_receiver_stream(
                object(), "r_three", "203.0.113.3"
            )
            self.assertIsNone(denied_global)
            self.assertEqual("global", reason)

        for stream in streams:
            server.unregister_event_stream(stream)

    def test_slow_stream_write_does_not_block_push_or_allow_concurrent_writes(self):
        class SlowWriter:
            def __init__(self):
                self.started = threading.Event()
                self.release = threading.Event()
                self.notified = threading.Event()
                self.guard = threading.Lock()
                self.active_writes = 0
                self.max_active_writes = 0

            def write(self, payload):
                with self.guard:
                    self.active_writes += 1
                    self.max_active_writes = max(
                        self.max_active_writes, self.active_writes
                    )
                try:
                    if not self.started.is_set():
                        self.started.set()
                        self.release.wait(timeout=3)
                    if b"event: notify" in payload:
                        self.notified.set()
                    time.sleep(0.005)
                finally:
                    with self.guard:
                        self.active_writes -= 1

            def flush(self):
                pass

        writer = SlowWriter()
        receiver_id = "r_slow_writer"
        stream, reason = server.register_receiver_stream(
            writer, receiver_id, "203.0.113.20"
        )
        self.assertIsNone(reason)
        writer_thread = threading.Thread(
            target=stream.run_writer,
            kwargs={"keepalive_seconds": 0.01},
            daemon=True,
        )
        writer_thread.start()
        self.assertTrue(writer.started.wait(timeout=1))

        started_at = time.monotonic()
        server.push_event(
            {"id": "slow-test", "title": "queued"},
            receiver_ids=[receiver_id],
            include_legacy=False,
        )
        elapsed = time.monotonic() - started_at
        self.assertLess(elapsed, 0.2)
        writer.release.set()
        self.assertTrue(writer.notified.wait(timeout=1))

        server.unregister_event_stream(stream)
        writer_thread.join(timeout=1)
        self.assertFalse(writer_thread.is_alive())
        self.assertEqual(1, writer.max_active_writes)

    def test_full_stream_queue_is_closed_and_unregistered(self):
        receiver_id = "r_full_queue"
        stream = server.EventStreamConnection(
            object(),
            client_ip="203.0.113.30",
            receiver_id=receiver_id,
            queue_size=1,
        )
        with server.lock:
            server.receiver_clients[receiver_id] = {stream}

        server.push_event(
            {"id": "first"}, receiver_ids=[receiver_id], include_legacy=False
        )
        server.push_event(
            {"id": "second"}, receiver_ids=[receiver_id], include_legacy=False
        )

        self.assertTrue(stream.closed.is_set())
        with server.lock:
            self.assertNotIn(receiver_id, server.receiver_clients)

    def test_device_revocation_closes_streams_that_lost_their_last_route(self):
        pairing = server.device_store.start_pairing("撤销流电脑", "macos")
        sender = server.device_store.claim_pairing(
            pairing["code"], "撤销流手机", "android"
        )
        stream, reason = server.register_receiver_stream(
            object(), pairing["receiverId"], "203.0.113.40"
        )
        self.assertIsNone(reason)

        self.assertTrue(server.revoke_device_and_secrets(sender["senderId"]))

        self.assertTrue(stream.closed.is_set())
        with server.lock:
            self.assertNotIn(pairing["receiverId"], server.receiver_clients)

    def test_local_management_rejects_untrusted_host_and_origin(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=5)
        connection.putrequest("GET", "/api/devices", skip_host=True)
        connection.putheader("Host", "attacker.invalid")
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(421, response.status)
        response.read()
        connection.close()

        status, body = self.request(
            "POST",
            "/api/config",
            {},
            extra_headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(403, status)
        self.assertEqual("local management access denied", body["error"])

    def test_local_config_rejects_ssrf_and_treats_bark_key_as_write_only(self):
        original = dict(server.config)
        status, _body = self.request(
            "POST",
            "/api/config",
            {
                "barkServer": "https://127.0.0.1",
                "barkKey": "x" * 16,
                "barkEnabled": True,
            },
        )
        self.assertEqual(400, status)
        self.assertEqual(original, server.config)

        server.config["barkKey"] = "ExistingPrivateKey_0123456789"
        rendered = server.page("fixed-test-nonce")
        self.assertNotIn("ExistingPrivateKey_0123456789", rendered)
        self.assertIn("已配置；留空保持不变", rendered)

        status, _body = self.request(
            "POST",
            "/api/config",
            {
                "barkServer": "https://api.day.app",
                "barkKey": "",
                "barkEnabled": True,
                "localMacNotify": False,
            },
        )
        self.assertEqual(200, status)
        self.assertEqual("ExistingPrivateKey_0123456789", server.config["barkKey"])

        status, _body = self.request(
            "POST",
            "/api/config",
            {
                "barkServer": "https://api.day.app",
                "barkKey": "",
                "clearBarkKey": True,
                "barkEnabled": True,
            },
        )
        self.assertEqual(200, status)
        self.assertEqual("", server.config["barkKey"])
        self.assertFalse(server.config["barkEnabled"])

    def test_dashboard_escapes_initial_event_json_and_uses_nonce_csp(self):
        malicious = [{
            "appName": "test",
            "title": "</script><script>window.breakout=true</script>",
            "text": "line\u2028separator",
        }]
        with mock.patch.object(server, "events", malicious):
            rendered = server.page("fixed-test-nonce")
        self.assertNotIn("</script><script>window.breakout", rendered)
        self.assertIn("\\u003c/script>", rendered)
        self.assertIn("\\u2028", rendered)
        payload_match = re.search(
            r'<script id="initial-events"[^>]*>(.*?)</script>', rendered, re.DOTALL
        )
        self.assertIsNotNone(payload_match)
        self.assertEqual(malicious, json.loads(payload_match.group(1)))

        request = urllib.request.Request(self.base + "/", method="GET")
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8")
            csp = response.headers.get("Content-Security-Policy", "")
        nonce_match = re.search(r"script-src 'nonce-([^']+)'", csp)
        self.assertIsNotNone(nonce_match)
        self.assertNotIn("script-src 'unsafe-inline'", csp)
        self.assertIn('nonce="' + nonce_match.group(1) + '"', body)

    def test_local_dashboard_advertises_only_official_https_client_base(self):
        rendered = server.page()
        self.assertIn(server.PUBLIC_BASE + "/v1/notify", rendered)
        self.assertNotIn("http://", rendered)

        status, body = self.request("GET", "/api/config")
        self.assertEqual(200, status)
        self.assertEqual([server.PUBLIC_BASE], body["urls"])

    def test_legacy_notify_accepts_only_bearer_header(self):
        payload = {"appName": "测试", "title": "标题", "text": "正文"}
        authorized_status, _ = self.request(
            "POST",
            "/api/notify",
            payload,
            extra_headers={"Authorization": "Bearer " + server.NOTIFY_TOKEN},
        )
        query_status, _ = self.request(
            "POST",
            "/api/notify?token=" + urllib.parse.quote(server.NOTIFY_TOKEN, safe=""),
            payload,
        )
        deprecated_header_status, _ = self.request(
            "POST",
            "/api/notify",
            payload,
            extra_headers={"X-XXZF-Token": server.NOTIFY_TOKEN},
        )
        wrong_status, _ = self.request(
            "POST",
            "/api/notify",
            payload,
            extra_headers={"Authorization": "Bearer incorrect-test-value"},
        )

        self.assertEqual(200, authorized_status)
        self.assertEqual(401, query_status)
        self.assertEqual(401, deprecated_header_status)
        self.assertEqual(401, wrong_status)

    def test_preflight_is_not_exposed_for_any_origin(self):
        for origin in (server.PUBLIC_ORIGIN, "https://evil.example"):
            with self.subTest(origin=origin):
                request = urllib.request.Request(
                    self.base + "/api/v1/bark/enroll/claim",
                    headers={"Origin": origin},
                    method="OPTIONS",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=5)
                with closing(raised.exception):
                    self.assertEqual(405, raised.exception.code)
                    self.assertIsNone(
                        raised.exception.headers.get("Access-Control-Allow-Origin")
                    )

    def test_global_enrollment_limit_stops_claim_before_validation(self):
        with mock.patch.object(server, "rate_allowed", return_value=False), mock.patch.object(
            server.device_store, "validate_bark_enrollment"
        ) as validated:
            status, body = self.request(
                "POST", "/api/v1/bark/enroll/claim", {"code": "123456"}
            )
        self.assertEqual(429, status)
        self.assertFalse(body["ok"])
        validated.assert_not_called()


class ServerLogPrivacyTests(unittest.TestCase):
    def test_request_log_does_not_render_path_or_query_credentials(self):
        handler = server.Handler.__new__(server.Handler)
        handler.address_string = lambda: "127.0.0.1"
        marker = "DO_NOT_LOG_THIS_CREDENTIAL"
        output = io.StringIO()

        with redirect_stdout(output):
            handler.log_message(
                '"%s" %s',
                "POST /api/notify?token=" + marker,
                "401",
            )

        self.assertNotIn(marker, output.getvalue())
        self.assertNotIn("/api/notify", output.getvalue())
        self.assertEqual("", output.getvalue())

    def test_private_error_log_is_rotated_and_bounded(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            server, "ERROR_LOG", Path(temporary) / "server-errors.log"
        ), mock.patch.object(
            server, "ERROR_LOG_MAX_BYTES", 4096
        ), mock.patch.object(
            server, "ERROR_LOG_BACKUP_COUNT", 3
        ):
            for index in range(24):
                server.record_internal_error(
                    "rotation-test",
                    f"request-{index:02d}",
                    RuntimeError("x" * 900),
                )

            files = sorted(Path(temporary).glob("server-errors.log*"))
            self.assertGreater(len(files), 1)
            self.assertLessEqual(len(files), 4)
            for path in files:
                self.assertLessEqual(path.stat().st_size, 4096)
                self.assertEqual(0o600, path.stat().st_mode & 0o777)


if __name__ == "__main__":
    unittest.main()
