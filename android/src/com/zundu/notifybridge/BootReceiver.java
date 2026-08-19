package com.zundu.notifybridge;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent == null ? "" : intent.getAction();
        if (Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)) {
            BackgroundRecovery.restoreAfterUpdate(context);
        } else {
            BackgroundRecovery.restore(context);
        }
    }
}
