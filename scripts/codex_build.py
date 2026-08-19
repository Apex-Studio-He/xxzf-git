#!/usr/bin/env python3
"""Build a configured XXZF copy without writing deployment URLs into source."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from codex_request import BuildRequest, RequestError, load_request


ROOT = Path(__file__).resolve().parent.parent
SOURCE_ENTRIES = (
    "android", "server", "windows", "scripts", "public", "nginx", "deploy",
    "docs", "test_source", ".env.example", "LICENSE", "THIRD_PARTY_NOTICES.md",
)
SKIP_NAMES = frozenset({
    ".git", ".DS_Store", ".planning", "__pycache__", "build", "bin", "obj",
    "dist", "安装包", "backups", "request.local.json", "task_plan.md",
    "findings.md", "progress.md", "server-data", "notification_archive",
    "diagnostics",
})
SKIP_SUFFIXES = (
    ".apk", ".dmg", ".exe", ".msi", ".p12", ".pfx", ".pem", ".key",
    ".keystore", ".jks", ".mobileprovision", ".sqlite3", ".log", ".pid",
)
TEXT_SUFFIXES = frozenset({
    ".css", ".cs", ".example", ".h", ".html", ".java", ".js", ".json",
    ".m", ".md", ".plist", ".ps1", ".py", ".sh", ".xml",
})


class BuildError(RuntimeError):
    pass


def ignored(_directory: str, names: list[str]) -> set[str]:
    return {
        name for name in names
        if name in SKIP_NAMES or name.lower().endswith(SKIP_SUFFIXES)
    }


def assert_no_symlinks(path: Path) -> None:
    candidates = [path]
    if path.is_dir():
        candidates.extend(path.rglob("*"))
    for candidate in candidates:
        if candidate.is_symlink():
            raise BuildError(f"refusing to copy symbolic link: {candidate.relative_to(ROOT)}")


def copy_clean_source(destination: Path) -> None:
    for relative in SOURCE_ENTRIES:
        source = ROOT / relative
        if not source.exists():
            raise BuildError(f"required source path is missing: {relative}")
        assert_no_symlinks(source)
        target = destination / relative
        if source.is_dir():
            shutil.copytree(source, target, ignore=ignored)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def configure_copy(root: Path, request: BuildRequest) -> int:
    replacements = (
        ("https://updates.example.com/downloads/forwarder/test", request.update_base),
        ("updates.example.com", request.update_host),
        ("https://example.com/xxzf", request.public_base),
    )
    changed = 0
    for top in ("android", "server", "windows", "scripts", "deploy", "nginx"):
        for path in (root / top).rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                original = path.read_text("utf-8")
            except UnicodeDecodeError:
                continue
            configured = original
            for old, new in replacements:
                configured = configured.replace(old, new)
            if configured != original:
                path.write_text(configured, encoding="utf-8")
                changed += 1
    origin_files = (
        ".env.example",
        "server/server.py",
        "server/public_ingress.py",
        "deploy/launchd/com.zundu.xxzf.server.plist.example",
    )
    for relative in origin_files:
        path = root / relative
        original = path.read_text("utf-8")
        configured = original
        configured = configured.replace("https://example.com:8443", request.public_origin)
        configured = configured.replace("https://example.com", request.public_origin)
        path.write_text(configured, encoding="utf-8")
        changed += configured != original
    if changed < 10:
        raise BuildError("configuration changed too few files; source layout may be incompatible")
    runtime_expectations = {
        "android/src/com/zundu/notifybridge/ServerPolicy.java": request.public_base,
        "android/src/com/zundu/notifybridge/UpdateSecurity.java": request.update_base,
        "server/server.py": request.public_base,
        "server/mac_receiver/Receiver.m": request.public_base,
        "server/mac_receiver/UpdateManager.m": request.update_base,
        "windows/Forwarder.cs": request.public_base,
        "windows/Updater.cs": request.update_base,
    }
    for relative, expected in runtime_expectations.items():
        text = (root / relative).read_text("utf-8")
        if expected not in text:
            raise BuildError(f"configured endpoint was not written to {relative}")
    metadata = {
        "public_base": request.public_base,
        "update_base": request.update_base,
        "targets": request.targets,
        "build_mode": request.build_mode,
        "server_platform": request.server_platform,
    }
    (root / "codex-build-request.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return changed


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    print(f"\n==> {' '.join(command)}", flush=True)
    result = subprocess.run(command, cwd=cwd, env=env, check=False)
    if result.returncode:
        raise BuildError(f"command failed with exit code {result.returncode}: {' '.join(command)}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_file(source: Path, output: Path, name: str | None = None) -> Path:
    if not source.is_file():
        raise BuildError(f"expected build artifact is missing: {source}")
    target = output / (name or source.name)
    shutil.copy2(source, target)
    return target


def make_server_bundle(staging: Path, output: Path) -> Path:
    bundle = staging / "server-bundle"
    bundle.mkdir()
    for relative in ("server", "public", "nginx", "deploy", ".env.example", "LICENSE", "THIRD_PARTY_NOTICES.md"):
        source = staging / relative
        target = bundle / relative
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    scripts = bundle / "scripts"
    scripts.mkdir()
    for name in ("provision_notify_token.sh", "migrate_sqlite_autovacuum.py", "privacy_scan.py"):
        shutil.copy2(staging / "scripts" / name, scripts / name)
    base = output / "xxzf-server-bundle"
    archive = Path(shutil.make_archive(str(base), "zip", root_dir=bundle))
    return archive


def build_targets(staging: Path, output: Path, request: BuildRequest) -> list[Path]:
    env = os.environ.copy()
    artifacts: list[Path] = []
    python = sys.executable
    if "server" in request.targets:
        run([python, "-m", "unittest", "discover", "-s", "server", "-p", "test_*.py"], cwd=staging, env=env)
        artifacts.append(make_server_bundle(staging, output))
    if "android" in request.targets:
        run(["bash", "android/test_receiver.sh"], cwd=staging, env=env)
        run(["bash", "android/test_security.sh"], cwd=staging, env=env)
        android_env = dict(env, BUILD_VARIANT=request.build_mode)
        run(["bash", "android/build.sh"], cwd=staging, env=android_env)
        name = "NotifyBridge-release.apk" if request.build_mode == "release" else "NotifyBridge-debug.apk"
        artifacts.append(copy_file(staging / "dist" / name, output))
    if "macos" in request.targets:
        mac_env = dict(env, BUILD_VARIANT=request.build_mode)
        run(["bash", "server/mac_notifier/build.sh"], cwd=staging, env=mac_env)
        run(["bash", "server/mac_receiver/test_update_manager.sh"], cwd=staging, env=mac_env)
        run(["bash", "server/mac_receiver/build.sh"], cwd=staging, env=mac_env)
        run(["bash", "server/mac_receiver/test_update_install.sh"], cwd=staging, env=mac_env)
        app = staging / "dist" / "转发.app"
        if not app.is_dir():
            raise BuildError(f"expected build artifact is missing: {app}")
        archive = output / f"xxzf-macos-{request.build_mode}.zip"
        run([
            "/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
            str(app), str(archive),
        ], cwd=staging, env=mac_env)
        artifacts.append(archive)
        notifier = staging / "dist" / "XXZFNotifier.app"
        if not notifier.is_dir():
            raise BuildError(f"expected build artifact is missing: {notifier}")
        notifier_archive = output / f"xxzf-macos-local-notifier-{request.build_mode}.zip"
        run([
            "/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
            str(notifier), str(notifier_archive),
        ], cwd=staging, env=mac_env)
        artifacts.append(notifier_archive)
    if "windows" in request.targets:
        windows_env = dict(env, XXZF_BUILD_VARIANT=request.build_mode.capitalize())
        run(["powershell.exe", "-NoProfile", "-File", "windows/build-installer.ps1"], cwd=staging, env=windows_env)
        artifacts.append(copy_file(
            staging / "windows" / "Forwarder-Windows-0.3.0-Test-Setup.exe", output
        ))
    return artifacts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "codex")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        request = load_request(args.request)
    except RequestError as exc:
        print(f"BUILD_REQUEST_INVALID: {exc}", file=sys.stderr)
        return 2

    preflight = subprocess.run([
        sys.executable, str(ROOT / "scripts/codex_preflight.py"),
        "--request", str(args.request),
    ], cwd=ROOT, check=False)
    if preflight.returncode:
        print("BUILD_STOPPED: preflight did not pass", file=sys.stderr)
        return preflight.returncode
    if args.dry_run:
        print("CODEX_BUILD_DRY_RUN_OK")
        return 0

    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_output = output / run_id
    run_output.mkdir(mode=0o700)
    try:
        with tempfile.TemporaryDirectory(prefix="xxzf-codex-build-") as temporary:
            staging = Path(temporary) / "source"
            staging.mkdir()
            copy_clean_source(staging)
            changed = configure_copy(staging, request)
            print(f"CONFIGURED_COPY_OK changed_files={changed} staging={staging}")
            artifacts = build_targets(staging, run_output, request)
        records = []
        for artifact in artifacts:
            digest = sha256(artifact)
            records.append({"file": artifact.name, "sha256": digest, "bytes": artifact.stat().st_size})
            print(f"ARTIFACT {artifact} SHA256={digest}")
        manifest = run_output / "build-results.json"
        manifest.write_text(json.dumps({
            "created_at": run_id,
            "system": {"os": platform.system(), "machine": platform.machine()},
            "public_base": request.public_base,
            "update_base": request.update_base,
            "build_mode": request.build_mode,
            "artifacts": records,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"CODEX_BUILD_OK output={run_output}")
        return 0
    except (BuildError, OSError) as exc:
        if run_output.is_dir():
            shutil.rmtree(run_output)
        print(f"CODEX_BUILD_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
