package com.zundu.notifybridge;

import android.content.Context;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

final class PairingClient {
    interface Callback {
        void done(boolean ok, String message, JSONObject device);
    }

    interface DestinationsCallback {
        void done(boolean ok, String message, JSONArray destinations);
    }

    interface BarkEnrollmentCallback {
        void done(boolean ok, String message, JSONObject enrollment);
    }

    interface ActionCallback {
        void done(boolean ok, String message);
    }

    private static final ExecutorService EXECUTOR = Executors.newSingleThreadExecutor();

    private PairingClient() {}

    static void claim(final Context context, final String serverBase, final String code, final Callback callback) {
        EXECUTOR.execute(new Runnable() {
            @Override
            public void run() {
                String preferredBase;
                try {
                    preferredBase = ServerPolicy.requireOfficialBase(serverBase);
                } catch (IllegalArgumentException invalidServer) {
                    callback.done(false, invalidServer.getMessage(), null);
                    return;
                }
                Set<String> candidates = new LinkedHashSet<>();
                candidates.add(preferredBase);
                Exception lastError = null;
                for (String candidate : candidates) {
                    try {
                        JSONObject response = claimAt(context, candidate, code);
                        JSONObject device = response.getJSONObject("device");
                        Prefs.savePairing(context, candidate, device);
                        DiagnosticLog.add(context, "info", "PAIR_OK");
                        callback.done(true, "配对成功", device);
                        return;
                    } catch (PairingRejected rejected) {
                        DiagnosticLog.add(context, "error", "PAIR_REJECTED");
                        callback.done(false, rejected.getMessage(), null);
                        return;
                    } catch (Exception exception) {
                        lastError = exception;
                    }
                }
                callback.done(false, lastError == null
                        ? "无法连接通知服务"
                        : lastError.getClass().getSimpleName() + ": " + lastError.getMessage(), null);
                DiagnosticLog.add(context, "error", "PAIR_NETWORK_FAILED");
            }
        });
    }

    static void destinations(final Context context, final DestinationsCallback callback) {
        EXECUTOR.execute(new Runnable() {
            @Override
            public void run() {
                Set<String> candidates = new LinkedHashSet<>();
                candidates.add(ServerPolicy.officialBase());
                Exception lastError = null;
                for (String candidate : candidates) {
                    try {
                        JSONObject response = destinationsAt(context, candidate);
                        callback.done(true, "连接正常", response.optJSONArray("destinations"));
                        return;
                    } catch (Exception exception) {
                        lastError = exception;
                    }
                }
                callback.done(false, lastError == null ? "无法连接通知服务" : lastError.getMessage(), null);
            }
        });
    }

    static void startBarkEnrollment(
            final Context context, final BarkEnrollmentCallback callback) {
        EXECUTOR.execute(new Runnable() {
            @Override
            public void run() {
                Exception lastError = null;
                for (String candidate : candidateBases(context)) {
                    try {
                        JSONObject response = authenticatedPostAt(
                                context, candidate, "/v1/bark/enroll/start", new JSONObject());
                        callback.done(
                                true, "绑定码已生成", response.optJSONObject("enrollment"));
                        return;
                    } catch (Exception exception) {
                        lastError = exception;
                    }
                }
                callback.done(false, lastError == null
                        ? "无法连接服务器" : lastError.getMessage(), null);
            }
        });
    }

    static void testBark(
            final Context context, final String destinationId, final ActionCallback callback) {
        barkAction(context, "/v1/bark/test", destinationId, "测试通知已发送", callback);
    }

    static void revokeBark(
            final Context context, final String destinationId, final ActionCallback callback) {
        barkAction(context, "/v1/bark/revoke", destinationId, "iPhone 已移除", callback);
    }

    static void selfRevoke(final Context context, final ActionCallback callback) {
        EXECUTOR.execute(new Runnable() {
            @Override
            public void run() {
                try {
                    authenticatedPostAt(
                            context,
                            ServerPolicy.officialBase(),
                            "/v1/device/revoke",
                            new JSONObject());
                    callback.done(true, "已解除全部连接");
                } catch (Exception exception) {
                    callback.done(false, exception.getMessage());
                }
            }
        });
    }

    private static void barkAction(
            final Context context, final String path, final String destinationId,
            final String successMessage, final ActionCallback callback) {
        EXECUTOR.execute(new Runnable() {
            @Override
            public void run() {
                Exception lastError = null;
                for (String candidate : candidateBases(context)) {
                    try {
                        JSONObject payload = new JSONObject();
                        payload.put("destinationId", destinationId);
                        authenticatedPostAt(context, candidate, path, payload);
                        callback.done(true, successMessage);
                        return;
                    } catch (Exception exception) {
                        lastError = exception;
                    }
                }
                callback.done(false, lastError == null
                        ? "无法连接服务器" : lastError.getMessage());
            }
        });
    }

    private static JSONObject claimAt(Context context, String base, String code) throws Exception {
        HttpURLConnection connection = null;
        try {
            URL url = new URL(base + "/pair/claim");
            connection = (HttpURLConnection) url.openConnection();
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(4500);
            connection.setReadTimeout(7000);
            connection.setRequestMethod("POST");
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            connection.setRequestProperty("Connection", "close");
            if (Prefs.paired(context)) {
                connection.setRequestProperty(
                        "Authorization",
                        "Bearer " + Prefs.deviceId(context) + "." + Prefs.deviceSecret(context));
            }
            connection.setDoOutput(true);

            JSONObject payload = new JSONObject();
            payload.put("code", code);
            payload.put("deviceName", Build.MANUFACTURER + " " + Build.MODEL);
            payload.put("platform", "android");
            byte[] bytes = payload.toString().getBytes(StandardCharsets.UTF_8);
            connection.setFixedLengthStreamingMode(bytes.length);
            OutputStream output = connection.getOutputStream();
            output.write(bytes);
            output.close();

            int status = connection.getResponseCode();
            InputStream stream = status >= 200 && status < 300
                    ? connection.getInputStream() : connection.getErrorStream();
            JSONObject response = new JSONObject(read(stream));
            if (status >= 400 && status < 500) {
                throw new PairingRejected(response.optString("error", "配对失败"));
            }
            if (status < 200 || status >= 300 || !response.optBoolean("ok")) {
                throw new IllegalStateException(response.optString("error", "配对失败"));
            }
            return response;
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private static JSONObject destinationsAt(Context context, String base) throws Exception {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(base + "/v1/destinations").openConnection();
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(4000);
            connection.setReadTimeout(6000);
            connection.setRequestMethod("GET");
            connection.setRequestProperty("Connection", "close");
            connection.setRequestProperty(
                    "Authorization",
                    "Bearer " + Prefs.deviceId(context) + "." + Prefs.deviceSecret(context));
            int status = connection.getResponseCode();
            InputStream stream = status >= 200 && status < 300
                    ? connection.getInputStream() : connection.getErrorStream();
            JSONObject response = new JSONObject(read(stream));
            if (status < 200 || status >= 300 || !response.optBoolean("ok")) {
                throw new IllegalStateException(response.optString("error", "读取接收设备失败"));
            }
            return response;
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private static JSONObject authenticatedPostAt(
            Context context, String base, String path, JSONObject payload) throws Exception {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(base + path).openConnection();
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(4500);
            connection.setReadTimeout(16000);
            connection.setRequestMethod("POST");
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            connection.setRequestProperty("Connection", "close");
            connection.setRequestProperty(
                    "Authorization",
                    "Bearer " + Prefs.deviceId(context) + "." + Prefs.deviceSecret(context));
            connection.setDoOutput(true);
            byte[] bytes = payload.toString().getBytes(StandardCharsets.UTF_8);
            connection.setFixedLengthStreamingMode(bytes.length);
            OutputStream output = connection.getOutputStream();
            output.write(bytes);
            output.close();

            int status = connection.getResponseCode();
            InputStream stream = status >= 200 && status < 300
                    ? connection.getInputStream() : connection.getErrorStream();
            JSONObject response = new JSONObject(read(stream));
            if (status < 200 || status >= 300 || !response.optBoolean("ok")) {
                throw new IllegalStateException(response.optString("error", "操作失败"));
            }
            return response;
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private static Set<String> candidateBases(Context context) {
        Set<String> candidates = new LinkedHashSet<>();
        candidates.add(ServerPolicy.officialBase());
        return candidates;
    }

    private static String normalizeBase(String value) {
        return ServerPolicy.requireOfficialBase(value);
    }

    private static String read(InputStream stream) throws Exception {
        if (stream == null) return "{}";
        BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8));
        StringBuilder result = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) result.append(line);
        reader.close();
        return result.toString();
    }

    private static final class PairingRejected extends Exception {
        PairingRejected(String message) { super(message); }
    }
}
