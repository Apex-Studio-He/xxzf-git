#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$PROJECT_DIR/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$PROJECT_DIR/build"
BUILD_VARIANT="${BUILD_VARIANT:-debug}"

case "$BUILD_VARIANT" in
  debug|release) ;;
  *)
    echo "BUILD_VARIANT must be debug or release" >&2
    exit 1
    ;;
esac

export JAVA_HOME="${JAVA_HOME:-$HOME/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"

ANDROID_API="${ANDROID_API:-35}"
BUILD_TOOLS_VERSION="${BUILD_TOOLS_VERSION:-35.0.0}"
BUILD_TOOLS="$ANDROID_HOME/build-tools/$BUILD_TOOLS_VERSION"
ANDROID_JAR="$ANDROID_HOME/platforms/android-$ANDROID_API/android.jar"
ZXING_JAR="$PROJECT_DIR/libs/zxing-core-3.5.4.jar"

if [ ! -x "$JAVA_HOME/bin/javac" ]; then
  echo "Cannot find javac at $JAVA_HOME/bin/javac" >&2
  echo "Run ../scripts/install_android_tools.sh first." >&2
  exit 1
fi

for tool in aapt2 d8 zipalign apksigner; do
  if [ ! -x "$BUILD_TOOLS/$tool" ]; then
    echo "Cannot find $tool in $BUILD_TOOLS" >&2
    echo "Run ../scripts/install_android_tools.sh first." >&2
    exit 1
  fi
done

if [ ! -f "$ANDROID_JAR" ]; then
  echo "Cannot find $ANDROID_JAR" >&2
  exit 1
fi

if [ ! -f "$ZXING_JAR" ]; then
  echo "Cannot find $ZXING_JAR" >&2
  exit 1
fi

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/gen" "$BUILD_DIR/classes" "$BUILD_DIR/dex" "$DIST_DIR"

echo "==> Compile resources"
"$BUILD_TOOLS/aapt2" compile --dir "$PROJECT_DIR/res" -o "$BUILD_DIR/res.zip"

echo "==> Link APK resources"
"$BUILD_TOOLS/aapt2" link \
  -I "$ANDROID_JAR" \
  --auto-add-overlay \
  --manifest "$PROJECT_DIR/AndroidManifest.xml" \
  --java "$BUILD_DIR/gen" \
  --min-sdk-version 26 \
  --target-sdk-version "$ANDROID_API" \
  --version-code 26 \
  --version-name 0.9.16 \
  -R "$BUILD_DIR/res.zip" \
  -o "$BUILD_DIR/app-unsigned.apk"

echo "==> Compile Java"
find "$PROJECT_DIR/src" "$BUILD_DIR/gen" -name '*.java' > "$BUILD_DIR/sources.txt"
"$JAVA_HOME/bin/javac" \
  -source 8 \
  -target 8 \
  -encoding UTF-8 \
  -bootclasspath "$ANDROID_JAR" \
  -classpath "$ZXING_JAR" \
  -d "$BUILD_DIR/classes" \
  @"$BUILD_DIR/sources.txt"

echo "==> Dex"
"$BUILD_TOOLS/d8" \
  --lib "$ANDROID_JAR" \
  --min-api 26 \
  --output "$BUILD_DIR/dex" \
  $(find "$BUILD_DIR/classes" -name '*.class') \
  "$ZXING_JAR"

echo "==> Package classes.dex"
cp "$BUILD_DIR/app-unsigned.apk" "$BUILD_DIR/app-with-dex.apk"
(cd "$BUILD_DIR/dex" && zip -q -u "$BUILD_DIR/app-with-dex.apk" classes.dex)

echo "==> Sign ($BUILD_VARIANT)"

private_file_mode() {
  local value
  value="$(stat -f '%Lp' "$1" 2>/dev/null || stat -c '%a' "$1")"
  [ $((8#$value & 077)) -eq 0 ]
}

if [ "$BUILD_VARIANT" = "debug" ]; then
  SIGNING_DIR="${XXZF_ANDROID_SIGNING_DIR:-$HOME/Library/Application Support/XXZF/signing}"
  KEYSTORE="${XXZF_ANDROID_DEBUG_KEYSTORE:-$SIGNING_DIR/debug.keystore}"
  if [ -L "$KEYSTORE" ]; then
    echo "Debug keystore must not be a symbolic link: $KEYSTORE" >&2
    exit 1
  fi
  mkdir -p "$SIGNING_DIR"
  chmod 700 "$SIGNING_DIR"
  if [ ! -f "$KEYSTORE" ]; then
    "$JAVA_HOME/bin/keytool" -genkeypair \
      -keystore "$KEYSTORE" \
      -storepass android \
      -keypass android \
      -alias androiddebugkey \
      -keyalg RSA \
      -keysize 2048 \
      -validity 10000 \
      -dname "CN=Android Debug,O=NotifyBridge,C=CN"
  fi
  chmod 600 "$KEYSTORE"
  KEY_ALIAS="androiddebugkey"
  KS_PASS="pass:android"
  KEY_PASS="pass:android"
  OUTPUT="$DIST_DIR/NotifyBridge-debug.apk"
else
  : "${XXZF_ANDROID_KEYSTORE:?Set XXZF_ANDROID_KEYSTORE for a release build}"
  : "${XXZF_ANDROID_KEY_ALIAS:?Set XXZF_ANDROID_KEY_ALIAS for a release build}"
  : "${XXZF_ANDROID_STORE_PASS_FILE:?Set XXZF_ANDROID_STORE_PASS_FILE for a release build}"
  : "${XXZF_ANDROID_KEY_PASS_FILE:?Set XXZF_ANDROID_KEY_PASS_FILE for a release build}"
  : "${XXZF_ANDROID_EXPECTED_CERT_SHA256:?Set XXZF_ANDROID_EXPECTED_CERT_SHA256 for a release build}"
  KEYSTORE="$XXZF_ANDROID_KEYSTORE"
  KEY_ALIAS="$XXZF_ANDROID_KEY_ALIAS"
  OUTPUT="$DIST_DIR/NotifyBridge-release.apk"
  for private_file in "$KEYSTORE" "$XXZF_ANDROID_STORE_PASS_FILE" "$XXZF_ANDROID_KEY_PASS_FILE"; do
    if [ ! -f "$private_file" ] || [ -L "$private_file" ] || ! private_file_mode "$private_file"; then
      echo "Release signing files must be private regular files: $private_file" >&2
      exit 1
    fi
  done
  KS_PASS="file:$XXZF_ANDROID_STORE_PASS_FILE"
  KEY_PASS="file:$XXZF_ANDROID_KEY_PASS_FILE"
fi

"$BUILD_TOOLS/zipalign" -f -p 4 "$BUILD_DIR/app-with-dex.apk" "$BUILD_DIR/app-aligned.apk"
"$BUILD_TOOLS/apksigner" sign \
  --ks "$KEYSTORE" \
  --ks-key-alias "$KEY_ALIAS" \
  --ks-pass "$KS_PASS" \
  --key-pass "$KEY_PASS" \
  --out "$OUTPUT" \
  "$BUILD_DIR/app-aligned.apk"

CERTIFICATES="$("$BUILD_TOOLS/apksigner" verify --verbose --print-certs "$OUTPUT")"
if [ "$BUILD_VARIANT" = "release" ]; then
  ACTUAL_CERT="$(printf '%s\n' "$CERTIFICATES" | sed -n 's/^Signer #1 certificate SHA-256 digest: //p' | head -n 1 | tr -d ':[:space:]' | tr '[:upper:]' '[:lower:]')"
  EXPECTED_CERT="$(printf '%s' "$XXZF_ANDROID_EXPECTED_CERT_SHA256" | tr -d ':[:space:]' | tr '[:upper:]' '[:lower:]')"
  if [ -z "$ACTUAL_CERT" ] || [ "$ACTUAL_CERT" != "$EXPECTED_CERT" ]; then
    rm -f "$OUTPUT"
    echo "Release signing certificate does not match the pinned SHA-256 digest" >&2
    exit 1
  fi
  if printf '%s\n' "$CERTIFICATES" | grep -qi 'Android Debug'; then
    rm -f "$OUTPUT"
    echo "A debug certificate cannot be used for a release APK" >&2
    exit 1
  fi
fi

/usr/bin/shasum -a 256 "$OUTPUT" > "$OUTPUT.sha256"
echo "APK: $OUTPUT"
echo "SHA256: $OUTPUT.sha256"
