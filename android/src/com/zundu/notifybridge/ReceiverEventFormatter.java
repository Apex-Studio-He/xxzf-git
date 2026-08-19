package com.zundu.notifybridge;

final class ReceiverEventFormatter {
    static final class Display {
        final String title;
        final String body;

        Display(String title, String body) {
            this.title = title;
            this.body = body;
        }
    }

    private ReceiverEventFormatter() {}

    static Display format(
            String appName, String sourceTitle, String sourceText,
            String senderMode, String receiverMode) {
        String app = clean(appName, 80);
        if (app.isEmpty()) app = "未知应用";
        String title = clean(sourceTitle, 160);
        String text = cleanRepeatedTitle(title, clean(sourceText, 500));
        String privacy = rank(senderMode) <= rank(receiverMode) ? normalize(senderMode)
                : normalize(receiverMode);
        String body = "source".equals(privacy) ? ""
                : "title".equals(privacy) ? title
                : join(title, text);
        return new Display("转发：" + app, body);
    }

    private static String normalize(String value) {
        return "source".equals(value) || "title".equals(value) ? value : "full";
    }

    private static int rank(String value) {
        return "source".equals(value) ? 0 : "title".equals(value) ? 1 : 2;
    }

    private static String clean(String value, int limit) {
        if (value == null) return "";
        String result = value.replace('\r', ' ').replace('\n', ' ').trim();
        return result.length() <= limit ? result : result.substring(0, limit);
    }

    private static String cleanRepeatedTitle(String title, String text) {
        if (title.isEmpty() || text.isEmpty()) return text;
        if (text.equals(title)) return "";
        String plain = title + ":";
        String full = title + "：";
        if (text.startsWith(plain)) return text.substring(plain.length()).trim();
        if (text.startsWith(full)) return text.substring(full.length()).trim();
        return text;
    }

    private static String join(String title, String text) {
        if (title.isEmpty()) return text;
        if (text.isEmpty()) return title;
        return title + "\n" + text;
    }
}
