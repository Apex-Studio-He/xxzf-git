package com.zundu.notifybridge;

import java.util.HashMap;
import java.util.Map;

public final class UpdateSecurityTest {
    private static int checks;
    private static String testPublicKey;

    public static void main(String[] args) throws Exception {
        if (args.length != 2 || args[0].isEmpty() || args[1].isEmpty()) {
            throw new AssertionError("signature and public key required");
        }
        testPublicKey = args[1];
        Map<String, Object> valid = valid(args[0]);
        UpdateSecurity.ManifestData accepted = UpdateSecurity.validateAndVerify(
                valid, 13, testPublicKey, UpdateSecurity.KEY_ID);
        equal(999L, accepted.versionCode, "valid signed manifest");
        equal(validCanonical(), accepted.canonical(), "canonical field order");

        reject(copy(valid, "url", "http://example.com:8443/downloads/forwarder/test/forwarder-android-9.9.9-test.apk"), 13);
        reject(copy(valid, "url", "https://evil.example:8443/downloads/forwarder/test/forwarder-android-9.9.9-test.apk"), 13);
        reject(copy(valid, "url", "https://updates.example.com/downloads/forwarder/test/../forwarder-android-9.9.9-test.apk"), 13);
        reject(copy(valid, "platform", "windows"), 13);
        reject(copy(valid, "keyId", "wrong"), 13);
        reject(copy(valid, "size", UpdateSecurity.MAX_PACKAGE_BYTES + 1), 13);
        reject(copy(valid, "signature", "AAAA"), 13);
        reject(valid, 999);

        Map<String, Object> extra = new HashMap<>(valid);
        extra.put("extra", "rejected");
        reject(extra, 13);

        System.out.println("UpdateSecurityTest: " + checks + " checks passed");
    }

    private static Map<String, Object> valid(String signature) {
        Map<String, Object> values = new HashMap<>();
        values.put("schema", 1);
        values.put("channel", "test");
        values.put("platform", "android");
        values.put("versionCode", 999);
        values.put("version", "9.9.9");
        values.put("url", "https://updates.example.com/downloads/forwarder/test/forwarder-android-9.9.9-test.apk");
        values.put("sha256", "0000000000000000000000000000000000000000000000000000000000000000");
        values.put("size", 12345);
        values.put("publishedAt", "2026-07-12T00:00:00Z");
        values.put("notes", "security test");
        values.put("keyId", "8545bd8392ab5de2");
        values.put("signature", signature);
        return values;
    }

    private static String validCanonical() {
        return "1\ntest\nandroid\n999\n9.9.9\n"
                + "https://updates.example.com/downloads/forwarder/test/forwarder-android-9.9.9-test.apk\n"
                + "0000000000000000000000000000000000000000000000000000000000000000\n"
                + "12345\n2026-07-12T00:00:00Z\nsecurity test\n8545bd8392ab5de2";
    }

    private static Map<String, Object> copy(Map<String, Object> source, String key, Object value) {
        Map<String, Object> result = new HashMap<>(source);
        result.put(key, value);
        return result;
    }

    private static void reject(Map<String, Object> values, long current) throws Exception {
        checks++;
        try {
            UpdateSecurity.validateAndVerify(
                    values, current, testPublicKey, UpdateSecurity.KEY_ID);
            throw new AssertionError("expected manifest rejection");
        } catch (SecurityException expected) {
            // Expected fail-closed path.
        }
    }

    private static void equal(Object expected, Object actual, String label) {
        checks++;
        if (!expected.equals(actual)) {
            throw new AssertionError(label + ": expected " + expected + ", got " + actual);
        }
    }
}
