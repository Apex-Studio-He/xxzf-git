#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
JAVA_HOME="${JAVA_HOME:-$HOME/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home}"
OUT="$HERE/build/receiver-tests"
rm -rf "$OUT"
mkdir -p "$OUT"

"$JAVA_HOME/bin/javac" --release 8 -encoding UTF-8 -d "$OUT" \
  "$HERE/src/com/zundu/notifybridge/ComponentAccess.java" \
  "$HERE/src/com/zundu/notifybridge/ListenerHealth.java" \
  "$HERE/src/com/zundu/notifybridge/RecentNotificationCache.java" \
  "$HERE/src/com/zundu/notifybridge/ReceiverEventFormatter.java" \
  "$HERE/src/com/zundu/notifybridge/ReceiverSenderContract.java" \
  "$HERE/src/com/zundu/notifybridge/SenderDevice.java" \
  "$HERE/src/com/zundu/notifybridge/SenderDevices.java" \
  "$HERE/src/com/zundu/notifybridge/BarkDestination.java" \
  "$HERE/tests/ComponentAccessTest.java" \
  "$HERE/tests/ListenerHealthTest.java" \
  "$HERE/tests/RecentNotificationCacheTest.java" \
  "$HERE/tests/ReceiverEventFormatterTest.java" \
  "$HERE/tests/ReceiverSenderContractTest.java" \
  "$HERE/tests/SenderDevicesTest.java" \
  "$HERE/tests/BarkDestinationTest.java"
"$JAVA_HOME/bin/java" -cp "$OUT" com.zundu.notifybridge.ComponentAccessTest
"$JAVA_HOME/bin/java" -cp "$OUT" com.zundu.notifybridge.ListenerHealthTest
"$JAVA_HOME/bin/java" -cp "$OUT" com.zundu.notifybridge.RecentNotificationCacheTest
"$JAVA_HOME/bin/java" -cp "$OUT" com.zundu.notifybridge.ReceiverEventFormatterTest
"$JAVA_HOME/bin/java" -cp "$OUT" com.zundu.notifybridge.ReceiverSenderContractTest
"$JAVA_HOME/bin/java" -cp "$OUT" com.zundu.notifybridge.SenderDevicesTest
"$JAVA_HOME/bin/java" -cp "$OUT" com.zundu.notifybridge.BarkDestinationTest
python3 "$HERE/tests/sender_management_policy_test.py"
python3 "$HERE/tests/bark_management_policy_test.py"
python3 "$HERE/tests/service_heartbeat_policy_test.py"
echo "Android receiver formatter checks passed"
