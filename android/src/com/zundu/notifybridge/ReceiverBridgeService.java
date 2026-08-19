package com.zundu.notifybridge;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.net.ConnectivityManager;
import android.net.NetworkInfo;
import android.os.Bundle;
import android.os.IBinder;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashSet;
import java.util.Set;

public class ReceiverBridgeService extends Service {
    static final String EXTRA_RECEIVER_DELIVERY = "xxzf_receiver_delivery";
    private static final String SERVICE_CHANNEL = "xxzf_receive_connection";
    private static final String MESSAGE_CHANNEL = "xxzf_received_messages";
    private static final int SERVICE_NOTIFICATION_ID = 230714;
    private static volatile String currentStatus = "未启动";
    private static volatile boolean running;

    private final Set<String> delivered = new LinkedHashSet<>();
    private volatile boolean stopped;
    private volatile HttpURLConnection activeConnection;
    private Thread worker;

    static void start(Context context) {
        if (!Prefs.receiveEnabled(context) || !Prefs.localReceiverReady(context)) return;
        if (running || "需要重新连接".equals(currentStatus)) return;
        context.startForegroundService(new Intent(context, ReceiverBridgeService.class));
    }

    static void credentialsChanged() {
        currentStatus = "未启动";
    }

    static void stop(Context context) {
        context.stopService(new Intent(context, ReceiverBridgeService.class));
        currentStatus = "已停止";
    }

    static String status() {
        return currentStatus;
    }

    static boolean isRunning() {
        return running;
    }

    @Override public void onCreate() {
        super.onCreate();
        createChannels();
        running = true;
        stopped = false;
        currentStatus = "正在连接服务器";
        startForeground(SERVICE_NOTIFICATION_ID, serviceNotification(currentStatus));
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (!Prefs.receiveEnabled(this) || !Prefs.localReceiverReady(this)) {
            stopSelf();
            return START_NOT_STICKY;
        }
        if (worker == null || !worker.isAlive()) {
            worker = new Thread(new Runnable() {
                @Override public void run() { receiveLoop(); }
            }, "XXZF-Receiver");
            worker.start();
        }
        return START_STICKY;
    }

    @Override public void onDestroy() {
        stopped = true;
        HttpURLConnection connection = activeConnection;
        if (connection != null) connection.disconnect();
        if (worker != null) worker.interrupt();
        worker = null;
        running = false;
        if (!"需要重新连接".equals(currentStatus)) currentStatus = "已停止";
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) {
        return null;
    }

    private void receiveLoop() {
        while (!stopped && Prefs.receiveEnabled(this)) {
            if (!networkAvailable()) {
                updateStatus("无网络连接");
                sleep(2500);
                continue;
            }
            HttpURLConnection connection = null;
            try {
                connection = (HttpURLConnection) new URL(
                        ServerPolicy.officialBase() + "/v1/events").openConnection();
                activeConnection = connection;
                connection.setInstanceFollowRedirects(false);
                connection.setConnectTimeout(8000);
                connection.setReadTimeout(65000);
                connection.setRequestMethod("GET");
                connection.setRequestProperty("Accept", "text/event-stream");
                connection.setRequestProperty("Cache-Control", "no-cache");
                connection.setRequestProperty("Authorization", "Bearer "
                        + Prefs.localReceiverId(this) + "." + Prefs.localReceiverSecret(this));
                int response = connection.getResponseCode();
                if (response == 401 || response == 403) {
                    updateStatus("需要重新连接");
                    DiagnosticLog.add(this, "error", "RECEIVER_AUTH_FAILED");
                    break;
                }
                if (response != 200) throw new IllegalStateException("HTTP " + response);
                updateStatus("服务器在线");
                DiagnosticLog.add(this, "info", "RECEIVER_STREAM_CONNECTED");
                readStream(connection.getInputStream());
            } catch (Exception error) {
                if (!stopped) {
                    updateStatus(networkAvailable() ? "服务器不可用" : "无网络连接");
                    DiagnosticLog.add(this, "warning", "RECEIVER_STREAM_DISCONNECTED");
                    sleep(2000);
                }
            } finally {
                activeConnection = null;
                if (connection != null) connection.disconnect();
            }
        }
        running = false;
        if (!Prefs.receiveEnabled(this)) currentStatus = "已停止";
        stopSelf();
    }

    private void readStream(InputStream input) throws Exception {
        BufferedReader reader = new BufferedReader(
                new InputStreamReader(input, StandardCharsets.UTF_8));
        String event = "";
        StringBuilder data = new StringBuilder();
        String line;
        while (!stopped && (line = reader.readLine()) != null) {
            if (line.length() == 0) {
                if ("notify".equals(event) && data.length() > 0) {
                    deliver(new JSONObject(data.toString()));
                }
                event = "";
                data.setLength(0);
            } else if (line.startsWith("event:")) {
                event = line.substring(6).trim();
            } else if (line.startsWith("data:")) {
                if (data.length() > 0) data.append('\n');
                if (data.length() > 65536) throw new IllegalStateException("事件过大");
                data.append(line.substring(5).trim());
            }
        }
        if (!stopped) throw new IllegalStateException("连接已关闭");
    }

    private void deliver(JSONObject event) {
        String fingerprint = event.optString("id") + "|" + event.optLong("postTime");
        synchronized (delivered) {
            if (delivered.contains(fingerprint)) return;
            delivered.add(fingerprint);
            while (delivered.size() > 200) {
                String first = delivered.iterator().next();
                delivered.remove(first);
            }
        }
        ReceiverEventFormatter.Display display = ReceiverEventFormatter.format(
                event.optString("appName", event.optString("packageName", "未知应用")),
                event.optString("title", ""), event.optString("text", ""),
                event.optString("privacyMode", "full"), Prefs.receiveContentMode(this));
        Notification.Builder builder = new Notification.Builder(this, MESSAGE_CHANNEL)
                .setSmallIcon(com.zundu.notifybridge.R.drawable.ic_launcher)
                .setContentTitle(display.title)
                .setAutoCancel(true)
                .setContentIntent(mainPendingIntent());
        Bundle extras = new Bundle();
        extras.putBoolean(EXTRA_RECEIVER_DELIVERY, true);
        builder.addExtras(extras);
        if (!display.body.isEmpty()) {
            builder.setContentText(display.body.replace('\n', ' '));
            builder.setStyle(new Notification.BigTextStyle().bigText(display.body));
        }
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (manager != null) manager.notify(fingerprint.hashCode(), builder.build());
        DiagnosticLog.add(this, "info", "RECEIVER_NOTIFICATION_DELIVERED");
    }

    private PendingIntent mainPendingIntent() {
        Intent intent = new Intent(this, MainActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        return PendingIntent.getActivity(this, 230714, intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    private Notification serviceNotification(String value) {
        return new Notification.Builder(this, SERVICE_CHANNEL)
                .setSmallIcon(com.zundu.notifybridge.R.drawable.ic_launcher)
                .setContentTitle("转发 · 接收通知")
                .setContentText(value)
                .setOngoing(true)
                .setContentIntent(mainPendingIntent())
                .build();
    }

    private void updateStatus(String value) {
        currentStatus = value;
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (manager != null) manager.notify(SERVICE_NOTIFICATION_ID, serviceNotification(value));
    }

    private void createChannels() {
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (manager == null) return;
        NotificationChannel service = new NotificationChannel(
                SERVICE_CHANNEL, "接收连接", NotificationManager.IMPORTANCE_LOW);
        service.setDescription("保持跨设备通知接收连接");
        manager.createNotificationChannel(service);
        NotificationChannel messages = new NotificationChannel(
                MESSAGE_CHANNEL, "转发通知", NotificationManager.IMPORTANCE_DEFAULT);
        messages.setDescription("显示其他设备转发来的通知");
        manager.createNotificationChannel(messages);
    }

    private boolean networkAvailable() {
        ConnectivityManager manager = (ConnectivityManager)
                getSystemService(Context.CONNECTIVITY_SERVICE);
        NetworkInfo info = manager == null ? null : manager.getActiveNetworkInfo();
        return info != null && info.isConnected();
    }

    private static void sleep(long millis) {
        try { Thread.sleep(millis); } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt();
        }
    }
}
