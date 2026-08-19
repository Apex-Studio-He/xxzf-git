# XXZF Codex working agreement

When a user asks Codex to configure, build, test, package, or deploy this
repository, read `CODEX.md` first and follow it as the source of truth.

Safety rules:

1. Read `codex/request.local.json`; if it does not exist, help the user create
   it from `codex/request.example.json`. Ask only for missing public values.
2. Never ask the user to paste a password, Bark device key, private signing
   key, certificate password, SSH private key, or production token into chat
   or a tracked file. Signing secrets must remain in local files outside this
   repository and be referenced through documented environment variables.
3. Run `python3 scripts/codex_preflight.py --request
   codex/request.local.json` before changing or installing anything.
4. Large downloads, package-manager installs, certificate changes, remote
   connections, server deployment, and release signing require explicit user
   confirmation. A build request alone does not authorize deployment.
5. Use `python3 scripts/codex_build.py --request
   codex/request.local.json` for the isolated configured build. Do not replace
   the placeholder endpoints in the public working tree.
6. Default to a debug build. Release builds require the user to choose release
   explicitly and to provide local signing material through the variables in
   `docs/配置参考.md`.
7. Run the relevant tests and report every output path and SHA-256. Never claim
   completion when a target was skipped, a test failed, or the current OS
   cannot build it.
8. Before any Git commit or push, run `./scripts/privacy_scan.sh` and Gitleaks
   when available. Never commit `codex/request.local.json`, `.env`, build
   products, logs, databases, credentials, or signing material.
