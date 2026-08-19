package com.zundu.notifybridge;

public final class RecentNotificationCacheTest {
    private static int checks;

    public static void main(String[] args) {
        RecentNotificationCache cache = new RecentNotificationCache(3);
        equal(false, cache.isDuplicate("one", 1000, 2500), "first event");
        equal(true, cache.isDuplicate("one", 1200, 2500), "recent duplicate");
        equal(false, cache.isDuplicate("one", 4000, 2500), "expired duplicate");
        cache.isDuplicate("two", 4100, 2500);
        cache.isDuplicate("three", 4200, 2500);
        cache.isDuplicate("four", 4300, 2500);
        equal(3, cache.size(), "bounded cache");
        equal(false, cache.isDuplicate("clock", 5000, 2500), "clock seed");
        equal(false, cache.isDuplicate("clock", 100, 2500), "backward clock is not duplicate");
        System.out.println("RecentNotificationCacheTest: " + checks + " checks passed");
    }

    private static void equal(boolean expected, boolean actual, String message) {
        checks++;
        if (expected != actual) throw new AssertionError(message);
    }

    private static void equal(int expected, int actual, String message) {
        checks++;
        if (expected != actual) throw new AssertionError(message + ": " + actual);
    }
}
