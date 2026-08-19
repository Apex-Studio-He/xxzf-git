package com.zundu.notifybridge;

public final class ReceiverSenderContractTest {
    public static void main(String[] args) {
        require("/pair/status".equals(ReceiverSenderContract.listPath()),
                "sender list uses receiver-authenticated status endpoint");
        require("/v1/receiver/senders/revoke".equals(ReceiverSenderContract.revokePath()),
                "single revoke uses receiver-scoped endpoint");
        require("sender-one".equals(ReceiverSenderContract.requireSenderId(" sender-one ")),
                "sender id is normalized without changing identity");

        boolean rejected = false;
        try {
            ReceiverSenderContract.requireSenderId("\n\t");
        } catch (IllegalArgumentException expected) {
            rejected = true;
        }
        require(rejected, "blank sender id is rejected before any request");
        System.out.println("ReceiverSenderContractTest passed");
    }

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
