#!/usr/bin/env python3
"""Fail closed on common secrets and machine-specific identifiers."""

import hashlib
import ipaddress
import re
import sys
import zipfile
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKIP_PARTS = {".git", "build", "dist", "node_modules", "__pycache__"}
SKIP_NAMES = {
    "task_plan.md", "findings.md", "progress.md", "request.local.json",
}
BINARY_SUFFIXES = {
    ".apk", ".dmg", ".exe", ".ico", ".jar", ".jpg", ".jpeg", ".png",
    ".p12", ".pfx", ".zip",
}
APPROVED_BINARY_SHA256 = {
    "android/libs/zxing-core-3.5.4.jar": "71de5d89341b5fcf5dd89da7f44e84d825d0e084cdf3ec77c9abe26b0f0ceb13",
    "server/mac_notifier/AppIcon-source.png": "6fe070103faaab1cd211a7802ed7ea57d4b6db38af19ca5b5701116f197fdf02",
    "server/mac_notifier/AppIcon-v3.png": "ae4cafacc1c1be0c4980468f503dd283e0f6e0c4a5b91f901ec5b5c3aabc7d1f",
    "windows/Forwarder.ico": "15f61d71bfb0347030232fd53bbaf67217828daa9a97320e958ce9642b5b0ffb",
    "windows/转发.ico": "6c7054602312c259a665ffb34a209c961e907bfab2d6706d80399de60ab898bd",
}
ALLOWED_EMAIL_DOMAINS = {"example.com", "example.invalid"}
ALLOWED_URL_SUFFIXES = (
    ".example", ".invalid", "example.com", "api.day.app", "apple.com",
    "adoptium.net", "android.com", "apache.org", "day.app",
    "digicert.com", "djangoproject.com", "google.com",
    "github.com", "ietf.org", "microsoft.com", "opensource.org",
    "iptc.org", "palletsprojects.com", "pypi.org", "sourceforge.net",
    "ssl.com", "strokescribe.com", "swtch.com", "w3.org", "wikipedia.org",
)
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:gh[opsu]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})\b"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "generic password assignment": re.compile(
        r"(?im)^\s*(?:password|passwd|apple[_ -]?id[_ -]?password)\s*[:=]\s*"
        r"(?!<|\$\{|example|change[-_ ]?me)[^#\s][^#\r\n]{5,}$"
    ),
}
URL_RE = re.compile(r"https?://([A-Za-z0-9._:%@\[\]{}-]+)", re.IGNORECASE)
EMAIL_RE = re.compile(r"(?<![\w.+-])([\w.+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,}))")
MAC_USER_RE = re.compile(r"/Users/([^/\s\"']+)")
WIN_USER_RE = re.compile(r"[A-Za-z]:\\Users\\([^\\\s\"']+)", re.IGNORECASE)
IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
ASCII_STRING_RE = re.compile(rb"[\x20-\x7e]{8,}")
UTF16LE_STRING_RE = re.compile(rb"(?:[\x20-\x7e]\x00){8,}")


def decoded_strings(data):
    values = []
    for raw in ASCII_STRING_RE.findall(data):
        values.append(raw.decode("ascii", "ignore"))
    for raw in UTF16LE_STRING_RE.findall(data):
        values.append(raw.decode("utf-16le", "ignore"))
    return "\n".join(values)


def png_metadata(data):
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ""
    offset = 8
    values = []
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset:offset + 4], "big")
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        if offset + 12 + length > len(data):
            break
        if kind in {b"tEXt", b"eXIf"}:
            values.append(decoded_strings(payload))
        elif kind == b"zTXt":
            separator = payload.find(b"\x00")
            if separator >= 0:
                values.append(decoded_strings(payload[:separator]))
                try:
                    values.append(zlib.decompress(payload[separator + 2:]).decode("utf-8", "ignore"))
                except zlib.error:
                    pass
        elif kind == b"iTXt":
            parts = payload.split(b"\x00", 5)
            values.append(decoded_strings(parts[0]))
            if len(parts) == 6:
                text = parts[5]
                if parts[1] == b"\x01":
                    try:
                        text = zlib.decompress(text)
                    except zlib.error:
                        text = b""
                values.append(text.decode("utf-8", "ignore"))
        offset += 12 + length
        if kind == b"IEND":
            break
    return "\n".join(value for value in values if value)


def zip_metadata(path):
    values = []
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                values.append(info.filename)
                suffix = Path(info.filename).suffix.lower()
                basename = Path(info.filename).name.lower()
                if (
                    info.file_size <= 2 * 1024 * 1024
                    and (suffix in {".mf", ".txt", ".md", ".json", ".xml", ".properties"}
                         or basename in {"license", "notice"})
                ):
                    values.append(archive.read(info).decode("utf-8", "ignore"))
    except (OSError, zipfile.BadZipFile):
        return ""
    return "\n".join(values)


def binary_metadata(path):
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    values = [decoded_strings(data)]
    if path.suffix.lower() == ".png":
        values.append(png_metadata(data))
    if path.suffix.lower() in {".jar", ".zip", ".apk"}:
        values.append(zip_metadata(path))
    combined = "\n".join(value for value in values if value)
    # C2PA certificate URLs can be immediately followed by printable ASN.1
    # length bytes. Normalize those public provenance endpoints before the URL
    # host check; all other metadata remains fully scanned.
    combined = re.sub(
        r"https?://(?:crt-c2pa|ocsp-c2pa)\.ssl\.com[^\s]*",
        "https://ssl.com",
        combined,
        flags=re.IGNORECASE,
    )
    return combined


def binary_inventory_violations():
    violations = []
    seen = set()
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in BINARY_SUFFIXES:
            continue
        relative = path.relative_to(ROOT)
        if any(part in SKIP_PARTS for part in relative.parts):
            continue
        name = relative.as_posix()
        seen.add(name)
        expected = APPROVED_BINARY_SHA256.get(name)
        if expected is None:
            violations.append(f"{name}: unreviewed binary asset")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            violations.append(f"{name}: binary asset changed and requires visual review")
    for name in sorted(set(APPROVED_BINARY_SHA256) - seen):
        violations.append(f"{name}: approved binary asset is missing")
    return violations


def scan_payloads():
    for path in ROOT.rglob("*"):
        if (
            not path.is_file()
            or path.name in SKIP_NAMES
            or path.resolve() == Path(__file__).resolve()
        ):
            continue
        if any(part in SKIP_PARTS for part in path.relative_to(ROOT).parts):
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            metadata = binary_metadata(path)
            if metadata:
                yield path, metadata
            continue
        try:
            yield path, path.read_text("utf-8")
        except UnicodeDecodeError:
            continue


def allowed_host(raw):
    raw = raw.rstrip("`'\".,;:。；，、")
    host = raw.rsplit("@", 1)[-1].split(":", 1)[0].rstrip(".").lower()
    if "{" in host or "}" in host:
        return True
    if host in {"localhost", "127.0.0.1", "::1", "%s%s", "100", "192.168"}:
        return True
    try:
        address = ipaddress.ip_address(host)
        return (
            address.is_loopback
            or address in ipaddress.ip_network("192.0.2.0/24")
            or address in ipaddress.ip_network("198.51.100.0/24")
            or address in ipaddress.ip_network("203.0.113.0/24")
            or address == ipaddress.ip_address("100.64.0.10")
        )
    except ValueError:
        pass
    return any(host == suffix.lstrip(".") or host.endswith(suffix) for suffix in ALLOWED_URL_SUFFIXES)


def main():
    violations = binary_inventory_violations()
    for path, text in scan_payloads():
        relative = path.relative_to(ROOT)
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                violations.append(f"{relative}: possible {label}")
        for match in EMAIL_RE.finditer(text):
            local = match.group(1).split("@", 1)[0]
            domain = match.group(2).lower()
            prefix = text[max(0, match.start() - 8):match.start()]
            if (
                domain not in ALLOWED_EMAIL_DOMAINS
                and not domain.endswith("day.app")
                and not domain[0].isdigit()
                and "://" not in prefix
                and local
            ):
                violations.append(f"{relative}: non-example email address")
        for pattern in (MAC_USER_RE, WIN_USER_RE):
            for match in pattern.finditer(text):
                if match.group(1).lower() not in {"tester", "example", "username"}:
                    violations.append(f"{relative}: machine-specific user path")
        for match in URL_RE.finditer(text):
            if not allowed_host(match.group(1)):
                violations.append(f"{relative}: unapproved URL host {match.group(1)}")
        for candidate in IPV4_RE.findall(text):
            try:
                address = ipaddress.ip_address(candidate)
            except ValueError:
                continue
            allowed = (
                address.is_loopback
                or address in ipaddress.ip_network("192.0.2.0/24")
                or address in ipaddress.ip_network("198.51.100.0/24")
                or address in ipaddress.ip_network("203.0.113.0/24")
                or address == ipaddress.ip_address("100.64.0.10")
            )
            rfc1918 = any(address in network for network in (
                ipaddress.ip_network("10.0.0.0/8"),
                ipaddress.ip_network("172.16.0.0/12"),
                ipaddress.ip_network("192.168.0.0/16"),
            ))
            if rfc1918 and not allowed:
                violations.append(f"{relative}: non-documentation private IP address")

    unique = sorted(set(violations))
    if unique:
        print("PRIVACY_SCAN_FAILED", file=sys.stderr)
        for item in unique:
            print(f"- {item}", file=sys.stderr)
        return 1
    print("PRIVACY_SCAN_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
