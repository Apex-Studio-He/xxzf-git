#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = 1
CHANNEL = "test"
PUBLIC_BASE = "https://updates.example.com/downloads/forwarder/test"
KEY_ID = "8545bd8392ab5de2"
MAX_VERSION_CODE = (1 << 63) - 1
PLATFORMS = {
    "android": ("apk", 128 * 1024 * 1024),
    "macos": ("dmg", 256 * 1024 * 1024),
    "windows": ("exe", 128 * 1024 * 1024),
}
VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}(?:-[A-Za-z0-9.]+)?$")


def canonical_payload(values):
    fields = (
        "schema",
        "channel",
        "platform",
        "versionCode",
        "version",
        "url",
        "sha256",
        "size",
        "publishedAt",
        "notes",
        "keyId",
    )
    return ("\n".join(str(values[field]) for field in fields)).encode("utf-8")


def require_private_file(path):
    path = path.expanduser()
    if path.is_symlink():
        raise ValueError("update private key must not be a symbolic link")
    path = path.resolve(strict=True)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("update private key must be a regular file")
    if info.st_mode & 0o077:
        raise ValueError("update private key permissions must be 0600")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise ValueError("update private key must be owned by the current user")
    return path


def require_package(path, max_size):
    path = path.expanduser()
    if path.is_symlink():
        raise ValueError("package must not be a symbolic link")
    path = path.resolve(strict=True)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("package must be a regular file")
    if info.st_size <= 0 or info.st_size > max_size:
        raise ValueError("package size is outside the allowed range")
    return path, info.st_size


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.digest()


def atomic_copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.parent.is_symlink():
        raise ValueError("output directory must not be a symbolic link")
    fd, temporary = tempfile.mkstemp(prefix=".update-", dir=str(destination.parent))
    os.close(fd)
    temporary = Path(temporary)
    try:
        shutil.copyfile(source, temporary)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.is_symlink():
                raise ValueError("immutable package destination must not be a symbolic link")
            destination_info = destination.stat()
            if not stat.S_ISREG(destination_info.st_mode):
                raise ValueError("immutable package destination must be a regular file")
            temporary_digest = sha256_file(temporary)
            destination_digest = sha256_file(destination)
            if (destination_info.st_size != temporary.stat().st_size
                    or destination_digest != temporary_digest):
                raise ValueError("immutable package collision: existing version has different bytes")
        else:
            directory_fd = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(values, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".manifest-", dir=str(destination.parent))
    temporary = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(values, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def build_manifest(platform, version_code, version, notes, package, private_key, output_root):
    if platform not in PLATFORMS:
        raise ValueError("unsupported platform")
    if version_code <= 0 or version_code > MAX_VERSION_CODE:
        raise ValueError("version code must be positive")
    if not VERSION_RE.fullmatch(version):
        raise ValueError("invalid version")
    notes = notes.strip()
    if not notes or len(notes) > 200 or "\n" in notes or "\r" in notes:
        raise ValueError("notes must be one non-empty line of at most 200 characters")

    extension, max_size = PLATFORMS[platform]
    package, package_size = require_package(package, max_size)
    private_key = require_private_file(private_key)
    output_root = output_root.expanduser()
    if output_root.is_symlink():
        raise ValueError("output root must not be a symbolic link")
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    output_info = output_root.stat()
    if not stat.S_ISDIR(output_info.st_mode):
        raise ValueError("output root must be a directory")
    if hasattr(os, "getuid") and output_info.st_uid != os.getuid():
        raise ValueError("output root must be owned by the current user")

    package_name = f"forwarder-{platform}-{version}-test.{extension}"
    package_output = output_root / package_name
    atomic_copy(package, package_output)
    digest = sha256_file(package_output).hex()
    published_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    manifest = {
        "schema": SCHEMA,
        "channel": CHANNEL,
        "platform": platform,
        "versionCode": version_code,
        "version": version,
        "url": f"{PUBLIC_BASE}/{package_name}",
        "sha256": digest,
        "size": package_size,
        "publishedAt": published_at,
        "notes": notes,
        "keyId": KEY_ID,
    }
    completed = subprocess.run(
        ["/usr/bin/openssl", "dgst", "-sha256", "-sign", str(private_key)],
        input=canonical_payload(manifest),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    manifest["signature"] = base64.b64encode(completed.stdout).decode("ascii")
    atomic_json(manifest, output_root / f"{platform}.json")
    return manifest, package_output


def parse_args():
    parser = argparse.ArgumentParser(description="Publish a signed XXZF test update")
    parser.add_argument("--platform", required=True, choices=sorted(PLATFORMS))
    parser.add_argument("--version-code", required=True, type=int)
    parser.add_argument("--version", required=True)
    parser.add_argument("--notes", required=True)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument(
        "--private-key",
        type=Path,
        default=Path.home() / "Library/Application Support/XXZF/update-signing/update-private.pem",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    manifest, package = build_manifest(
        args.platform,
        args.version_code,
        args.version,
        args.notes,
        args.package,
        args.private_key,
        args.output_root,
    )
    print(json.dumps({
        "ok": True,
        "platform": manifest["platform"],
        "version": manifest["version"],
        "sha256": manifest["sha256"],
        "package": str(package),
        "manifest": str(args.output_root / f"{args.platform}.json"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
