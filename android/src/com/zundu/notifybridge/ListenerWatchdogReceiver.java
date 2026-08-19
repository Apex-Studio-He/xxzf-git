package com.zundu.notifybridge;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public final class ListenerWatchdogReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        ListenerBinding.ensure(context);
        ListenerWatchdog.schedule(context);
    }
}
