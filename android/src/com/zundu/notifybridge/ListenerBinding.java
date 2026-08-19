package com.zundu.notifybridge;

import android.content.ComponentName;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.provider.Settings;
import android.service.notification.NotificationListenerService;
import android.text.TextUtils;
import android.util.Log;

final class ListenerBinding {
    private static final String TAG = "XXZFBinding";
    private static final String PREFS = "listener_binding";
    private static final String KEY_VERSION = "last_version";
    private static final long COMPONENT_REFRESH_COOLDOWN_MS = 10000;
    private static volatile boolean connected;
    private static volatile boolean componentRefreshPending;
    private static volatile long lastComponentRefreshAt;

    private ListenerBinding() {}

    static boolean isAccessEnabled(Context context) {
        String flat = Settings.Secure.getString(
                context.getContentResolver(), "enabled_notification_listeners");
        if (TextUtils.isEmpty(flat)) return false;
        ComponentName component = new ComponentName(context, NotifyBridgeService.class);
        return ComponentAccess.contains(flat, component.flattenToString());
    }

    static boolean isConnected() {
        return connected;
    }

    static void markConnected(boolean value) {
        connected = value;
    }

    static void ensure(Context context) {
        if (!isAccessEnabled(context)) return;
        final Context application = context.getApplicationContext();
        int version = currentVersion(context);
        SharedPreferences preferences = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        int previous = preferences.getInt(KEY_VERSION, -1);
        preferences.edit().putInt(KEY_VERSION, version).apply();
        if (previous != version) {
            repairAfterUpdate(application);
        } else if (!connected && !NotifyBridgeService.isRunning()) {
            request(application, 0);
        }
    }

    static void repairAfterUpdate(Context context) {
        if (!isAccessEnabled(context)) return;
        final Context application = context.getApplicationContext();
        if (!ListenerHealth.shouldRequestRebind(
                NotifyBridgeService.isRunning(), connected)) return;
        request(application, 0);
        request(application, 400);
        request(application, 2500);
        DiagnosticLog.add(application, "info", "LISTENER_REBIND_REQUESTED");
    }

    static void recoverDisconnected(Context context) {
        if (!ListenerHealth.shouldRecoverDisconnected(isAccessEnabled(context), connected)) return;
        connected = false;
        refreshComponent(context);
    }

    static void forceRepair(Context context) {
        if (!isAccessEnabled(context)) return;
        final Context application = context.getApplicationContext();
        connected = false;
        refreshComponent(application);
        DiagnosticLog.add(application, "info", "LISTENER_MANUAL_REBIND_REQUESTED");
    }

    private static void refreshComponent(Context context) {
        if (!isAccessEnabled(context)) return;
        long now = SystemClock.elapsedRealtime();
        if (componentRefreshPending || now - lastComponentRefreshAt < COMPONENT_REFRESH_COOLDOWN_MS) {
            request(context, 100);
            return;
        }

        final Context application = context.getApplicationContext();
        final ComponentName component = new ComponentName(application, NotifyBridgeService.class);
        final PackageManager manager = application.getPackageManager();
        componentRefreshPending = true;
        lastComponentRefreshAt = now;
        boolean disabled = false;
        try {
            manager.setComponentEnabledSetting(
                    component,
                    PackageManager.COMPONENT_ENABLED_STATE_DISABLED,
                    PackageManager.DONT_KILL_APP);
            disabled = true;
            DiagnosticLog.add(application, "info", "LISTENER_COMPONENT_REFRESH_STARTED");
        } catch (RuntimeException exception) {
            Log.w(TAG, "notification listener component disable failed", exception);
            DiagnosticLog.add(application, "warning", "LISTENER_COMPONENT_REFRESH_FAILED");
        } finally {
            boolean restored = restoreComponentEnabled(manager, component);
            componentRefreshPending = false;
            if (disabled && restored) {
                DiagnosticLog.add(application, "info", "LISTENER_COMPONENT_REFRESHED");
            } else if (!restored) {
                DiagnosticLog.add(application, "warning", "LISTENER_COMPONENT_REFRESH_FAILED");
            }
        }

        request(application, 0);
        request(application, 400);
        request(application, 2500);
    }

    private static boolean restoreComponentEnabled(
            PackageManager manager, ComponentName component) {
        try {
            manager.setComponentEnabledSetting(
                    component,
                    PackageManager.COMPONENT_ENABLED_STATE_ENABLED,
                    PackageManager.DONT_KILL_APP);
            return true;
        } catch (RuntimeException exception) {
            Log.w(TAG, "notification listener component enable failed", exception);
        }
        try {
            manager.setComponentEnabledSetting(
                    component,
                    PackageManager.COMPONENT_ENABLED_STATE_DEFAULT,
                    PackageManager.DONT_KILL_APP);
            return true;
        } catch (RuntimeException exception) {
            Log.w(TAG, "notification listener component default restore failed", exception);
            return false;
        }
    }

    private static void request(final Context context, long delayMs) {
        final ComponentName component = new ComponentName(context, NotifyBridgeService.class);
        if (delayMs <= 0) {
            requestNow(context, component);
            return;
        }
        new Handler(Looper.getMainLooper()).postDelayed(new Runnable() {
            @Override public void run() {
                if (ListenerHealth.shouldRequestRebind(
                        NotifyBridgeService.isRunning(), connected)) {
                    requestNow(context, component);
                }
            }
        }, delayMs);
    }

    private static void requestNow(Context context, ComponentName component) {
        try {
            NotificationListenerService.requestRebind(component);
            Log.i(TAG, "requested notification listener rebind");
        } catch (RuntimeException exception) {
            Log.w(TAG, "notification listener rebind failed", exception);
            DiagnosticLog.add(context, "warning", "LISTENER_REBIND_FAILED");
        }
    }

    private static int currentVersion(Context context) {
        try {
            return context.getPackageManager().getPackageInfo(context.getPackageName(), 0).versionCode;
        } catch (Exception ignored) {
            return 0;
        }
    }
}
