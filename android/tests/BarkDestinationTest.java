package com.zundu.notifybridge;

public final class BarkDestinationTest {
    public static void main(String[] args) {
        BarkDestination connected = BarkDestination.fromFields(
                "bark", " b_iphone ", "  我的 iPhone  ", "ABC123", 20, 10);
        require(connected != null, "Bark destination is accepted");
        require("b_iphone".equals(connected.id), "destination id is normalized");
        require("我的 iPhone".equals(connected.name), "name is normalized");
        require(connected.deliveryState().contains("最近发送成功"),
                "latest successful delivery is visible");

        BarkDestination failed = BarkDestination.fromFields(
                "bark", "b_failed", "", "", 10, 30);
        require(failed != null && "iPhone".equals(failed.name),
                "blank name uses safe fallback");
        require(failed.deliveryState().contains("发送测试确认"),
                "latest delivery failure asks for an explicit test");

        require(BarkDestination.fromFields(
                "desktop", "device_one", "Mac", "", 0, 0) == null,
                "non-Bark receivers never appear on the Bark page");
        require(BarkDestination.fromFields(
                "bark", "bad/id", "iPhone", "", 0, 0) == null,
                "unsafe destination ids are rejected before actions");
    }

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
