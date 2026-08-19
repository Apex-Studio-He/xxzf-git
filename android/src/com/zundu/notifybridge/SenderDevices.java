package com.zundu.notifybridge;

import java.util.ArrayList;
import java.util.List;

final class SenderDevices {
    private SenderDevices() {}

    static List<SenderDevice> without(List<SenderDevice> devices, String senderId) {
        String target = senderId == null ? "" : senderId.trim();
        if (target.isEmpty()) throw new IllegalArgumentException("sender id is required");
        List<SenderDevice> result = new ArrayList<>();
        if (devices == null) return result;
        for (SenderDevice device : devices) {
            if (device != null && !target.equals(device.id)) result.add(device);
        }
        return result;
    }
}
