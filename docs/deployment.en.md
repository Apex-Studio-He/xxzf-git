# Self-hosted deployment

This guide uses `https://notify.example.com/xxzf` and `https://updates.example.com/downloads/forwarder/test` as examples. Replace them with domains you control. Never commit a real environment file, private key, Bark key, database, or notification archive.

## Server

1. Create a dedicated non-login `xxzf` account.
2. Install the source at `/opt/xxzf` and create `/var/lib/xxzf` with mode `0700`, owned by that account.
3. Point DNS at the host and obtain a certificate from a trusted CA.
4. Generate the compatibility token:

   ```bash
   sudo -u xxzf /opt/xxzf/scripts/provision_notify_token.sh \
     /var/lib/xxzf/notify-token.txt
   ```

5. Copy `.env.example` to `/etc/xxzf/xxzf.env`, set mode `0640`, and replace all paths and URLs. Keep `HOST=127.0.0.1`.
6. Install `deploy/systemd/xxzf.service.example`, or customize the launchd example on macOS.
7. Verify the loopback health endpoint before configuring public ingress:

   ```bash
   curl --fail http://127.0.0.1:8787/api/v1/health
   ```

## Nginx

Merge `deploy/nginx/xxzf-server.conf.example` into the HTTPS virtual host and copy `nginx/xxzf_public_routes.inc` to the include path. The parent `http {}` block must define the two rate/connection zones shown in the example.

Keep the exact route allowlist. Do not replace it with a broad `/xxzf/` proxy. Do not expose `/audit/`, `/api/config`, or the loopback server port. Use an SSH tunnel to reach the audit UI.

## Client endpoint pinning

Replace `https://example.com/xxzf` with your public base in:

- `android/src/com/zundu/notifybridge/ServerPolicy.java`
- `server/mac_client.py`
- `server/mac_receiver/Receiver.m`
- `scripts/start_air_notifier.sh`
- `windows/Forwarder.cs`

Update the matching test expectations and run the complete test suite. The base must be HTTPS and contain no userinfo, query, or fragment.

## Update signing

The committed public key is an ownerless placeholder: its private counterpart was discarded, so it cannot sign a release. Generate your own key outside the repository:

```bash
./scripts/generate_update_key.sh /absolute/private/path/xxzf-update-signing
```

Pin the generated Key ID and public values in Android `UpdateSecurity.java`, macOS `UpdateManager.m`, Windows `Updater.cs`, `publish_test_update.py`, and `verify_published_update.py`. Replace the example update base/host/path in the same files and their tests. Keep `update-private.pem` offline or on a tightly controlled release host.

## Client builds

Android needs JDK 17, Android Platform 35, and Build Tools 35.0.0. Run `android/test_receiver.sh`, `android/test_security.sh`, and `android/build.sh`. Public distribution requires a long-lived release keystore.

macOS needs Xcode Command Line Tools. Run `server/mac_receiver/build.sh`; public distribution should use Developer ID signing and notarization.

Windows needs PowerShell 5.1+, .NET Framework 4.8 Developer Pack, IExpress, and Windows SDK signing tools for a release build. Run `windows/build.ps1` and `windows/build-installer.ps1`.

## Final checks

Run all tests and `scripts/privacy_scan.sh`, preferably followed by Gitleaks. Build from a clean checkout and verify that no runtime data, logs, packages, certificates, or keys are tracked.
