#!/usr/bin/env python3
"""Read-only environment checks for the Codex-assisted XXZF build."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from codex_request import RequestError, load_request


@dataclass(frozen=True)
class Check:
    target: str
    name: str
    ok: bool
    detail: str
    fix: str = ""


def command_path(name: str) -> str:
    return shutil.which(name) or ""


def display_path(path: Path | str) -> str:
    value = str(path)
    home = str(Path.home())
    return "~" + value[len(home):] if value == home or value.startswith(home + os.sep) else value


def java_home_17() -> Path:
    configured = os.environ.get("JAVA_HOME")
    if configured:
        return Path(configured).expanduser()
    default = Path.home() / "Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home"
    if default.joinpath("bin", "javac").is_file():
        return default
    helper = Path("/usr/libexec/java_home")
    if helper.is_file():
        result = subprocess.run(
            [str(helper), "-v", "17"], capture_output=True, text=True, check=False
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    return default


def base_checks() -> list[Check]:
    version_ok = sys.version_info >= (3, 9)
    return [Check(
        "all",
        "Python 3.9+",
        version_ok,
        platform.python_version(),
        "Install Python 3.9 or newer" if not version_ok else "",
    )]


def server_checks() -> list[Check]:
    return [Check(
        "server",
        "Python standard library runtime",
        sys.version_info >= (3, 9),
        f"Python {platform.python_version()}",
        "Install Python 3.9 or newer",
    )]


def android_checks() -> list[Check]:
    checks: list[Check] = []
    is_macos = platform.system() == "Darwin"
    checks.append(Check(
        "android", "macOS build host", is_macos, platform.system(),
        "Use a Mac for the repository's Android build script",
    ))
    home = java_home_17()
    javac = home / "bin" / "javac"
    checks.append(Check(
        "android", "JDK 17", javac.is_file(), display_path(home),
        "After approval, run scripts/install_android_tools.sh",
    ))
    sdk = Path(os.environ.get("ANDROID_HOME", Path.home() / "Library/Android/sdk")).expanduser()
    checks.append(Check(
        "android", "Android SDK Platform 35",
        (sdk / "platforms/android-35/android.jar").is_file(), display_path(sdk),
        "After approval, run scripts/install_android_tools.sh",
    ))
    tools = sdk / "build-tools/35.0.0"
    missing = [name for name in ("aapt2", "d8", "zipalign", "apksigner") if not (tools / name).is_file()]
    checks.append(Check(
        "android", "Android Build Tools 35.0.0", not missing,
        display_path(tools) if not missing else f"missing: {', '.join(missing)}",
        "After approval, run scripts/install_android_tools.sh",
    ))
    return checks


def macos_checks() -> list[Check]:
    is_macos = platform.system() == "Darwin"
    checks = [Check(
        "macos", "macOS build host", is_macos, platform.system(),
        "Build the macOS target on a Mac",
    )]
    for name, path in (
        ("Clang", "/usr/bin/clang"),
        ("codesign", "/usr/bin/codesign"),
        ("PlistBuddy", "/usr/libexec/PlistBuddy"),
    ):
        present = Path(path).is_file()
        checks.append(Check(
            "macos", name, present, path,
            "Install Xcode Command Line Tools with: xcode-select --install",
        ))
    return checks


def windows_checks() -> list[Check]:
    is_windows = platform.system() == "Windows"
    checks = [Check(
        "windows", "Windows build host", is_windows, platform.system(),
        "Build the Windows target on Windows 10 or 11",
    )]
    windir = Path(os.environ.get("WINDIR", "C:/Windows"))
    csc = windir / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    checks.append(Check(
        "windows", ".NET Framework C# compiler", csc.is_file(), str(csc),
        "Install .NET Framework 4.8 Developer Pack",
    ))
    powershell = command_path("powershell.exe") or command_path("powershell")
    checks.append(Check(
        "windows", "PowerShell 5.1+", bool(powershell), powershell or "not found",
        "Enable Windows PowerShell 5.1",
    ))
    iexpress = windir / "System32/iexpress.exe"
    checks.append(Check(
        "windows", "IExpress installer builder", iexpress.is_file(), str(iexpress),
        "Use a standard Windows 10/11 installation with IExpress",
    ))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        request = load_request(args.request)
    except RequestError as exc:
        payload = {"ok": False, "stage": "request", "error": str(exc)}
        print(json.dumps(payload, ensure_ascii=False) if args.json else f"PREFLIGHT_INVALID: {exc}")
        return 2

    checks = base_checks()
    providers = {
        "server": server_checks,
        "android": android_checks,
        "macos": macos_checks,
        "windows": windows_checks,
    }
    for target in request.targets:
        checks.extend(providers[target]())
    ok = all(check.ok for check in checks)
    if args.json:
        print(json.dumps({
            "ok": ok,
            "request": asdict(request),
            "system": {"os": platform.system(), "machine": platform.machine()},
            "checks": [asdict(check) for check in checks],
        }, ensure_ascii=False, indent=2))
    else:
        print(f"XXZF Codex preflight — {platform.system()} {platform.machine()}")
        for check in checks:
            marker = "OK" if check.ok else "MISSING"
            print(f"[{marker:7}] {check.target:7} {check.name}: {check.detail}")
            if not check.ok and check.fix:
                print(f"          How to fix: {check.fix}")
        print("PREFLIGHT_OK" if ok else "PREFLIGHT_NEEDS_ATTENTION")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
