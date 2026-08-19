#!/usr/bin/env bash
set -euo pipefail

ROOT="${ANDROID_NOTIFY_BRIDGE_ROOT:-$HOME/.local/share/android-notify-bridge}"
SDK_ROOT="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
JVM_ROOT="$HOME/Library/Java/JavaVirtualMachines"
CMDLINE_VERSION="14742923"
ANDROID_API="35"
BUILD_TOOLS="35.0.0"

arch_name="$(uname -m)"
case "$arch_name" in
  arm64|aarch64)
    adoptium_arch="aarch64"
    jdk_checksum="8fa1eff40bb637a33613b2ccb8b12c70dc3661cc22cf8e784943715769a05336"
    ;;
  x86_64|amd64)
    adoptium_arch="x64"
    jdk_checksum=""
    ;;
  *)
    echo "Unsupported architecture: $arch_name" >&2
    exit 1
    ;;
esac

mkdir -p "$ROOT/downloads" "$SDK_ROOT/cmdline-tools" "$JVM_ROOT"

echo "==> Installing Temurin JDK 17 for macOS $adoptium_arch"
jdk_api="https://api.adoptium.net/v3/assets/latest/17/hotspot?architecture=$adoptium_arch&image_type=jdk&os=mac&heap_size=normal&vendor=eclipse"
jdk_url="$(curl -fsSL -H 'User-Agent: curl' "$jdk_api" | /usr/bin/python3 -c 'import json, sys; data = json.load(sys.stdin); print(data[0]["binary"]["package"]["link"])')"
jdk_tar="$ROOT/downloads/temurin17-$adoptium_arch.tar.gz"
curl -L "$jdk_url" -o "$jdk_tar"

if [ -n "$jdk_checksum" ]; then
  actual="$(shasum -a 256 "$jdk_tar" | awk '{print $1}')"
  if [ "$actual" != "$jdk_checksum" ]; then
    echo "JDK checksum mismatch: $actual" >&2
    exit 1
  fi
fi

tmp_jdk="$(mktemp -d)"
tar -xzf "$jdk_tar" -C "$tmp_jdk"
jdk_dir="$(find "$tmp_jdk" -maxdepth 1 -type d -name '*.jdk' -o -type d -name 'jdk-*' | head -n 1)"
if [ -z "$jdk_dir" ]; then
  echo "Cannot find extracted JDK directory" >&2
  exit 1
fi
rm -rf "$JVM_ROOT/temurin-17.jdk"
mv "$jdk_dir" "$JVM_ROOT/temurin-17.jdk"
rm -rf "$tmp_jdk"

export JAVA_HOME="$JVM_ROOT/temurin-17.jdk/Contents/Home"
export PATH="$JAVA_HOME/bin:$PATH"
"$JAVA_HOME/bin/java" -version

echo "==> Installing Android command line tools"
cmd_zip="$ROOT/downloads/commandlinetools-mac-${CMDLINE_VERSION}_latest.zip"
curl -L "https://dl.google.com/android/repository/commandlinetools-mac-${CMDLINE_VERSION}_latest.zip" -o "$cmd_zip"

tmp_tools="$(mktemp -d)"
unzip -q -o "$cmd_zip" -d "$tmp_tools"
rm -rf "$SDK_ROOT/cmdline-tools/latest"
mkdir -p "$SDK_ROOT/cmdline-tools"
mv "$tmp_tools/cmdline-tools" "$SDK_ROOT/cmdline-tools/latest"
rm -rf "$tmp_tools"

export ANDROID_HOME="$SDK_ROOT"
export ANDROID_SDK_ROOT="$SDK_ROOT"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"

echo "==> Accepting Android SDK licenses"
set +o pipefail
yes | sdkmanager --licenses >/dev/null
set -o pipefail

echo "==> Installing Android SDK packages"
sdkmanager \
  "platform-tools" \
  "platforms;android-${ANDROID_API}" \
  "build-tools;${BUILD_TOOLS}"

cat <<EOF

Done.

Add this to your shell when building manually:
export JAVA_HOME="$JAVA_HOME"
export ANDROID_HOME="$ANDROID_HOME"
export PATH="\$JAVA_HOME/bin:\$ANDROID_HOME/cmdline-tools/latest/bin:\$ANDROID_HOME/platform-tools:\$PATH"
EOF
