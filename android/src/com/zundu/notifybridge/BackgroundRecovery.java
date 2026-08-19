package com.zundu.notifybridge;

import android.content.Context;

final class BackgroundRecovery {
    private BackgroundRecovery() {}

    static void restore(Context context) {
        ListenerBinding.ensure(context);
        ListenerWatchdog.schedule(context);
        restoreServices(context);
    }

    static void restoreAfterUpdate(Context context) {
        UpdateManager.clearPendingUpdate(context);
        ListenerBinding.repairAfterUpdate(context);
        ListenerWatchdog.schedule(context);
        restoreServices(context);
    }

    private static void restoreServices(Context context) {
        if (Prefs.receiveEnabled(context) && Prefs.localReceiverReady(context)) {
            try {
                ReceiverBridgeService.start(context);
            } catch (RuntimeException exception) {
                DiagnosticLog.add(context, "warning", "RECEIVER_SERVICE_RESTORE_FAILED");
            }
        }
    }
}
