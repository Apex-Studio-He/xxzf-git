# Configuration reference

## Server environment

| Variable | Purpose |
|---|---|
| `HOST` | Numeric loopback address only; defaults to `127.0.0.1` |
| `PORT` | Python service port, default `8787` |
| `DATA_DIR` | Private runtime-data root; set it explicitly in production |
| `XXZF_TOKEN_FILE` | Private legacy Bearer token file |
| `XXZF_AUDIT_DIR` | Bounded notification archive |
| `XXZF_DIAGNOSTIC_DIR` | Bounded diagnostics directory |
| `XXZF_BARK_SECRET_FILE` | Mode-`0600` Bark device-key store |
| `XXZF_BARK_ICON_DIR` | Private content-addressed Android app-icon cache |
| `XXZF_APK_FILE` | Local release APK exposed only by the local management UI |
| `XXZF_PUBLIC_BASE` | Public client API base, such as `https://notify.example.com/xxzf` |
| `XXZF_PUBLIC_ORIGIN` | Canonical HTTPS origin used for Host/origin validation |
| `XXZF_BARK_BIND_PAGE` | Public one-time Bark enrollment page |
| `XXZF_BARK_ALLOWED_BASES` | Exact comma-separated allowlist of Bark HTTPS bases, optionally with safe path prefixes |

## Android release signing

Set `BUILD_VARIANT=release` plus `XXZF_ANDROID_KEYSTORE`, `XXZF_ANDROID_KEY_ALIAS`, `XXZF_ANDROID_STORE_PASS_FILE`, `XXZF_ANDROID_KEY_PASS_FILE`, and `XXZF_ANDROID_EXPECTED_CERT_SHA256`. Secret files must be private regular files and must not be symlinks.

## macOS release signing

Set `BUILD_VARIANT=release`, `XXZF_MAC_SIGN_IDENTITY`, and `XXZF_MAC_EXPECTED_TEAM_ID`. Notarization additionally uses `XXZF_NOTARY_KEYCHAIN_PROFILE` created with `notarytool store-credentials`.

## Windows release signing

Set `XXZF_BUILD_VARIANT=Release`, `XXZF_WINDOWS_SIGN_CERT_SHA256`, and optionally `XXZF_SIGNTOOL`. Exactly one private certificate must match the pinned SHA-256 digest.

## Update publishing

`XXZF_UPDATE_PRIVATE_KEY` selects the private RSA key outside the repository. The publisher writes signed artifacts only to a local output directory. This repository deliberately contains no SSH, SCP, or automatic server-upload workflow.

The API and update endpoints are deliberately compiled into each client. See [deployment.en.md](deployment.en.md) for the exact source files that must be updated and tested for a self-hosted instance.
