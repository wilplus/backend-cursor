import unittest

from services import draft_delivery as dd


class DraftDeliveryLifecycleTests(unittest.TestCase):
    def test_infer_delivered_when_status_sent(self):
        self.assertEqual(dd.infer_delivery_lifecycle({"status": "sent"}), dd.DELIVERY_DELIVERED)

    def test_infer_delivering_when_pipeline_active(self):
        row = {"status": "pending", "pipeline_status": "queued"}
        self.assertEqual(dd.infer_delivery_lifecycle(row), dd.DELIVERY_DELIVERING)

    def test_infer_failed_when_pipeline_failed(self):
        row = {"status": "pending", "pipeline_status": "failed"}
        self.assertEqual(dd.infer_delivery_lifecycle(row), dd.DELIVERY_FAILED)

    def test_auto_approve_sets_state_sent(self):
        out = dd.auto_approve_payload_for_send({"email_draft": "x"})
        self.assertEqual(out.get("state"), "Sent")
        self.assertTrue(out.get("approved_at"))


if __name__ == "__main__":
    unittest.main()
