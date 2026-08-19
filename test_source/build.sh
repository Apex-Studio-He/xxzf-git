#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$PROJECT_DIR/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$PROJECT_DIR/build"

export JAVA_HOME="${JAVA_HOME:-$HOME/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
ANDROID_API="${ANDROID_API:-35}"
BUILD_TOOLS_VERSION="${BUILD_TOOLS_VERSION:-35.0.0}"
BUILD_TOOLS="$ANDROID_HOME/build-tools/$BUILD_TOOLS_VERSION"
ANDROID_JAR="$ANDROID_HOME/platforms/android-$ANDROID_API/android.jar"

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/gen" "$BUILD_DIR/classes" "$BUILD_DIR/dex" "$DIST_DIR"

"$BUILD_TOOLS/aapt2" compile --dir "$PROJECT_DIR/res" -o "$BUILD_DIR/res.zip"
"$BUILD_TOOLS/aapt2" link \
  -I "$ANDROID_JAR" \
  --auto-add-overlay \
  --manifest "$PROJECT_DIR/AndroidManifest.xml" \
  --java "$BUILD_DIR/gen" \
  --min-sdk-version 26 \
  --target-sdk-version "$ANDROID_API" \
  --version-code 1 \
  --version-name 0.1 \
  -R "$BUILD_DIR/res.zip" \
  -o "$BUILD_DIR/app-unsigned.apk"

find "$PROJECT_DIR/src" "$BUILD_DIR/gen" -name '*.java' > "$BUILD_DIR/sources.txt"
"$JAVA_HOME/bin/javac" -source 8 -target 8 -encoding UTF-8 -bootclasspath "$ANDROID_JAR" -d "$BUILD_DIR/classes" @"$BUILD_DIR/sources.txt"
"$BUILD_TOOLS/d8" --lib "$ANDROID_JAR" --min-api 26 --output "$BUILD_DIR/dex" $(find "$BUILD_DIR/classes" -name '*.class')
cp "$BUILD_DIR/app-unsigned.apk" "$BUILD_DIR/app-with-dex.apk"
(cd "$BUILD_DIR/dex" && zip -q -u "$BUILD_DIR/app-with-dex.apk" classes.dex)

SIGNING_DIR="${XXZF_ANDROID_SIGNING_DIR:-$HOME/Library/Application Support/XXZF/signing}"
KEYSTORE="${XXZF_ANDROID_DEBUG_KEYSTORE:-$SIGNING_DIR/debug.keystore}"
if [ -L "$KEYSTORE" ]; then
  echo "Debug keystore must not be a symbolic link: $KEYSTORE" >&2
  exit 1
fi
mkdir -p "$SIGNING_DIR"
chmod 700 "$SIGNING_DIR"
if [ ! -f "$KEYSTORE" ]; then
  "$JAVA_HOME/bin/keytool" -genkeypair -keystore "$KEYSTORE" -storepass android -keypass android -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Android Debug,O=XXZF,C=CN"
fi
chmod 600 "$KEYSTORE"

"$BUILD_TOOLS/zipalign" -f -p 4 "$BUILD_DIR/app-with-dex.apk" "$BUILD_DIR/app-aligned.apk"
"$BUILD_TOOLS/apksigner" sign --ks "$KEYSTORE" --ks-key-alias androiddebugkey --ks-pass pass:android --key-pass pass:android --out "$DIST_DIR/NotifySource-debug.apk" "$BUILD_DIR/app-aligned.apk"
"$BUILD_TOOLS/apksigner" verify "$DIST_DIR/NotifySource-debug.apk"
/usr/bin/shasum -a 256 "$DIST_DIR/NotifySource-debug.apk" > "$DIST_DIR/NotifySource-debug.apk.sha256"
echo "APK: $DIST_DIR/NotifySource-debug.apk"
