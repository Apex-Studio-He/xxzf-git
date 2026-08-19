#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path


PUBLIC_KEY_DER_BASE64 = (
    "MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEAvtEyLwpBwuLl3beIHljcyva1LI9BStCnW7ml3XZllEHsTRU2DJ/gb8D6ElvocBr0BjKxtgMJAb/RQoh7AL+U8EZ+QTooT6DZC7tMxxu4C0J9Mg9UFAIA8WVdXEOsSoqjeXYanMYZDiZ21SrklCl5mIYsL5f6wOnSBd+Oy18yUiaCX87YirxkfBH3ooNEDXAT61tc9ieNBFo4Wr4/2yeB7DC+xFAzKBNMwQBzRqEwNkD/w0kUh/k0zs0VDz35RwNoI46XzC6e8UUVwKbNg6GO/9dvtpgyZDEqP1Ldr3T3c3hHLDKmiaklYexO9P43vO1exff2EBt4oTU0NBdUZvyvkFhZQjGWDqAycpdgdzVCRJcCFHBVBvEHWeTCXbaJyBLAv41SJ4a92iiwj3+1qw5yaVIWw9e8aGBVXTu7G8cMU6r5/XN/UF+u449fVneVCMQZ+wDfwrc0h29IY+y+RzMHQrz9yHkv1YiFmL/00K/c4Bpgu0TeurMI33M/W3u1bTJ/AgMBAAE="
)
FIELDS = (
    "schema", "channel", "platform", "versionCode", "version", "url",
    "sha256", "size", "publishedAt", "notes", "keyId",
)
PUBLIC_BASE = "https://updates.example.com/downloads/forwarder/test"
MAX_VERSION_CODE = (1 << 63) - 1
PLATFORMS = {
    "android": ("apk", 128 * 1024 * 1024),
    "macos": ("dmg", 256 * 1024 * 1024),
    "windows": ("exe", 128 * 1024 * 1024),
}
VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}(?:-[A-Za-z0-9.]+)?$")


def canonical(values):
    return "\n".join(str(values[field]) for field in FIELDS).encode("utf-8")


def verify(manifest_path, package_root):
    manifest = json.loads(manifest_path.read_text("utf-8"))
    expected = set(FIELDS) | {"signature"}
    if set(manifest) != expected:
        raise ValueError("manifest fields do not match the signed schema")
    if manifest["schema"] != 1 or manifest["channel"] != "test":
        raise ValueError("manifest identity is invalid")
    if manifest["keyId"] != "8545bd8392ab5de2":
        raise ValueError("manifest key id is invalid")
    platform = manifest["platform"]
    if platform not in PLATFORMS:
        raise ValueError("manifest platform is invalid")
    if (not isinstance(manifest["versionCode"], int)
            or isinstance(manifest["versionCode"], bool)
            or not 0 < manifest["versionCode"] <= MAX_VERSION_CODE):
        raise ValueError("manifest version code is invalid")
    version = manifest["version"]
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise ValueError("manifest version is invalid")
    extension, max_size = PLATFORMS[platform]
    package_name = f"forwarder-{platform}-{version}-test.{extension}"
    if manifest["url"] != f"{PUBLIC_BASE}/{package_name}":
        raise ValueError("package name does not match manifest platform")
    if not isinstance(manifest["size"], int) or isinstance(manifest["size"], bool) or not 0 < manifest["size"] <= max_size:
        raise ValueError("package size is outside the allowed range")
    if not isinstance(manifest["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", manifest["sha256"]):
        raise ValueError("package digest is invalid")
    candidate = package_root / package_name
    if candidate.is_symlink():
        raise ValueError("package path is unsafe")
    package = candidate.resolve(strict=True)
    if package.parent != package_root.resolve() or not package.is_file():
        raise ValueError("package path is unsafe")
    digest = hashlib.sha256()
    with package.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if package.stat().st_size != manifest["size"] or digest.hexdigest() != manifest["sha256"]:
        raise ValueError("package size or digest mismatch")

    with tempfile.TemporaryDirectory() as temporary:
        temporary = Path(temporary)
        der = temporary / "public.der"
        pem = temporary / "public.pem"
        signature = temporary / "signature.bin"
        der.write_bytes(base64.b64decode(PUBLIC_KEY_DER_BASE64, validate=True))
        signature.write_bytes(base64.b64decode(manifest["signature"], validate=True))
        subprocess.run(
            ["/usr/bin/openssl", "pkey", "-pubin", "-inform", "DER", "-in", str(der), "-out", str(pem)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        verified = subprocess.run(
            ["/usr/bin/openssl", "dgst", "-sha256", "-verify", str(pem), "-signature", str(signature)],
            input=canonical(manifest), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if verified.returncode != 0:
            raise ValueError("manifest signature verification failed")
    return manifest, package


def main():
    parser = argparse.ArgumentParser(description="Verify a published XXZF update without private keys")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--package-root", type=Path)
    args = parser.parse_args()
    root = args.package_root or args.manifest.parent
    manifest, package = verify(args.manifest.resolve(strict=True), root.resolve(strict=True))
    print(json.dumps({
        "ok": True,
        "platform": manifest["platform"],
        "version": manifest["version"],
        "package": str(package),
        "sha256": manifest["sha256"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
