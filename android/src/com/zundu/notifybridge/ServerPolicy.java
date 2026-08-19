package com.zundu.notifybridge;

final class ServerPolicy {
    private static final String OFFICIAL_BASE =
            "https://example.com/xxzf";

    private ServerPolicy() {}

    static String officialBase() {
        return OFFICIAL_BASE;
    }

    static String officialNotifyUrl() {
        return OFFICIAL_BASE + "/v1/notify";
    }

    static String requireOfficialBase(String value) {
        String candidate = value == null ? "" : value;
        if (!OFFICIAL_BASE.equals(candidate)) {
            throw new IllegalArgumentException("仅支持尊嘟官方 HTTPS 服务");
        }
        return OFFICIAL_BASE;
    }
}
