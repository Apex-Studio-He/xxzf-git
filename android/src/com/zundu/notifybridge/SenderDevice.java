package com.zundu.notifybridge;

final class SenderDevice {
    final String id;
    final String name;
    final String platform;
    final String fingerprint;

    SenderDevice(String id, String name, String platform, String fingerprint) {
        this.id = clean(id);
        this.name = clean(name);
        this.platform = clean(platform);
        this.fingerprint = clean(fingerprint);
        if (this.id.isEmpty()) throw new IllegalArgumentException("sender id is required");
    }

    String displayName() {
        return name.isEmpty() ? "未命名发送设备" : name;
    }

    private static String clean(String value) {
        return value == null ? "" : value.trim();
    }
}
