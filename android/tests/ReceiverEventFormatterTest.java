package com.zundu.notifybridge;

public final class ReceiverEventFormatterTest {
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    public static void main(String[] args) {
        ReceiverEventFormatter.Display full = ReceiverEventFormatter.format(
                "微信", "何昊", "何昊：你好", "full", "full");
        require("转发：微信".equals(full.title), "source title");
        require("何昊\n你好".equals(full.body), "duplicate sender cleanup");

        ReceiverEventFormatter.Display title = ReceiverEventFormatter.format(
                "QQ", "群消息", "正文", "full", "title");
        require("群消息".equals(title.body), "receiver title ceiling");

        ReceiverEventFormatter.Display source = ReceiverEventFormatter.format(
                "邮件", "主题", "正文", "source", "full");
        require(source.body.isEmpty(), "sender source ceiling");
    }
}
