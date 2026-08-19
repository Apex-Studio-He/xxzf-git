#!/usr/bin/env python3
"""Validation shared by the Codex preflight and isolated build tools."""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


ALLOWED_TARGETS = frozenset({"server", "android", "macos", "windows"})
ALLOWED_KEYS = frozenset({
    "public_base",
    "update_base",
    "targets",
    "build_mode",
    "server_platform",
})
PLACEHOLDER_ZONES = ("example.com", "example.net", "example.org")


class RequestError(ValueError):
    """A safe, user-facing validation failure."""


@dataclass(frozen=True)
class BuildRequest:
    public_base: str
    public_origin: str
    public_host: str
    update_base: str
    update_host: str
    targets: tuple[str, ...]
    build_mode: str
    server_platform: str


def _validated_url(value: Any, *, label: str, required_path: str) -> tuple[str, str, str]:
    if not isinstance(value, str) or not value.strip():
        raise RequestError(f"{label} must be a non-empty HTTPS URL")
    if value != value.strip():
        raise RequestError(f"{label} must not contain leading or trailing spaces")
    parsed = urlsplit(value)
    if parsed.scheme != "https":
        raise RequestError(f"{label} must start with https://")
    if parsed.username is not None or parsed.password is not None:
        raise RequestError(f"{label} must not contain a username or password")
    if parsed.query or parsed.fragment:
        raise RequestError(f"{label} must not contain a query or fragment")
    try:
        port = parsed.port
    except ValueError as exc:
        raise RequestError(f"{label} contains an invalid port") from exc
    if port not in (None, 443):
        raise RequestError(f"{label} must use the default HTTPS port 443")
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host or "." not in host:
        raise RequestError(f"{label} must use a fully qualified domain name")
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise RequestError(f"{label} contains an invalid domain name") from exc
    if len(ascii_host) > 253 or any(
        not part or len(part) > 63 or part.startswith("-") or part.endswith("-")
        for part in ascii_host.split(".")
    ):
        raise RequestError(f"{label} contains an invalid domain name")
    if parsed.path.rstrip("/") != required_path:
        raise RequestError(f"{label} path must be exactly {required_path}")
    try:
        address = ipaddress.ip_address(ascii_host)
    except ValueError:
        address = None
    if address is not None:
        raise RequestError(f"{label} must use a domain with a trusted HTTPS certificate, not an IP")
    if (
        any(ascii_host == zone or ascii_host.endswith("." + zone) for zone in PLACEHOLDER_ZONES)
        or ascii_host.endswith((".example", ".invalid", ".test"))
    ):
        raise RequestError(f"{label} still uses a placeholder domain; replace it with your domain")
    normalized = f"https://{ascii_host}{required_path}"
    return normalized, f"https://{ascii_host}", ascii_host


def load_request(path: Path | str) -> BuildRequest:
    request_path = Path(path).expanduser()
    try:
        raw = json.loads(request_path.read_text("utf-8"))
    except FileNotFoundError as exc:
        raise RequestError(
            f"request file not found: {request_path}; copy codex/request.example.json first"
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RequestError(f"request file is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise RequestError("request root must be a JSON object")
    unknown = sorted(set(raw) - ALLOWED_KEYS)
    if unknown:
        raise RequestError(f"unknown request field(s): {', '.join(unknown)}")

    public_base, public_origin, public_host = _validated_url(
        raw.get("public_base"), label="public_base", required_path="/xxzf"
    )
    update_base, _, update_host = _validated_url(
        raw.get("update_base"),
        label="update_base",
        required_path="/downloads/forwarder/test",
    )

    targets = raw.get("targets")
    if not isinstance(targets, list) or not targets:
        raise RequestError("targets must be a non-empty JSON list")
    if any(not isinstance(item, str) for item in targets):
        raise RequestError("every targets item must be a string")
    duplicates = sorted({item for item in targets if targets.count(item) > 1})
    invalid = sorted(set(targets) - ALLOWED_TARGETS)
    if invalid:
        raise RequestError(f"unsupported target(s): {', '.join(invalid)}")
    if duplicates:
        raise RequestError(f"duplicate target(s): {', '.join(duplicates)}")

    build_mode = raw.get("build_mode", "debug")
    if build_mode not in {"debug", "release"}:
        raise RequestError("build_mode must be debug or release")
    server_platform = raw.get("server_platform", "linux")
    if server_platform not in {"linux", "macos"}:
        raise RequestError("server_platform must be linux or macos")
    return BuildRequest(
        public_base=public_base,
        public_origin=public_origin,
        public_host=public_host,
        update_base=update_base,
        update_host=update_host,
        targets=tuple(targets),
        build_mode=build_mode,
        server_platform=server_platform,
    )
