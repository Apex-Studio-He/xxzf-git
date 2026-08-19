package com.zundu.notifybridge;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public final class UpdateRecoveryReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        long expectedVersion = intent == null
                ? 0L : intent.getLongExtra(UpdateRecovery.EXTRA_VERSION_CODE, 0L);
        if (expectedVersion > 0L && UpdateManager.currentVersionCode(context) >= expectedVersion) {
            BackgroundRecovery.restoreAfterUpdate(context);
            DiagnosticLog.add(context, "info", "UPDATE_RECOVERY_COMPLETED");
        } else {
            BackgroundRecovery.restore(context);
            DiagnosticLog.add(context, "info", "UPDATE_RECOVERY_RETRY_WAITING");
        }
    }
}
