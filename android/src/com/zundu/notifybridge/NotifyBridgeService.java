package com.zundu.notifybridge;

import android.app.Notification;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;
import android.text.TextUtils;
import android.util.Log;

import org.json.JSONObject;

import java.util.Locale;

public class NotifyBridgeService extends NotificationListenerService {
    private static final String TAG = "XXZFListener";
    private static volatile boolean running;
    private final RecentNotificationCache recent = new RecentNotificationCache(256);
    private final Handler updateHandler = new Handler(Looper.getMainLooper());
    private final Runnable updateCheck = new Runnable() {
        @Override public void run() {
            UpdateManager.checkInBackground(NotifyBridgeService.this);
            updateHandler.postDelayed(this, UpdateManager.CHECK_INTERVAL_MS);
        }
    };

    @Override
    public void onCreate() {
        super.onCreate();
        running = true;
        updateHandler.post(updateCheck);
    }

    @Override
    public void onDestroy() {
        updateHandler.removeCallbacks(updateCheck);
        running = false;
        ListenerBinding.markConnected(false);
        super.onDestroy();
    }

    static boolean isRunning() {
        return running;
    }

    @Override
    public void onListenerConnected() {
        super.onListenerConnected();
        ListenerBinding.markConnected(true);
        Log.i(TAG, "listener connected");
        LogStore.add(this, "通知监听已连接");
        DiagnosticLog.add(this, "info", "LISTENER_CONNECTED");
    }

    @Override
    public void onListenerDisconnected() {
        super.onListenerDisconnected();
        ListenerBinding.markConnected(false);
        Log.w(TAG, "listener disconnected; requesting rebind");
        DiagnosticLog.add(this, "warning", "LISTENER_DISCONNECTED");
        new Handler(Looper.getMainLooper()).postDelayed(new Runnable() {
            @Override
            public void run() {
                ListenerBinding.recoverDisconnected(NotifyBridgeService.this);
            }
        }, 1000);
    }

    @Override
    public void onNotificationPosted(StatusBarNotification sbn) {
        if (sbn == null || !Prefs.enabled(this)) return;
        ListenerBinding.markConnected(true);

        try {
            Notification n = sbn.getNotification();
            if (n == null) return;
            Bundle extras = n.extras;
            if (extras == null) return;
            if (extras.getBoolean(ReceiverBridgeService.EXTRA_RECEIVER_DELIVERY, false)) return;
            String pkg = safe(sbn.getPackageName());
            String title = safe(extras.getCharSequence(Notification.EXTRA_TITLE));
            String text = firstNonEmpty(
                    safe(extras.getCharSequence(Notification.EXTRA_TEXT)),
                    safe(extras.getCharSequence(Notification.EXTRA_BIG_TEXT)),
                    safe(extras.getCharSequence(Notification.EXTRA_SUMMARY_TEXT))
            );

            if (TextUtils.isEmpty(title) && TextUtils.isEmpty(text)) return;
            if (!packageAllowed(pkg)) return;
            if (!keywordAllowed(title + "\n" + text)) return;
            if (isDuplicate(pkg, title, text)) return;
            Log.i(TAG, "notification accepted pkg=" + pkg);

            String appName = appName(pkg);
            String privacy = Prefs.privacy(this);
            String outTitle = title;
            String outText = text;
            if ("title".equals(privacy)) {
                outText = "";
            } else if ("source".equals(privacy)) {
                outTitle = "";
                outText = "";
            }

            JSONObject payload = new JSONObject();
            payload.put("id", sbn.getKey());
            payload.put("packageName", pkg);
            payload.put("appName", appName);
            payload.put("title", outTitle);
            payload.put("text", outText);
            payload.put("postTime", sbn.getPostTime());
            payload.put("privacyMode", privacy);

            final String logName = appName;
            BridgeSender.send(this, payload, new BridgeSender.Callback() {
                @Override
                public void done(boolean ok, String message) {
                    LogStore.add(NotifyBridgeService.this, (ok ? "已转发 " : "转发失败 ") + logName + " · " + message);
                }
            });
        } catch (Exception e) {
            Log.e(TAG, "listener error", e);
            LogStore.add(this, "监听异常 " + e.getClass().getSimpleName() + ": " + e.getMessage());
        }
    }

    private boolean packageAllowed(String pkg) {
        if (Prefs.filterAll(this)) return true;
        String raw = Prefs.packages(this).trim();
        if (raw.length() == 0) return false;
        String[] parts = raw.split("[,，\\s]+");
        for (String p : parts) {
            if (p.trim().length() == 0) continue;
            if (pkg.equals(p.trim())) return true;
        }
        return false;
    }

    private boolean keywordAllowed(String content) {
        String raw = Prefs.keywords(this).trim().toLowerCase(Locale.ROOT);
        if (raw.length() == 0) return true;
        String lower = content.toLowerCase(Locale.ROOT);
        String[] parts = raw.split("[,，\\s]+");
        for (String p : parts) {
            if (p.trim().length() == 0) continue;
            if (lower.contains(p.trim().toLowerCase(Locale.ROOT))) return true;
        }
        return false;
    }

    private boolean isDuplicate(String pkg, String title, String text) {
        long now = SystemClock.elapsedRealtime();
        String key = pkg + "|" + title + "|" + text;
        return recent.isDuplicate(key, now, 2500);
    }

    private String appName(String pkg) {
        try {
            PackageManager pm = getPackageManager();
            ApplicationInfo info = pm.getApplicationInfo(pkg, 0);
            CharSequence label = pm.getApplicationLabel(info);
            return label == null ? pkg : label.toString();
        } catch (Exception e) {
            return pkg;
        }
    }

    private static String safe(CharSequence value) {
        return value == null ? "" : value.toString();
    }

    private static String firstNonEmpty(String a, String b, String c) {
        if (!TextUtils.isEmpty(a)) return a;
        if (!TextUtils.isEmpty(b)) return b;
        if (!TextUtils.isEmpty(c)) return c;
        return "";
    }
}
