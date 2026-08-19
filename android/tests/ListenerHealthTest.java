package com.zundu.notifybridge;

public final class ListenerHealthTest {
    private static int checks;

    public static void main(String[] args) {
        equal(ListenerHealth.DISABLED,
                ListenerHealth.state(false, false, false),
                "disabled access");
        equal(ListenerHealth.READY,
                ListenerHealth.state(true, true, false),
                "a running listener service is healthy even if the callback flag was lost");
        equal(ListenerHealth.READY,
                ListenerHealth.state(true, false, true),
                "a connected callback is healthy");
        equal(ListenerHealth.WAITING,
                ListenerHealth.state(true, false, false),
                "enabled access without a running service is waiting");
        equal(false,
                ListenerHealth.shouldRecoverDisconnected(true, true),
                "a delayed recovery must not disrupt a listener that already reconnected");
        equal(false,
                ListenerHealth.shouldRecoverDisconnected(false, false),
                "recovery must stop when notification access was revoked");
        equal(true,
                ListenerHealth.shouldRecoverDisconnected(true, false),
                "an enabled listener that is still disconnected needs recovery");
        equal(false,
                ListenerHealth.shouldRequestRebind(true, false),
                "a running listener service does not need another delayed rebind");
        equal(false,
                ListenerHealth.shouldRequestRebind(false, true),
                "a connected listener does not need another delayed rebind");
        equal(true,
                ListenerHealth.shouldRequestRebind(false, false),
                "a listener that is neither running nor connected needs rebind");
        System.out.println("ListenerHealthTest: " + checks + " checks passed");
    }

    private static void equal(int expected, int actual, String message) {
        checks++;
        if (expected != actual) throw new AssertionError(
                message + ": expected=" + expected + " actual=" + actual);
    }

    private static void equal(boolean expected, boolean actual, String message) {
        checks++;
        if (expected != actual) throw new AssertionError(
                message + ": expected=" + expected + " actual=" + actual);
    }
}
