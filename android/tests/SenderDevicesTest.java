package com.zundu.notifybridge;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

public final class SenderDevicesTest {
    public static void main(String[] args) {
        SenderDevice first = new SenderDevice("sender-a", "设备 A", "android", "AAA");
        SenderDevice selected = new SenderDevice("sender-b", "设备 B", "ios", "BBB");
        SenderDevice third = new SenderDevice("sender-c", "设备 C", "android", "CCC");
        List<SenderDevice> original = new ArrayList<>(Arrays.asList(first, selected, third));

        List<SenderDevice> remaining = SenderDevices.without(original, "sender-b");

        require(remaining.size() == 2, "only one sender is removed");
        require(remaining.get(0) == first, "sender before target is preserved");
        require(remaining.get(1) == third, "sender after target is preserved");
        require(original.size() == 3, "input snapshot is not mutated");
        require(SenderDevices.without(original, "sender-missing").size() == 3,
                "unknown sender leaves snapshot unchanged");

        boolean rejected = false;
        try {
            SenderDevices.without(original, "  ");
        } catch (IllegalArgumentException expected) {
            rejected = true;
        }
        require(rejected, "blank sender id is rejected");
        System.out.println("SenderDevicesTest passed");
    }

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
