#!/usr/bin/env python3
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReceiverSenderClientPolicyTests(unittest.TestCase):
    def test_client_lists_and_revokes_with_receiver_scoped_contract(self):
        source = (ROOT / "src/com/zundu/notifybridge/ReceiverClient.java").read_text(
            encoding="utf-8"
        )
        self.assertIn("interface SendersCallback", source)
        self.assertRegex(source, r"static void senders\s*\(")
        self.assertIn("ReceiverSenderContract.listPath()", source)
        self.assertIn('response.optJSONArray("senders")', source)
        self.assertRegex(source, r"static void revokeSender\s*\(")
        self.assertIn("ReceiverSenderContract.revokePath()", source)
        self.assertIn(
            'payload.put("senderId", ReceiverSenderContract.requireSenderId(senderId))',
            source,
        )

    def test_single_revoke_client_does_not_clear_any_local_identity(self):
        source = (ROOT / "src/com/zundu/notifybridge/ReceiverClient.java").read_text(
            encoding="utf-8"
        )
        method = re.search(
            r"static void revokeSender\s*\([\s\S]*?\n    \}", source
        )
        self.assertIsNotNone(method)
        body = method.group(0)
        self.assertNotIn("clearPairing", body)
        self.assertNotIn("clearLocalReceiver", body)
        self.assertNotIn("selfRevoke", body)


class ReceiverSenderUiPolicyTests(unittest.TestCase):
    def test_receiver_page_renders_sender_management_and_per_item_delete(self):
        source = (ROOT / "src/com/zundu/notifybridge/ReceiverPairActivity.java").read_text(
            encoding="utf-8"
        )
        self.assertIn('Ui.title(this, "管理发送设备", 17)', source)
        self.assertIn("ReceiverClient.senders(", source)
        self.assertIn("sendersList", source)
        self.assertIn('Ui.button(this, "删除", false)', source)
        self.assertIn("confirmRemoveSender(device)", source)

    def test_confirmation_names_target_and_never_invokes_delete_all_paths(self):
        source = (ROOT / "src/com/zundu/notifybridge/ReceiverPairActivity.java").read_text(
            encoding="utf-8"
        )
        method = re.search(
            r"private void confirmRemoveSender\s*\([\s\S]*?\n    \}", source
        )
        self.assertIsNotNone(method)
        body = method.group(0)
        self.assertIn('setTitle("删除发送设备？")', body)
        self.assertIn("device.displayName()", body)
        self.assertIn('setPositiveButton("删除此设备"', body)
        self.assertIn("ReceiverClient.revokeSender(", body)
        self.assertRegex(
            body, r"SenderDevices\.without\(\s*senders,\s*device\.id\)"
        )
        self.assertNotIn("clearPairing", body)
        self.assertNotIn("clearLocalReceiver", body)
        self.assertNotIn("selfRevoke", body)


if __name__ == "__main__":
    unittest.main()
