package com.zundu.notifybridge;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.util.Log;

import org.json.JSONObject;

public class DebugReceiver extends BroadcastReceiver {
    private static final String TAG = "XXZFDebug";
    private static final String CHANNEL_ID = "xxzf_debug";

    @Override
    public void onReceive(final Context context, Intent intent) {
        if (intent == null || intent.getAction() == null) return;
        String action = intent.getAction();
        try {
            if ("com.zundu.notifybridge.SEND_TEST".equals(action)) {
                String appName = valueOrDefault(intent.getStringExtra("appName"), "转发");
                String title = valueOrDefault(intent.getStringExtra("title"), "ADB 直连测试");
                String text = valueOrDefault(intent.getStringExtra("text"), "安卓已直接上报到 mini");
                JSONObject payload = new JSONObject();
                payload.put("id", "adb-test-" + System.currentTimeMillis());
                payload.put("packageName", context.getPackageName());
                payload.put("appName", appName);
                payload.put("title", title);
                payload.put("text", text);
                payload.put("postTime", System.currentTimeMillis());
                payload.put("privacyMode", Prefs.privacy(context));
                BridgeSender.send(context, payload, new BridgeSender.Callback() {
                    @Override
                    public void done(boolean ok, String message) {
                        LogStore.add(context, (ok ? "ADB 测试成功 " : "ADB 测试失败 ") + message);
                        Log.i(TAG, "direct test " + ok + " " + message);
                    }
                });
                return;
            }

            if ("com.zundu.notifybridge.POST_TEST_NOTIFICATION".equals(action)) {
                postNotification(context);
                return;
            }

            if ("com.zundu.notifybridge.CLEAR_LOGS".equals(action)) {
                LogStore.clear(context);
                Log.i(TAG, "logs cleared");
            }
        } catch (Exception e) {
            Log.e(TAG, "debug receiver error", e);
            LogStore.add(context, "ADB 调试异常 " + e.getMessage());
        }
    }

    private void postNotification(Context context) {
        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) return;
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel channel = new NotificationChannel(CHANNEL_ID, "讯桥测试", NotificationManager.IMPORTANCE_DEFAULT);
            manager.createNotificationChannel(channel);
        }
        Notification.Builder builder = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(context, CHANNEL_ID)
                : new Notification.Builder(context);
        Notification notification = builder
                .setSmallIcon(android.R.drawable.stat_notify_chat)
                .setContentTitle("监听测试通知")
                .setContentText("如果这条被转发，真实通知监听链路已通")
                .setAutoCancel(true)
                .build();
        manager.notify(230709, notification);
        LogStore.add(context, "ADB 已发送本机通知");
        Log.i(TAG, "posted local notification");
    }

    private static String valueOrDefault(String value, String fallback) {
        return value == null || value.trim().length() == 0 ? fallback : value.trim();
    }
}
