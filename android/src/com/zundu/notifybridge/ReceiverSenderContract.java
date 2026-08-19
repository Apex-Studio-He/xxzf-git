package com.zundu.notifybridge;

final class ReceiverSenderContract {
    private static final String LIST_PATH = "/pair/status";
    private static final String REVOKE_PATH = "/v1/receiver/senders/revoke";

    private ReceiverSenderContract() {}

    static String listPath() {
        return LIST_PATH;
    }

    static String revokePath() {
        return REVOKE_PATH;
    }

    static String requireSenderId(String value) {
        String senderId = value == null ? "" : value.trim();
        if (senderId.isEmpty()) throw new IllegalArgumentException("sender id is required");
        return senderId;
    }
}
