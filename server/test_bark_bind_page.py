import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "public" / "bark" / "index.html"
SCRIPT = ROOT / "public" / "bark" / "bind.js"
STYLE = ROOT / "public" / "bark" / "bind.css"
ROUTES = ROOT / "nginx" / "xxzf_public_routes.inc"
SERVER = ROOT / "server" / "server.py"


class BarkBindingPagePolicyTests(unittest.TestCase):
    def test_page_is_private_accessible_and_title_only(self):
        page = PAGE.read_text(encoding="utf-8")
        self.assertIn("noindex,nofollow,noarchive", page)
        self.assertIn('label for="barkUrl"', page)
        self.assertIn('role="status"', page)
        self.assertIn("只显示来源应用和通知标题，不发送正文", page)
        self.assertNotIn("localStorage", page)
        self.assertNotIn("sessionStorage", page)

    def test_script_erases_fragment_and_posts_only_to_exact_claim_api(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("window.history.replaceState", script)
        self.assertIn('fetch("/xxzf/v1/bark/enroll/claim"', script)
        self.assertIn('credentials: "omit"', script)
        self.assertIn('parsed.hostname.toLowerCase() === "api.day.app"', script)
        self.assertNotIn("localStorage", script)
        self.assertNotIn("sessionStorage", script)
        self.assertNotIn("console.", script)

    def test_exact_static_routes_precede_deny_by_default_prefix(self):
        routes = ROUTES.read_text(encoding="utf-8")
        for path in (
            "/xxzf/bark", "/xxzf/bark/", "/xxzf/bark/index.html",
            "/xxzf/bark/bind.css", "/xxzf/bark/bind.js",
        ):
            self.assertEqual(1, routes.count(f"location = {path} {{"))
        self.assertLess(routes.index("location = /xxzf/bark/ {"), routes.index("location ^~ /xxzf/ {"))
        self.assertIn("alias /opt/xxzf/public/bark/;", routes)
        self.assertIn("index index.html;", routes)
        self.assertIn("frame-ancestors 'none'", routes)
        self.assertIn('X-Robots-Tag "noindex, nofollow, noarchive"', routes)

    def test_server_generates_the_new_binding_origin(self):
        source = SERVER.read_text(encoding="utf-8")
        self.assertIn("https://example.com/xxzf/bark/", source)

    def test_mobile_layout_has_no_fixed_width_larger_than_viewport(self):
        style = STYLE.read_text(encoding="utf-8")
        self.assertIn("min-width: 320px", style)
        self.assertIn("width: min(100%, 560px)", style)
        self.assertIn("@media (max-width: 520px)", style)


if __name__ == "__main__":
    unittest.main()
