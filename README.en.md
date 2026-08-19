# XXZF / Forwarder

![XXZF forwards Android notifications to Mac, Windows, and iPhone](docs/images/xxzf-hero.svg)

[中文](README.md) · [Codex-assisted build](CODEX.md) · [Deployment](docs/deployment.en.md) · [Configuration](docs/configuration.en.md) · [Security](SECURITY.md) · [Support](SUPPORT.md)

**Keep an eye on your Android notifications from the screen you already use.** XXZF forwards notifications selected by the user through a self-hosted HTTPS service to macOS, Windows, or an iPhone through Bark. Its privacy-friendly presentation sends the source app and notification title without exposing the original body on another screen.

The project ships the complete Android sender, Python service, macOS and Windows receivers, Bark enrollment page, deployment templates, tests, and build tooling. You choose the HTTPS endpoints and build the clients for your own deployment; non-working documentation domains are used until that configuration is supplied.

![How XXZF works](docs/images/how-it-works.svg)

## Components

- Android sender: notification listener, app allowlist, background relay, destination management, and Bark enrollment.
- Python server: pairing, per-device credentials, rate limiting, routing, bounded archives, diagnostics, and isolated Bark-secret storage.
- macOS and Windows receivers: six-digit pairing, native notifications, reconnect logic, and signed-update verification.
- iPhone: the App Store version of Bark; no native XXZF iOS app or self-signing workflow is required.

## Requirements

| Component | Environment |
|---|---|
| Server | macOS 12+ or a common 64-bit Linux distribution; Python 3.9+; Nginx; a domain and valid TLS certificate |
| Android build | macOS; JDK 17; Android SDK Platform 35; Build Tools 35.0.0 |
| Android runtime | Android 8.0 / API 26+ with notification-listener and background permissions granted by the user |
| macOS build | macOS 12+ and Xcode Command Line Tools; Apple Developer credentials for public release |
| macOS runtime | macOS 10.14+ |
| Windows build | Windows 10/11; PowerShell 5.1+; .NET Framework 4.8 Developer Pack; IExpress |
| Windows release | Windows SDK `signtool.exe` and a code-signing certificate |
| iPhone | Bark installed from the App Store; Xcode and Developer Mode are not required |

## Deployment overview

New to source builds? Open [the Codex-assisted build guide](CODEX.md), fill in the public endpoint template, and ask Codex to preflight, configure, test, and build an isolated copy. Passwords and private signing keys never belong in that template.

1. Point your own domain at the host and configure trusted TLS.
2. Install the repository under `/opt/xxzf`; keep runtime data outside the repository.
3. Copy `.env.example` to a private location and replace every example path and URL.
4. Generate the compatibility token with `scripts/provision_notify_token.sh`.
5. Install the example systemd or launchd service. The Python process must remain bound to `127.0.0.1:8787`.
6. Include `nginx/xxzf_public_routes.inc` in your HTTPS virtual host. Never publish the management or audit page.
7. Replace all example endpoints embedded in the clients and rebuild them.
8. Generate an update-signing key outside the repository with `scripts/generate_update_key.sh`, then pin its public values in every client and publishing verifier.
9. Run all tests and `scripts/privacy_scan.sh` before release.

See [the full deployment guide](docs/deployment.en.md) and [configuration reference](docs/configuration.en.md) for exact files, environment variables, signing requirements, and update setup.

## Build and test

```bash
./android/test_receiver.sh
./android/test_security.sh
./android/build.sh

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s server -p 'test_*.py'

./server/mac_receiver/test_update_manager.sh
./server/mac_receiver/build.sh

./scripts/privacy_scan.sh
```

On Windows PowerShell:

```powershell
.\windows\build.ps1
.\windows\build-installer.ps1
```

## Privacy and network boundary

- No business endpoint works until the operator explicitly configures and rebuilds the clients.
- Runtime clients contact only the pinned self-hosted XXZF HTTPS origin and pinned update origin.
- Bark support contacts an allowlisted Bark origin; the default is only `https://api.day.app`.
- There is no advertising, analytics, crash reporting, device fingerprinting, backdoor account, or universal pairing key.
- Databases, archives, diagnostics, Bark keys, compatibility tokens, and signing materials must stay outside the source tree with private filesystem permissions.
- The audit UI is loopback-only and has no public Nginx route.

## License

XXZF code is licensed under the [MIT License](LICENSE). Bundled dependencies retain their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
