#!/usr/bin/env python3
import http.client
import io
import json
import threading
import unittest
import urllib.error
from unittest import mock

import public_ingress


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, maximum=None):
        payload = b'{"ok":true}'
        return payload if maximum is None else payload[:maximum]


class PublicIngressTests(unittest.TestCase):
    def setUp(self):
        self.httpd = public_ingress.ThreadingHTTPServer(
            ("127.0.0.1", 0), public_ingress.Handler
        )
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)

    def raw_request(self, method="POST", path="/xxzf/notify", body=b"{}", headers=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.httpd.server_port, timeout=5
        )
        merged = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "Authorization": "Bearer test-only-ingress-token",
        }
        merged.update(headers or {})
        connection.putrequest(method, path, skip_host="Host" in merged)
        for name, value in merged.items():
            connection.putheader(name, value)
        connection.endheaders(body)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, json.loads(raw.decode("utf-8")) if raw else {}

    def test_valid_request_forwards_only_bearer_and_json(self):
        with mock.patch.object(
            public_ingress.BACKEND_OPENER, "open", return_value=_Response()
        ) as opened:
            status, body = self.raw_request()

        self.assertEqual(200, status)
        self.assertTrue(body["ok"])
        request = opened.call_args.args[0]
        self.assertEqual("Bearer test-only-ingress-token", request.get_header("Authorization"))
        self.assertEqual("application/json", request.get_header("Content-type"))

    def test_cross_site_simple_post_and_untrusted_host_are_rejected(self):
        with mock.patch.object(public_ingress.BACKEND_OPENER, "open") as opened:
            status, _ = self.raw_request(
                headers={"Origin": "https://evil.example", "Content-Type": "text/plain"}
            )
            self.assertEqual(403, status)

            status, _ = self.raw_request(headers={"Host": "attacker.invalid"})
            self.assertEqual(421, status)
        opened.assert_not_called()

    def test_body_is_rejected_instead_of_truncated(self):
        with mock.patch.object(public_ingress.BACKEND_OPENER, "open") as opened:
            status, _ = self.raw_request(
                body=b"{}", headers={"Content-Length": str(public_ingress.MAX_BODY + 1)}
            )
            self.assertEqual(413, status)

            status, _ = self.raw_request(body=b"{}", headers={"Content-Length": "-1"})
            self.assertEqual(400, status)
        opened.assert_not_called()

    def test_json_and_bearer_are_mandatory(self):
        with mock.patch.object(public_ingress.BACKEND_OPENER, "open") as opened:
            status, _ = self.raw_request(headers={"Content-Type": "text/plain"})
            self.assertEqual(415, status)

            status, _ = self.raw_request(headers={"Authorization": ""})
            self.assertEqual(401, status)
        opened.assert_not_called()

    def test_upstream_error_is_generic(self):
        with mock.patch.object(
            public_ingress.BACKEND_OPENER,
            "open",
            side_effect=RuntimeError("private upstream detail"),
        ):
            status, body = self.raw_request()
        self.assertEqual(502, status)
        self.assertEqual("upstream unavailable", body["error"])
        self.assertNotIn("private", json.dumps(body))

    def test_upstream_http_error_is_forwarded_and_closed(self):
        response_body = io.BytesIO(b'{"error":"rate limited"}')
        upstream_error = urllib.error.HTTPError(
            "http://backend.invalid",
            429,
            "rate limited",
            {},
            response_body,
        )
        with mock.patch.object(
            public_ingress.BACKEND_OPENER,
            "open",
            side_effect=upstream_error,
        ):
            status, body = self.raw_request()

        self.assertEqual(429, status)
        self.assertEqual("rate limited", body["error"])
        self.assertTrue(response_body.closed)


if __name__ == "__main__":
    unittest.main()
