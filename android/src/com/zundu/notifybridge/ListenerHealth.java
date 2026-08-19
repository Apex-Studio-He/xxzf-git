package com.zundu.notifybridge;

final class ListenerHealth {
    static final int DISABLED = 0;
    static final int WAITING = 1;
    static final int READY = 2;

    private ListenerHealth() {}

    static int state(boolean accessEnabled, boolean serviceRunning, boolean callbackConnected) {
        if (!accessEnabled) return DISABLED;
        return serviceRunning || callbackConnected ? READY : WAITING;
    }

    static boolean shouldRecoverDisconnected(boolean accessEnabled, boolean callbackConnected) {
        return accessEnabled && !callbackConnected;
    }

    static boolean shouldRequestRebind(boolean serviceRunning, boolean callbackConnected) {
        return !serviceRunning && !callbackConnected;
    }
}
