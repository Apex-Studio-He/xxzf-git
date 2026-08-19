package com.zundu.notifybridge;

import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;

final class RecentNotificationCache {
    private final LinkedHashMap<String, Long> entries = new LinkedHashMap<>();
    private final int maximumEntries;

    RecentNotificationCache(int maximumEntries) {
        if (maximumEntries < 1) throw new IllegalArgumentException("maximumEntries");
        this.maximumEntries = maximumEntries;
    }

    synchronized boolean isDuplicate(String key, long now, long windowMillis) {
        Long previous = entries.put(key, now);
        trim(now, windowMillis);
        return previous != null && now >= previous && now - previous < windowMillis;
    }

    synchronized int size() {
        return entries.size();
    }

    private void trim(long now, long windowMillis) {
        Iterator<Map.Entry<String, Long>> iterator = entries.entrySet().iterator();
        while (iterator.hasNext()) {
            Map.Entry<String, Long> entry = iterator.next();
            long timestamp = entry.getValue();
            if (now >= timestamp && now - timestamp >= windowMillis) iterator.remove();
        }
        iterator = entries.entrySet().iterator();
        while (entries.size() > maximumEntries && iterator.hasNext()) {
            iterator.next();
            iterator.remove();
        }
    }
}
