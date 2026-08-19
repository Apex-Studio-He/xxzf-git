package com.zundu.notifybridge;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.SystemClock;

final class UpdateRecovery {
    static final String EXTRA_VERSION_CODE =
            "com.zundu.notifybridge.UPDATE_RECOVERY_VERSION_CODE";

    private static final long[] RETRY_DELAYS_MS = {
            45_000L,
            2L * 60L * 1000L,
            5L * 60L * 1000L
    };
    private static final int REQUEST_CODE_BASE = 9710;

    private UpdateRecovery() {}

    static void schedule(Context context, long versionCode) {
        AlarmManager manager = (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
        if (manager == null) {
            DiagnosticLog.add(context, "warning", "UPDATE_RECOVERY_SCHEDULE_FAILED");
            return;
        }
        for (int index = 0; index < RETRY_DELAYS_MS.length; index++) {
            scheduleAlarm(manager, context, versionCode, index, RETRY_DELAYS_MS[index]);
        }
        DiagnosticLog.add(context, "info", "UPDATE_RECOVERY_SCHEDULED");
    }

    private static void scheduleAlarm(AlarmManager manager, Context context, long versionCode,
                                      int index, long delayMs) {
        Intent intent = new Intent(context, UpdateRecoveryReceiver.class)
                .setPackage(context.getPackageName())
                .putExtra(EXTRA_VERSION_CODE, versionCode);
        PendingIntent pending = PendingIntent.getBroadcast(
                context,
                REQUEST_CODE_BASE + index,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        manager.setAndAllowWhileIdle(
                AlarmManager.ELAPSED_REALTIME_WAKEUP,
                SystemClock.elapsedRealtime() + delayMs,
                pending);
    }
}
