package com.zundu.notifybridge;

final class BarkDestination {
    final String id;
    final String name;
    final String fingerprint;
    final long lastSuccessAt;
    final long lastFailureAt;

    private BarkDestination(
            String id, String name, String fingerprint,
            long lastSuccessAt, long lastFailureAt) {
        this.id = id;
        this.name = name;
        this.fingerprint = fingerprint;
        this.lastSuccessAt = Math.max(0, lastSuccessAt);
        this.lastFailureAt = Math.max(0, lastFailureAt);
    }

    static BarkDestination fromFields(
            String type, String id, String name, String fingerprint,
            long lastSuccessAt, long lastFailureAt) {
        if (!"bark".equals(type)) return null;
        String safeId = normalizeId(id);
        if (safeId.isEmpty()) return null;
        return new BarkDestination(
                safeId,
                normalizeLabel(name, "iPhone"),
                normalizeLabel(fingerprint, ""),
                lastSuccessAt,
                lastFailureAt);
    }

    String deliveryState() {
        if (lastFailureAt > lastSuccessAt) return "上次发送失败，请发送测试确认";
        if (lastSuccessAt > 0) return "已连接 · 最近发送成功";
        return "已连接 · 尚未发送通知";
    }

    private static String normalizeId(String value) {
        String candidate = value == null ? "" : value.trim();
        if (candidate.length() < 1 || candidate.length() > 128) return "";
        for (int index = 0; index < candidate.length(); index++) {
            char character = candidate.charAt(index);
            boolean allowed = character >= 'a' && character <= 'z'
                    || character >= 'A' && character <= 'Z'
                    || character >= '0' && character <= '9'
                    || character == '_' || character == '-';
            if (!allowed) return "";
        }
        return candidate;
    }

    private static String normalizeLabel(String value, String fallback) {
        String candidate = value == null ? "" : value.trim();
        StringBuilder safe = new StringBuilder();
        for (int index = 0; index < candidate.length() && safe.length() < 48; index++) {
            char character = candidate.charAt(index);
            if (!Character.isISOControl(character)) safe.append(character);
        }
        String normalized = safe.toString().trim();
        return normalized.isEmpty() ? fallback : normalized;
    }
}
