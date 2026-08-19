package com.zundu.notifybridge;

import android.app.ActivityManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.pm.PackageInfo;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkInfo;
import android.os.Build;
import android.provider.Settings;

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

final class ServerClient {
    interface StatusCallback {
        void done(String status);
    }

    interface UploadCallback {
        void done(boolean ok, String message, String diagnosticId);
    }

    static final String ONLINE = "online";
    static final String OFFLINE = "offline";
    static final String UNREACHABLE = "unreachable";
    static final String AUTH_FAILED = "auth_failed";

    private static final ExecutorService EXECUTOR = Executors.newSingleThreadExecutor();
    private static volatile String lastLoggedStatus = "";

    private ServerClient() {}

    static void check(final Context context, final StatusCallback callback) {
        if (!hasNetwork(context)) {
            logStatus(context, OFFLINE, "warning", "NETWORK_OFFLINE", 0);
            callback.done(OFFLINE);
            return;
        }
        EXECUTOR.execute(new Runnable() {
            @Override public void run() {
                boolean paired = Prefs.paired(context);
                for (String base : candidates(context)) {
                    HttpURLConnection connection = null;
                    try {
                        String route = paired ? "v1/device-status" : "v1/health";
                        connection = open(context, base, route, "GET", paired);
                        int status = connection.getResponseCode();
                        if (status >= 200 && status < 300) {
                            logStatus(context, ONLINE, "info", "SERVER_ONLINE", status);
                            callback.done(ONLINE);
                            return;
                        }
                        if (status == 401 || status == 403) {
                            logStatus(context, AUTH_FAILED, "error", "AUTH_FAILED", status);
                            callback.done(AUTH_FAILED);
                            return;
                        }
                    } catch (Exception ignored) {
                    } finally {
                        if (connection != null) connection.disconnect();
                    }
                }
                logStatus(context, UNREACHABLE, "error", "SERVER_UNREACHABLE", 0);
                callback.done(UNREACHABLE);
            }
        });
    }

    static void uploadDiagnostics(final Context context, final UploadCallback callback) {
        if (!Prefs.paired(context)) {
            callback.done(false, "请先连接接收设备", "");
            return;
        }
        if (!hasNetwork(context)) {
            callback.done(false, "无网络连接", "");
            return;
        }
        EXECUTOR.execute(new Runnable() {
            @Override public void run() {
                for (String base : candidates(context)) {
                    HttpURLConnection connection = null;
                    try {
                        JSONObject payload = new JSONObject();
                        payload.put("appVersion", appVersion(context));
                        payload.put("platformVersion", "Android-" + Build.VERSION.RELEASE);
                        payload.put("networkStatus", "online");
                        payload.put("serverStatus", "online");
                        payload.put("paired", true);
                        payload.put("listenerEnabled", listenerEnabled(context));
                        payload.put("backgroundRestricted", backgroundRestricted(context));
                        payload.put("entries", DiagnosticLog.entries(context));
                        byte[] bytes = payload.toString().getBytes(StandardCharsets.UTF_8);
                        connection = open(context, base, "v1/diagnostics", "POST", true);
                        connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                        connection.setDoOutput(true);
                        connection.setFixedLengthStreamingMode(bytes.length);
                        OutputStream output = connection.getOutputStream();
                        output.write(bytes);
                        output.close();
                        int status = connection.getResponseCode();
                        JSONObject response = new JSONObject(read(
                                status >= 200 && status < 300
                                        ? connection.getInputStream() : connection.getErrorStream()));
                        if (status >= 200 && status < 300 && response.optBoolean("ok")) {
                            String diagnosticId = response.optString("diagnosticId", "");
                            DiagnosticLog.add(context, "info", "DIAGNOSTIC_UPLOAD_OK", status);
                            callback.done(true, "上传成功", diagnosticId);
                            return;
                        }
                        if (status == 401 || status == 403) {
                            callback.done(false, "需要重新连接", "");
                            return;
                        }
                        if (status == 429) {
                            callback.done(false, "上传过于频繁，请稍后再试", "");
                            return;
                        }
                    } catch (Exception ignored) {
                    } finally {
                        if (connection != null) connection.disconnect();
                    }
                }
                DiagnosticLog.add(context, "error", "DIAGNOSTIC_UPLOAD_FAILED");
                callback.done(false, "服务器不可用", "");
            }
        });
    }

    static boolean hasNetwork(Context context) {
        ConnectivityManager manager = (ConnectivityManager)
                context.getSystemService(Context.CONNECTIVITY_SERVICE);
        if (manager == null) return false;
        if (Build.VERSION.SDK_INT >= 23) {
            Network network = manager.getActiveNetwork();
            NetworkCapabilities capabilities = network == null
                    ? null : manager.getNetworkCapabilities(network);
            return capabilities != null
                    && capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);
        }
        NetworkInfo info = manager.getActiveNetworkInfo();
        return info != null && info.isConnected();
    }

    private static synchronized void logStatus(
            Context context, String status, String level, String code, int httpStatus) {
        if (status.equals(lastLoggedStatus)) return;
        lastLoggedStatus = status;
        DiagnosticLog.add(context, level, code, httpStatus);
    }

    private static boolean listenerEnabled(Context context) {
        String enabled = Settings.Secure.getString(
                context.getContentResolver(), "enabled_notification_listeners");
        String component = new ComponentName(context, NotifyBridgeService.class).flattenToString();
        return ComponentAccess.contains(enabled, component);
    }

    private static boolean backgroundRestricted(Context context) {
        if (Build.VERSION.SDK_INT < 28) return false;
        ActivityManager manager = (ActivityManager)
                context.getSystemService(Context.ACTIVITY_SERVICE);
        return manager != null && manager.isBackgroundRestricted();
    }

    private static HttpURLConnection open(
            Context context, String base, String route, String method, boolean authenticated)
            throws Exception {
        HttpURLConnection connection = (HttpURLConnection)
                new URL(endpoint(base, route)).openConnection();
        connection.setInstanceFollowRedirects(false);
        connection.setConnectTimeout(4500);
        connection.setReadTimeout(7000);
        connection.setRequestMethod(method);
        connection.setRequestProperty("Connection", "close");
        if (authenticated) {
            connection.setRequestProperty("Authorization",
                    "Bearer " + Prefs.deviceId(context) + "." + Prefs.deviceSecret(context));
        }
        return connection;
    }

    private static Set<String> candidates(Context context) {
        LinkedHashSet<String> values = new LinkedHashSet<>();
        values.add(ServerPolicy.officialBase());
        return values;
    }

    private static String endpoint(String base, String route) throws Exception {
        String trusted = ServerPolicy.requireOfficialBase(base);
        return trusted + "/" + route.replaceFirst("^/+", "");
    }

    private static String normalize(String value) {
        return ServerPolicy.requireOfficialBase(value);
    }

    private static String appVersion(Context context) {
        try {
            PackageInfo info = context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
            return info.versionName == null ? "" : info.versionName;
        } catch (Exception ignored) {
            return "";
        }
    }

    private static String read(InputStream stream) throws Exception {
        if (stream == null) return "{}";
        BufferedReader reader = new BufferedReader(
                new InputStreamReader(stream, StandardCharsets.UTF_8));
        StringBuilder result = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) result.append(line);
        reader.close();
        return result.toString();
    }
}
