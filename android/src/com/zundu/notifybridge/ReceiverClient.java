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
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

final class ReceiverClient {
    interface PairingCallback {
        void done(boolean ok, String message, JSONObject pairing);
    }

    interface StatusCallback {
        void done(boolean ok, String message, boolean paired);
    }

    interface SendersCallback {
        void done(boolean ok, String message, JSONArray senders);
    }

    interface ActionCallback {
        void done(boolean ok, String message);
    }

    private static final ExecutorService EXECUTOR = Executors.newSingleThreadExecutor();

    private ReceiverClient() {}

    static void startPairing(final Context context, final PairingCallback callback) {
        EXECUTOR.execute(new Runnable() {
            @Override public void run() {
                HttpURLConnection connection = null;
                try {
                    connection = open(context, "/pair/start", "POST");
                    JSONObject body = new JSONObject();
                    body.put("deviceName", Build.MANUFACTURER + " " + Build.MODEL + " 的 Android");
                    body.put("platform", "android");
                    write(connection, body);
                    JSONObject response = response(connection);
                    JSONObject pairing = response.optJSONObject("pairing");
                    if (!response.optBoolean("ok") || pairing == null) {
                        throw new IllegalStateException(response.optString("error", "生成配对码失败"));
                    }
                    Prefs.saveLocalReceiver(context, pairing);
                    ReceiverBridgeService.credentialsChanged();
                    callback.done(true, "配对码已生成", pairing);
                } catch (Exception error) {
                    callback.done(false, safeMessage(error, "生成配对码失败"), null);
                } finally {
                    if (connection != null) connection.disconnect();
                }
            }
        });
    }

    static void pairingStatus(
            final Context context, final String pairingId, final StatusCallback callback) {
        EXECUTOR.execute(new Runnable() {
            @Override public void run() {
                HttpURLConnection connection = null;
                try {
                    String query = pairingId == null || pairingId.isEmpty() ? ""
                            : "?pairingId=" + URLEncoder.encode(pairingId, "UTF-8");
                    connection = open(context, "/pair/status" + query, "GET");
                    JSONObject response = response(connection);
                    if (!response.optBoolean("ok")) {
                        throw new IllegalStateException(response.optString("error", "读取配对状态失败"));
                    }
                    callback.done(true, response.optBoolean("paired") ? "配对成功" : "等待发送设备连接",
                            response.optBoolean("paired"));
                } catch (Exception error) {
                    callback.done(false, safeMessage(error, "读取配对状态失败"), false);
                } finally {
                    if (connection != null) connection.disconnect();
                }
            }
        });
    }

    static void senders(final Context context, final SendersCallback callback) {
        EXECUTOR.execute(new Runnable() {
            @Override public void run() {
                HttpURLConnection connection = null;
                try {
                    connection = open(context, ReceiverSenderContract.listPath(), "GET");
                    JSONObject response = response(connection);
                    if (!response.optBoolean("ok")) {
                        throw new IllegalStateException(
                                response.optString("error", "读取发送设备失败"));
                    }
                    JSONArray senders = response.optJSONArray("senders");
                    callback.done(true, "发送设备已更新",
                            senders == null ? new JSONArray() : senders);
                } catch (Exception error) {
                    callback.done(false, safeMessage(error, "读取发送设备失败"), null);
                } finally {
                    if (connection != null) connection.disconnect();
                }
            }
        });
    }

    static void revokeSender(
            final Context context, final String senderId, final ActionCallback callback) {
        EXECUTOR.execute(new Runnable() {
            @Override public void run() {
                HttpURLConnection connection = null;
                try {
                    JSONObject payload = new JSONObject();
                    payload.put("senderId", ReceiverSenderContract.requireSenderId(senderId));
                    connection = open(context, ReceiverSenderContract.revokePath(), "POST");
                    write(connection, payload);
                    JSONObject response = response(connection);
                    if (!response.optBoolean("ok")) {
                        throw new IllegalStateException(
                                response.optString("error", "删除发送设备失败"));
                    }
                    callback.done(true, "已删除所选发送设备");
                } catch (Exception error) {
                    callback.done(false, safeMessage(error, "删除发送设备失败"));
                } finally {
                    if (connection != null) connection.disconnect();
                }
            }
        });
    }

    private static HttpURLConnection open(Context context, String path, String method)
            throws Exception {
        URL url = new URL(ServerPolicy.officialBase() + path);
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        connection.setInstanceFollowRedirects(false);
        connection.setConnectTimeout(5000);
        connection.setReadTimeout(8000);
        connection.setRequestMethod(method);
        connection.setRequestProperty("Connection", "close");
        if ("POST".equals(method)) {
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            connection.setDoOutput(true);
        }
        if (Prefs.localReceiverReady(context)) {
            connection.setRequestProperty("Authorization", "Bearer "
                    + Prefs.localReceiverId(context) + "." + Prefs.localReceiverSecret(context));
        }
        return connection;
    }

    private static void write(HttpURLConnection connection, JSONObject body) throws Exception {
        byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
        connection.setFixedLengthStreamingMode(bytes.length);
        OutputStream output = connection.getOutputStream();
        output.write(bytes);
        output.close();
    }

    private static JSONObject response(HttpURLConnection connection) throws Exception {
        int status = connection.getResponseCode();
        InputStream input = status >= 200 && status < 300
                ? connection.getInputStream() : connection.getErrorStream();
        JSONObject body = new JSONObject(read(input));
        if (status < 200 || status >= 300) {
            throw new IllegalStateException(body.optString("error", "服务器拒绝请求"));
        }
        return body;
    }

    private static String read(InputStream input) throws Exception {
        if (input == null) return "{}";
        BufferedReader reader = new BufferedReader(
                new InputStreamReader(input, StandardCharsets.UTF_8));
        StringBuilder value = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            if (value.length() > 65536) throw new IllegalStateException("服务器响应过大");
            value.append(line);
        }
        return value.toString();
    }

    private static String safeMessage(Exception error, String fallback) {
        String message = error == null ? "" : error.getMessage();
        return message == null || message.trim().isEmpty() ? fallback : message.trim();
    }
}
