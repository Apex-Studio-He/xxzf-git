package com.zundu.notifybridge;

public final class ComponentAccessTest {
    private static int checks;

    public static void main(String[] args) {
        equal(false, ComponentAccess.contains(null, "a/b"), "null list");
        equal(false, ComponentAccess.contains("a/b", ""), "empty expected");
        equal(true, ComponentAccess.contains("a/b:c/d", "c/d"), "exact component");
        equal(true, ComponentAccess.contains(" a/b : c/d ", "c/d"), "trim component");
        equal(false, ComponentAccess.contains("prefix.c/d.suffix", "c/d"), "substring rejected");
        equal(false, ComponentAccess.contains("x/c/d:y/z", "c/d"), "partial component rejected");
        System.out.println("ComponentAccessTest: " + checks + " checks passed");
    }

    private static void equal(boolean expected, boolean actual, String message) {
        checks++;
        if (expected != actual) throw new AssertionError(message);
    }
}
