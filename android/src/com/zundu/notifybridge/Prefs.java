package com.zundu.notifybridge;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONObject;

import java.util.LinkedHashSet;
import java.util.Set;

final class Prefs {
    static final String PREFS = "notify_bridge";
    static final String KEY_ENABLED = "enabled";
    static final String KEY_SERVER_URL = "server_url";
    static final String KEY_PACKAGES = "packages";
    static final String KEY_KEYWORDS = "keywords";
    static final String KEY_PRIVACY = "privacy";
    static final String KEY_FILTER_ALL = "filter_all";
    static final String KEY_DEVICE_ID = "device_id";
    static final String KEY_DEVICE_SECRET = "device_secret";
    static final String KEY_DEVICE_FINGERPRINT = "device_fingerprint";
    static final String KEY_RECEIVER_NAME = "receiver_name";
    static final String KEY_RECEIVER_FINGERPRINT = "receiver_fingerprint";
    static final String KEY_SERVER_BASE = "server_base";
    static final String KEY_LAST_UPDATE_CHECK = "last_update_check";
    static final String KEY_SKIPPED_UPDATE_VERSION = "skipped_update_version";
    static final String KEY_PENDING_UPDATE_MANIFEST = "pending_update_manifest";
    static final String KEY_RECEIVE_ENABLED = "receive_enabled";
    static final String KEY_RECEIVE_CONTENT_MODE = "receive_content_mode";
    static final String KEY_LOCAL_RECEIVER_ID = "local_receiver_id";
    static final String KEY_LOCAL_RECEIVER_SECRET = "local_receiver_secret";
    static final String KEY_LOCAL_RECEIVER_FINGERPRINT = "local_receiver_fingerprint";

    private Prefs() {}

    static SharedPreferences get(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static String defaultServerUrl() {
        return ServerPolicy.officialNotifyUrl();
    }

    static String defaultServerBase() {
        return ServerPolicy.officialBase();
    }

    static boolean enabled(Context context) {
        return get(context).getBoolean(KEY_ENABLED, true);
    }

    static boolean receiveEnabled(Context context) {
        return get(context).getBoolean(KEY_RECEIVE_ENABLED, false);
    }

    static void setReceiveEnabled(Context context, boolean enabled) {
        get(context).edit().putBoolean(KEY_RECEIVE_ENABLED, enabled).apply();
    }

    static String receiveContentMode(Context context) {
        String value = get(context).getString(KEY_RECEIVE_CONTENT_MODE, "full");
        return "source".equals(value) || "title".equals(value) ? value : "full";
    }

    static void setReceiveContentMode(Context context, String mode) {
        String value = "source".equals(mode) || "title".equals(mode) ? mode : "full";
        get(context).edit().putString(KEY_RECEIVE_CONTENT_MODE, value).apply();
    }

    static String serverUrl(Context context) {
        SharedPreferences preferences = get(context);
        String official = defaultServerUrl();
        if (!official.equals(preferences.getString(KEY_SERVER_URL, official))) {
            preferences.edit().putString(KEY_SERVER_URL, official).apply();
        }
        return official;
    }

    static String packages(Context context) {
        return get(context).getString(KEY_PACKAGES, "");
    }

    static String keywords(Context context) {
        return get(context).getString(KEY_KEYWORDS, "");
    }

    static String privacy(Context context) {
        return get(context).getString(KEY_PRIVACY, "full");
    }

    static boolean filterAll(Context context) {
        SharedPreferences preferences = get(context);
        if (!preferences.contains(KEY_FILTER_ALL)) {
            return packages(context).trim().length() == 0;
        }
        return preferences.getBoolean(KEY_FILTER_ALL, true);
    }

    static Set<String> selectedPackages(Context context) {
        Set<String> result = new LinkedHashSet<>();
        String raw = packages(context);
        for (String value : raw.split("[,，\\s]+")) {
            String trimmed = value.trim();
            if (!trimmed.isEmpty()) result.add(trimmed);
        }
        return result;
    }

    static void savePackageSelection(Context context, boolean all, Set<String> packages) {
        StringBuilder joined = new StringBuilder();
        for (String value : packages) {
            if (joined.length() > 0) joined.append(',');
            joined.append(value);
        }
        get(context).edit()
                .putBoolean(KEY_FILTER_ALL, all)
                .putString(KEY_PACKAGES, joined.toString())
                .apply();
    }

    static boolean paired(Context context) {
        return !get(context).getString(KEY_DEVICE_ID, "").isEmpty()
                && !deviceSecret(context).isEmpty();
    }

    static String deviceId(Context context) {
        return get(context).getString(KEY_DEVICE_ID, "");
    }

    static String deviceSecret(Context context) {
        return SecretStore.read(context, get(context), KEY_DEVICE_SECRET);
    }

    static String deviceFingerprint(Context context) {
        return get(context).getString(KEY_DEVICE_FINGERPRINT, "");
    }

    static String receiverName(Context context) {
        return get(context).getString(KEY_RECEIVER_NAME, "");
    }

    static String receiverFingerprint(Context context) {
        return get(context).getString(KEY_RECEIVER_FINGERPRINT, "");
    }

    static boolean localReceiverReady(Context context) {
        return !localReceiverId(context).isEmpty() && !localReceiverSecret(context).isEmpty();
    }

    static String localReceiverId(Context context) {
        return get(context).getString(KEY_LOCAL_RECEIVER_ID, "");
    }

    static String localReceiverSecret(Context context) {
        return SecretStore.readSlot(
                context, get(context), KEY_LOCAL_RECEIVER_SECRET, "receiver");
    }

    static String localReceiverFingerprint(Context context) {
        return get(context).getString(KEY_LOCAL_RECEIVER_FINGERPRINT, "");
    }

    static void saveLocalReceiver(Context context, JSONObject pairing) {
        String receiverId = pairing.optString("receiverId", "");
        String receiverSecret = pairing.optString("receiverSecret", "");
        SharedPreferences preferences = get(context);
        if (receiverId.isEmpty()) receiverId = preferences.getString(KEY_LOCAL_RECEIVER_ID, "");
        if (receiverSecret.isEmpty()) receiverSecret = localReceiverSecret(context);
        if (receiverId.isEmpty() || receiverSecret.isEmpty()) {
            throw new IllegalStateException("无法安全保存接收凭据");
        }
        SharedPreferences.Editor editor = preferences.edit()
                .putString(KEY_LOCAL_RECEIVER_ID, receiverId)
                .putString(KEY_LOCAL_RECEIVER_FINGERPRINT,
                        pairing.optString("receiverFingerprint", ""));
        try {
            SecretStore.stageWriteSlot(
                    context, editor, receiverSecret, KEY_LOCAL_RECEIVER_SECRET, "receiver");
        } catch (Exception error) {
            throw new IllegalStateException("无法安全保存接收凭据");
        }
        if (!editor.commit()) throw new IllegalStateException("无法安全保存接收凭据");
    }

    static void clearLocalReceiver(Context context) {
        SharedPreferences.Editor editor = get(context).edit()
                .remove(KEY_LOCAL_RECEIVER_ID)
                .remove(KEY_LOCAL_RECEIVER_FINGERPRINT)
                .putBoolean(KEY_RECEIVE_ENABLED, false);
        SecretStore.stageClearSlot(editor, KEY_LOCAL_RECEIVER_SECRET, "receiver");
        if (editor.commit()) SecretStore.deleteKeySlot("receiver");
    }

    static String serverBase(Context context) {
        SharedPreferences preferences = get(context);
        String official = defaultServerBase();
        if (!official.equals(preferences.getString(KEY_SERVER_BASE, official))) {
            preferences.edit().putString(KEY_SERVER_BASE, official).apply();
        }
        return official;
    }

    static void savePairing(Context context, String serverBase, JSONObject device) {
        String trustedBase = ServerPolicy.requireOfficialBase(serverBase);
        JSONObject receiver = device.optJSONObject("receiver");
        if (receiver == null) receiver = new JSONObject();
        SharedPreferences preferences = get(context);
        String senderId = device.optString("senderId", "");
        String senderSecret = device.optString("senderSecret", "");
        if (senderId.isEmpty()) senderId = preferences.getString(KEY_DEVICE_ID, "");
        if (senderSecret.isEmpty()) senderSecret = deviceSecret(context);
        if (senderId.isEmpty() || senderSecret.isEmpty()) {
            throw new IllegalStateException("无法安全保存设备凭据");
        }
        SharedPreferences.Editor editor = preferences.edit()
                .putString(KEY_SERVER_BASE, trustedBase)
                .putString(KEY_SERVER_URL, ServerPolicy.officialNotifyUrl())
                .putString(KEY_DEVICE_ID, senderId)
                .putString(KEY_DEVICE_FINGERPRINT, device.optString("senderFingerprint", ""))
                .putString(KEY_RECEIVER_NAME, receiver.optString("name", ""))
                .putString(KEY_RECEIVER_FINGERPRINT, receiver.optString("fingerprint", ""));
        try {
            SecretStore.stageWrite(context, editor, senderSecret, KEY_DEVICE_SECRET);
        } catch (Exception error) {
            throw new IllegalStateException("无法安全保存设备凭据");
        }
        if (!editor.commit()) throw new IllegalStateException("无法安全保存设备凭据");
    }

    static void clearPairing(Context context) {
        SharedPreferences.Editor editor = get(context).edit()
                .remove(KEY_DEVICE_ID)
                .remove(KEY_DEVICE_FINGERPRINT)
                .remove(KEY_RECEIVER_NAME)
                .remove(KEY_RECEIVER_FINGERPRINT)
                .remove(KEY_SERVER_BASE)
                .putString(KEY_SERVER_URL, defaultServerUrl());
        SecretStore.stageClear(editor, KEY_DEVICE_SECRET);
        if (editor.commit()) SecretStore.deleteKey();
    }

    static long lastUpdateCheck(Context context) {
        return get(context).getLong(KEY_LAST_UPDATE_CHECK, 0L);
    }

    static void markUpdateCheck(Context context, long timestamp) {
        get(context).edit().putLong(KEY_LAST_UPDATE_CHECK, timestamp).apply();
    }

    static long skippedUpdateVersion(Context context) {
        return get(context).getLong(KEY_SKIPPED_UPDATE_VERSION, -1L);
    }

    static void skipUpdateVersion(Context context, long versionCode) {
        get(context).edit().putLong(KEY_SKIPPED_UPDATE_VERSION, versionCode).apply();
    }

    static boolean savePendingUpdate(Context context, String manifest) {
        return get(context).edit()
                .putString(KEY_PENDING_UPDATE_MANIFEST, manifest)
                .commit();
    }

    static void clearPendingUpdate(Context context) {
        get(context).edit().remove(KEY_PENDING_UPDATE_MANIFEST).commit();
    }
}
