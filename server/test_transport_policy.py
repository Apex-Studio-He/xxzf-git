#!/usr/bin/env python3
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
import plistlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ANDROID_SOURCE = (
    ROOT / "android" / "src" / "com" / "zundu" / "notifybridge" / "ServerPolicy.java"
)
JAVA_HOME = Path(os.environ.get("JAVA_HOME") or (
    Path.home() / "Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home"
))
RETIRED_NODE_SERVER = ROOT / "server" / "server.js"


class AndroidServerPolicyTests(unittest.TestCase):
    def test_only_exact_official_https_base_is_accepted(self):
        harness = textwrap.dedent(
            """
            package com.zundu.notifybridge;

            public final class ServerPolicyHarness {
                public static void main(String[] args) {
                    String official = "https://example.com/xxzf";
                    if (!official.equals(ServerPolicy.requireOfficialBase(official))) {
                        throw new AssertionError("official base rejected");
                    }
                    String[] rejected = new String[] {
                        "http://example.com/xxzf",
                        "https://example.com:8443/xxzf",
                        "https://example.com:443/xxzf",
                        "https://example.com/xxzf/",
                        "https://example.com/XXZF",
                        "https://user@example.com/xxzf",
                        "https://example.com/xxzf?x=1",
                        "https://example.com/xxzf#fragment",
                        "https://example.com.evil.example/xxzf",
                        "https://例子.example/xxzf",
                        "HTTPS://EXAMPLE.COM/xxzf",
                        " https://example.com/xxzf "
                    };
                    for (String value : rejected) {
                        try {
                            ServerPolicy.requireOfficialBase(value);
                            throw new AssertionError("accepted: " + value);
                        } catch (IllegalArgumentException expected) {
                            // Expected.
                        }
                    }
                    if (!"https://example.com/xxzf/v1/notify".equals(
                            ServerPolicy.officialNotifyUrl())) {
                        throw new AssertionError("wrong notify URL");
                    }
                }
            }
            """
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            harness_path = root / "ServerPolicyHarness.java"
            harness_path.write_text(harness, encoding="utf-8")
            subprocess.run(
                [
                    str(JAVA_HOME / "bin" / "javac"),
                    "--release",
                    "8",
                    "-encoding",
                    "UTF-8",
                    "-d",
                    str(root),
                    str(ANDROID_SOURCE),
                    str(harness_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    str(JAVA_HOME / "bin" / "java"),
                    "-cp",
                    str(root),
                    "com.zundu.notifybridge.ServerPolicyHarness",
                ],
                check=True,
                capture_output=True,
                text=True,
            )


class ActiveTransportPolicyTests(unittest.TestCase):
    def test_clients_do_not_contain_remote_cleartext_fallbacks(self):
        active_files = [
            ROOT / "android" / "AndroidManifest.xml",
            ROOT / "android" / "src" / "com" / "zundu" / "notifybridge" / "Prefs.java",
            ROOT / "android" / "src" / "com" / "zundu" / "notifybridge" / "PairingClient.java",
            ROOT / "android" / "src" / "com" / "zundu" / "notifybridge" / "ServerClient.java",
            ROOT / "android" / "src" / "com" / "zundu" / "notifybridge" / "BridgeSender.java",
            ROOT / "server" / "mac_client.py",
            ROOT / "server" / "mac_receiver" / "Receiver.m",
            ROOT / "scripts" / "start_air_notifier.sh",
            ROOT / "windows" / "Forwarder.cs",
        ]
        forbidden = (
            "http://192.168.",
            "http://100.",
            'android:usesCleartextTraffic="true"',
        )
        violations = []
        for path in active_files:
            text = path.read_text("utf-8")
            for marker in forbidden:
                if marker in text:
                    violations.append(f"{path.relative_to(ROOT)}: {marker}")
        self.assertEqual([], violations)

    def test_active_legacy_paths_do_not_use_query_tokens(self):
        active_files = [
            ROOT / "scripts" / "push_to_phone.sh",
            ROOT / "server" / "public_ingress.py",
            ROOT / "server" / "server.py",
        ]
        forbidden = ("?token=", "X-XXZF-Token")
        violations = []
        for path in active_files:
            text = path.read_text("utf-8")
            for marker in forbidden:
                if marker in text:
                    violations.append(f"{path.relative_to(ROOT)}: {marker}")
        self.assertEqual([], violations)

    def test_public_proxy_has_exact_authenticated_self_revoke_route(self):
        text = (ROOT / "nginx" / "xxzf_public_routes.inc").read_text("utf-8")
        self.assertIn("location = /xxzf/v1/device/revoke", text)
        self.assertIn("proxy_pass http://127.0.0.1:8787/api/v1/device/revoke;", text)
        self.assertIn("proxy_set_header Authorization $http_authorization;", text)

    def test_public_proxy_has_exact_receiver_sender_revoke_route(self):
        text = (ROOT / "nginx" / "xxzf_public_routes.inc").read_text("utf-8")
        selector = "location = /xxzf/v1/receiver/senders/revoke {"
        self.assertEqual(1, text.count(selector))
        block = text.split(selector, 1)[1].split("\n    }", 1)[0]
        self.assertIn("if ($request_method != POST) { return 405; }", block)
        self.assertIn("client_max_body_size 4k;", block)
        self.assertIn(
            "proxy_pass http://127.0.0.1:8787/api/v1/receiver/senders/revoke;",
            block,
        )
        self.assertIn("proxy_set_header Authorization $http_authorization;", block)
        self.assertIn("access_log off;", block)
        self.assertNotIn("$request_uri", block)

        fallback = text.split("location ^~ /xxzf/ {", 1)[1].split(
            "\n    }", 1
        )[0]
        self.assertIn("return 404;", fallback)
        self.assertNotIn("location ^~ /xxzf/v1/receiver/", text)

    def test_legacy_proxy_explicitly_forwards_bearer_header(self):
        text = (ROOT / "nginx" / "xxzf_public_routes.inc").read_text("utf-8")
        legacy = text.split("location = /xxzf/notify {", 1)[1].split(
            "location = /xxzf/pair/start {", 1
        )[0]
        self.assertIn("proxy_set_header Authorization $http_authorization;", legacy)
        self.assertIn("access_log off;", legacy)

    def test_android_disconnect_revokes_server_credential_before_local_clear(self):
        client = (
            ROOT / "android" / "src" / "com" / "zundu" / "notifybridge"
            / "PairingClient.java"
        ).read_text("utf-8")
        activity = (
            ROOT / "android" / "src" / "com" / "zundu" / "notifybridge"
            / "PairActivity.java"
        ).read_text("utf-8")
        self.assertIn('"/v1/device/revoke"', client)
        self.assertIn("PairingClient.selfRevoke", activity)
        self.assertLess(
            activity.index("PairingClient.selfRevoke"),
            activity.index("Prefs.clearPairing", activity.index("PairingClient.selfRevoke")),
        )

    def test_xxzf_routes_have_one_project_owned_authoritative_include(self):
        routes = (ROOT / "nginx" / "xxzf_public_routes.inc").read_text("utf-8")
        for selector in (
            "location = /xxzf/notify {",
            "location = /xxzf/pair/start {",
            "location = /xxzf/v1/events {",
            "location = /xxzf/v1/device/revoke {",
            "location = /xxzf/v1/receiver/senders/revoke {",
            "location ^~ /xxzf/ {",
        ):
            self.assertEqual(1, routes.count(selector), selector)
        self.assertNotIn("proxy_add_x_forwarded_for", routes)
        self.assertNotIn("zundu/auth/check", routes)
        events = routes.split("location = /xxzf/v1/events {", 1)[1].split(
            "\n    }", 1
        )[0]
        self.assertIn("limit_conn zundu_conn_per_ip 4;", events)

    def test_node_server_is_a_fail_closed_non_listening_stub(self):
        source = RETIRED_NODE_SERVER.read_text("utf-8")
        for forbidden in (
            "createServer",
            ".listen(",
            "searchParams",
            "x-xxzf-token",
            "notify-token.txt",
            "XXZF_TOKEN",
            "require('http')",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("retired; use server.py", source)
        self.assertIn("process.exit(1)", source)

    def test_node_stub_exits_nonzero_without_listening(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node runtime is not installed in this environment")
        completed = subprocess.run(
            [node, str(RETIRED_NODE_SERVER)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(1, completed.returncode)
        self.assertIn("retired; use server.py", completed.stderr)
        self.assertEqual("", completed.stdout)


class RetiredIngressServiceTests(unittest.TestCase):
    def test_unused_8790_launchd_job_is_fail_closed(self):
        path = (
            ROOT
            / "deploy"
            / "launchd"
            / "com.zundu.xxzf.ingress.plist.example"
        )
        with path.open("rb") as handle:
            job = plistlib.load(handle)
        self.assertTrue(job.get("Disabled"))
        self.assertFalse(job.get("RunAtLoad"))
        self.assertFalse(job.get("KeepAlive"))
        self.assertEqual(["/usr/bin/false"], job.get("ProgramArguments"))
        serialized = path.read_text("utf-8")
        self.assertNotIn("public_ingress.py", serialized)
        self.assertNotIn("8790", serialized)


if __name__ == "__main__":
    unittest.main()
