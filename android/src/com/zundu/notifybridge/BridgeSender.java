package com.zundu.notifybridge;

import android.content.Context;
import android.os.Build;
import android.util.Log;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.OutputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

final class BridgeSender {
    private static final String TAG = "XXZFBridge";
    interface Callback {
        void done(boolean ok, String message);
    }

    private static final ExecutorService EXECUTOR = Executors.newSingleThreadExecutor();

    private BridgeSender() {}

    static void send(final Context context, final JSONObject payload, final Callback callback) {
        final List<String> targets = Collections.singletonList(
                ServerPolicy.officialNotifyUrl());
        EXECUTOR.execute(new Runnable() {
            @Override
            public void run() {
                String lastError = "No server URL";
                try {
                    payload.put("device", Build.MANUFACTURER + " " + Build.MODEL);
                } catch (Exception ignored) {
                }
                for (String target : targets) {
                    HttpURLConnection conn = null;
                    try {
                        URL url = new URL(target);
                        conn = (HttpURLConnection) url.openConnection();
                        conn.setInstanceFollowRedirects(false);
                        conn.setConnectTimeout(4000);
                        conn.setReadTimeout(5000);
                        conn.setRequestMethod("POST");
                        conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                        conn.setRequestProperty("Connection", "close");
                        if (Prefs.paired(context)) {
                            conn.setRequestProperty(
                                    "Authorization",
                                    "Bearer " + Prefs.deviceId(context) + "."
                                            + Prefs.deviceSecret(context));
                        }
                        conn.setDoOutput(true);
                        byte[] data = payload.toString().getBytes(StandardCharsets.UTF_8);
                        conn.setFixedLengthStreamingMode(data.length);
                        OutputStream out = conn.getOutputStream();
                        out.write(data);
                        out.close();

                        int code = conn.getResponseCode();
                        BufferedReader reader = new BufferedReader(new InputStreamReader(
                                code >= 200 && code < 300
                                        ? conn.getInputStream() : conn.getErrorStream(),
                                StandardCharsets.UTF_8));
                        while (reader.readLine() != null) {
                            // Consume the bounded server response without logging its content.
                        }
                        reader.close();

                        boolean ok = code >= 200 && code < 300;
                        if (ok) {
                            String via = safeTarget(url);
                            Log.i(TAG, "sent via " + via);
                            DiagnosticLog.add(context, "info", "SEND_OK", code);
                            if (callback != null) {
                                callback.done(true, "via " + via + " HTTP " + code);
                            }
                            return;
                        }
                        lastError = "via " + safeTarget(url) + " HTTP " + code;
                        DiagnosticLog.add(context, "error", "SEND_HTTP_FAILED", code);
                    } catch (Exception e) {
                        lastError = e.getClass().getSimpleName() + ": " + e.getMessage();
                        Log.e(TAG, "send failed", e);
                        DiagnosticLog.add(context, "error", "SEND_NETWORK_FAILED");
                    } finally {
                        if (conn != null) conn.disconnect();
                    }
                }
                if (callback != null) callback.done(false, lastError);
            }
        });
    }

    private static String safeTarget(URL url) {
        int port = url.getPort();
        String value = url.getProtocol() + "://" + url.getHost();
        if (port > 0) value += ":" + port;
        value += url.getPath();
        return value;
    }
}
