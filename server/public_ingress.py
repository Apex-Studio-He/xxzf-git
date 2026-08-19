#!/usr/bin/env python3
import json
import os
import urllib.parse
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 8790
BACKEND = "http://127.0.0.1:8787/api/notify"
MAX_BODY = 512 * 1024
MAX_BACKEND_RESPONSE = 64 * 1024
PUBLIC_ORIGIN = os.environ.get(
    "XXZF_PUBLIC_ORIGIN", "https://example.com:8443"
).rstrip("/")
PUBLIC_HOST = (urllib.parse.urlparse(PUBLIC_ORIGIN).hostname or "").lower()
ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", PUBLIC_HOST, "www." + PUBLIC_HOST}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


BACKEND_OPENER = urllib.request.build_opener(NoRedirect())


def normalized_host(value):
    try:
        parsed = urllib.parse.urlsplit("//" + str(value or "").strip())
        if parsed.username is not None or parsed.password is not None or parsed.path:
            return ""
        parsed.port
        return (parsed.hostname or "").rstrip(".").lower()
    except (TypeError, ValueError):
        return ""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def send_body(self, status, body, content_type="application/json; charset=utf-8"):
        raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)

    def trusted_request_host(self):
        if normalized_host(self.headers.get("Host")) in ALLOWED_HOSTS:
            return True
        self.send_body(421, {"ok": False, "error": "misdirected request"})
        return False

    def trusted_origin(self, required=False):
        origin = self.headers.get("Origin", "").strip().rstrip("/")
        if (not origin and not required) or origin == PUBLIC_ORIGIN:
            return True
        self.send_body(403, {"ok": False, "error": "origin not allowed"})
        return False

    def do_GET(self):
        if not self.trusted_request_host():
            return
        self.send_body(404, {"ok": False, "error": "not found"})

    def do_OPTIONS(self):
        if not self.trusted_request_host() or not self.trusted_origin(required=True):
            return
        if urllib.parse.urlparse(self.path).path != "/xxzf/notify":
            self.send_body(404, {"ok": False, "error": "not found"})
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", PUBLIC_ORIGIN)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "authorization, content-type")
        self.send_header("Access-Control-Allow-Methods", "POST,OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        if not self.trusted_request_host() or not self.trusted_origin():
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/xxzf/notify":
            self.send_body(404, {"ok": False, "error": "not found"})
            return
        if parsed.query:
            self.send_body(400, {"ok": False, "error": "query parameters are not allowed"})
            return

        if self.headers.get("Transfer-Encoding"):
            self.send_body(400, {"ok": False, "error": "transfer encoding is not supported"})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self.send_body(415, {"ok": False, "error": "application/json required"})
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.send_body(400, {"ok": False, "error": "bad content length"})
            return
        if length < 1:
            self.send_body(400, {"ok": False, "error": "bad content length"})
            return
        if length > MAX_BODY:
            self.send_body(413, {"ok": False, "error": "request body too large"})
            return

        authorization = self.headers.get("Authorization", "").strip()
        if not authorization.lower().startswith("bearer ") or not authorization[7:].strip():
            self.send_body(401, {"ok": False, "error": "unauthorized"})
            return

        body = self.rfile.read(length)
        if len(body) != length:
            self.send_body(400, {"ok": False, "error": "incomplete request body"})
            return
        headers = {"Content-Type": "application/json", "Authorization": authorization}
        request = urllib.request.Request(
            BACKEND,
            data=body,
            method="POST",
            headers=headers,
        )
        try:
            with BACKEND_OPENER.open(request, timeout=12) as response:
                self.send_body(
                    response.status,
                    response.read(MAX_BACKEND_RESPONSE),
                    "application/json; charset=utf-8",
                )
        except urllib.error.HTTPError as exc:
            try:
                self.send_body(
                    exc.code,
                    exc.read(MAX_BACKEND_RESPONSE),
                    "application/json; charset=utf-8",
                )
            finally:
                exc.close()
        except Exception:
            self.send_body(502, {"ok": False, "error": "upstream unavailable"})

    def log_message(self, fmt, *args):
        # Request paths can contain accidental credentials. Keep ingress logs
        # deliberately content-free.
        print("%s - request completed" % self.address_string(), flush=True)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"XXZF public ingress listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
