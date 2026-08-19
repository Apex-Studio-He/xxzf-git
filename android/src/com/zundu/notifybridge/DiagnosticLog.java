package com.zundu.notifybridge;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

final class DiagnosticLog {
    private static final String KEY = "diagnostic_events";
    private static final int MAX_ENTRIES = 80;

    private DiagnosticLog() {}

    static synchronized void add(Context context, String level, String code) {
        add(context, level, code, 0);
    }

    static synchronized void add(Context context, String level, String code, int httpStatus) {
        try {
            JSONArray current = new JSONArray(Prefs.get(context).getString(KEY, "[]"));
            JSONArray next = new JSONArray();
            JSONObject entry = new JSONObject();
            entry.put("at", System.currentTimeMillis());
            entry.put("level", normalizeLevel(level));
            entry.put("code", normalizeCode(code));
            if (httpStatus > 0) entry.put("httpStatus", Math.min(httpStatus, 999));
            next.put(entry);
            for (int index = 0; index < current.length() && next.length() < MAX_ENTRIES; index++) {
                JSONObject value = current.optJSONObject(index);
                if (value != null) next.put(value);
            }
            Prefs.get(context).edit().putString(KEY, next.toString()).apply();
        } catch (Exception ignored) {
        }
    }

    static synchronized JSONArray entries(Context context) {
        try {
            return new JSONArray(Prefs.get(context).getString(KEY, "[]"));
        } catch (Exception ignored) {
            return new JSONArray();
        }
    }

    private static String normalizeLevel(String value) {
        if ("warning".equals(value) || "error".equals(value)) return value;
        return "info";
    }

    private static String normalizeCode(String value) {
        String normalized = String.valueOf(value == null ? "UNKNOWN" : value)
                .toUpperCase().replaceAll("[^A-Z0-9_.:-]", "_");
        return normalized.substring(0, Math.min(normalized.length(), 48));
    }
}
