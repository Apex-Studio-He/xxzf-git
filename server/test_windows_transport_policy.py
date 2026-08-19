#!/usr/bin/env python3
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FORWARDER = ROOT / "windows" / "Forwarder.cs"
OFFICIAL_BASE = "https://example.com/xxzf"


class WindowsTransportPolicyTests(unittest.TestCase):
    def setUp(self):
        self.source = FORWARDER.read_text("utf-8")

    def test_forwarder_uses_only_the_exact_official_https_base(self):
        self.assertIn(
            f'private const string OfficialServer = "{OFFICIAL_BASE}";',
            self.source,
        )
        self.assertNotIn("http://", self.source)
        self.assertNotIn("defaultServers", self.source)
        self.assertIn(
            "if (!String.Equals(server, OfficialServer, StringComparison.Ordinal))",
            self.source,
        )
        self.assertIn("return new string[] { OfficialServer };", self.source)

    def test_startup_migrates_only_the_saved_server_base(self):
        expected = """
            if (!String.Equals(state.ServerBase, OfficialServer, StringComparison.Ordinal))
            {
                state.ServerBase = OfficialServer;
                StateStore.Save(state);
            }
        """
        self.assertIn(expected, self.source)

    def test_all_http_clients_refuse_redirects(self):
        self.assertIn(
            "HttpClientHandler handler = new HttpClientHandler { AllowAutoRedirect = false };",
            self.source,
        )
        self.assertNotIn("new HttpClient()", self.source)
        self.assertIn(
            "using (HttpClient client = NewClient(bearer, Timeout.InfiniteTimeSpan))",
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
