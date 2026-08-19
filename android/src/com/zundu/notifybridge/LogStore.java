package com.zundu.notifybridge;

import android.content.Context;
import android.content.SharedPreferences;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

final class LogStore {
    private static final String KEY_LOGS = "logs";
    private static final int MAX_LINES = 28;

    private LogStore() {}

    static void add(Context context, String line) {
        SharedPreferences prefs = Prefs.get(context);
        String current = prefs.getString(KEY_LOGS, "");
        String stamp = new SimpleDateFormat("HH:mm:ss", Locale.CHINA).format(new Date());
        String combined = stamp + "  " + line + "\n" + current;
        String[] lines = combined.split("\n");
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < lines.length && i < MAX_LINES; i++) {
            if (lines[i].trim().length() > 0) {
                out.append(lines[i]).append('\n');
            }
        }
        prefs.edit().putString(KEY_LOGS, out.toString()).apply();
    }

    static String all(Context context) {
        return Prefs.get(context).getString(KEY_LOGS, "");
    }

    static void clear(Context context) {
        Prefs.get(context).edit().remove(KEY_LOGS).apply();
    }
}
