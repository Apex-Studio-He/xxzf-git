package com.zundu.notifybridge;

import android.app.Notification;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.graphics.drawable.Drawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;
import android.text.TextUtils;
import android.util.Base64;
import android.util.Log;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;

public class NotifyBridgeService extends NotificationListenerService {
    private static final String TAG = "XXZFListener";
    private static final int BARK_ICON_SIZE_PX = 64;
    private static final int BARK_ICON_MAX_BYTES = 32 * 1024;
    private static final long HEARTBEAT_INTERVAL_MS = 60 * 1000L;
    private static volatile boolean running;
    private final RecentNotificationCache recent = new RecentNotificationCache(256);
    private final Map<String, String> appIconCache = new LinkedHashMap<>();
    private final Handler updateHandler = new Handler(Looper.getMainLooper());
    private final Runnable updateCheck = new Runnable() {
        @Override public void run() {
            UpdateManager.checkInBackground(NotifyBridgeService.this);
            updateHandler.postDelayed(this, UpdateManager.CHECK_INTERVAL_MS);
        }
    };
    private final Runnable heartbeat = new Runnable() {
        @Override public void run() {
            ServerClient.check(NotifyBridgeService.this, new ServerClient.StatusCallback() {
                @Override public void done(String status) {
                    // Authentication itself refreshes the server-side last-seen time.
                }
            });
            updateHandler.postDelayed(this, HEARTBEAT_INTERVAL_MS);
        }
    };

    @Override
    public void onCreate() {
        super.onCreate();
        running = true;
        updateHandler.post(updateCheck);
        updateHandler.post(heartbeat);
    }

    @Override
    public void onDestroy() {
        updateHandler.removeCallbacks(updateCheck);
        updateHandler.removeCallbacks(heartbeat);
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
            String appIconPng = appIconPng(pkg);
            if (!TextUtils.isEmpty(appIconPng)) payload.put("appIconPng", appIconPng);

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

    private String appIconPng(String pkg) {
        synchronized (appIconCache) {
            if (appIconCache.containsKey(pkg)) return appIconCache.get(pkg);
        }
        String encoded = "";
        Bitmap bitmap = null;
        try {
            Drawable icon = getPackageManager().getApplicationIcon(pkg).mutate();
            bitmap = Bitmap.createBitmap(
                    BARK_ICON_SIZE_PX, BARK_ICON_SIZE_PX, Bitmap.Config.ARGB_8888);
            Canvas canvas = new Canvas(bitmap);
            icon.setBounds(0, 0, BARK_ICON_SIZE_PX, BARK_ICON_SIZE_PX);
            icon.draw(canvas);
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            if (bitmap.compress(Bitmap.CompressFormat.PNG, 100, output)) {
                byte[] bytes = output.toByteArray();
                if (bytes.length <= BARK_ICON_MAX_BYTES) {
                    encoded = Base64.encodeToString(bytes, Base64.NO_WRAP);
                }
            }
        } catch (Exception ignored) {
            encoded = "";
        } finally {
            if (bitmap != null) bitmap.recycle();
        }
        synchronized (appIconCache) {
            if (appIconCache.size() >= 64) {
                String first = appIconCache.keySet().iterator().next();
                appIconCache.remove(first);
            }
            appIconCache.put(pkg, encoded);
        }
        return encoded;
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
