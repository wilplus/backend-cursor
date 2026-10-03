"""A dropped connection during the Take promotion is retried, not fatal.

THE BUG (the founder's Takes of 2026-10-02 and 2026-10-03, during the
database incident): the promotion RPC is the last call of a run. When the
transport dropped on that one call the wrapper returned None, the lifecycle
raised "successful recording was not promoted to a Take", and the job threw
the whole attempt away and re-ran transcription and the Ideal Text from the
start. The RPC is idempotent on (attempt, completion_hash), so the right
answer is the same reconnect-and-retry every read already gets.

Run: python3 -m unittest tests.test_take_promotion_survives_a_dropped_connection
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.db import DatabaseService

TAKE_ID = "3b7a2d4e-1c5f-4a6b-9d8e-0f1a2b3c4d5e"


class _Result:
    def __init__(self, data):
        self.data = data


class _Call:
    def __init__(self, client, name, params):
        self.client, self.name, self.params = client, name, params

    def execute(self):
        self.client.calls.append((self.name, self.params))
        if self.client.drops > 0:
            self.client.drops -= 1
            raise RuntimeError("RemoteProtocolError: Server disconnected")
        return _Result([{"take_id": TAKE_ID, "take_index": 1}])


class _Client:
    def __init__(self, drops=0):
        self.drops = drops
        self.calls = []

    def rpc(self, name, params):
        return _Call(self, name, params)


def _service(client):
    service = DatabaseService.__new__(DatabaseService)
    service.client = client
    return service


ARGS = dict(recording_attempt_id=TAKE_ID, completion_hash="c" * 64,
            processing_job_id="job-1", attempt_count=1, input_hash="i" * 64,
            output_hash="o" * 64, idempotency_key="attempt-promotion:x")


class PromotionRetryTests(unittest.TestCase):
    def test_a_dropped_connection_is_retried_and_the_take_returned(self):
        client = _Client(drops=1)
        service = _service(client)
        with patch.object(service, "_build_supabase_client", lambda: client), \
             patch("services.db.time.sleep", lambda _s: None), \
             patch("services.confident_moment_delivery_worker.arm_confident_moment_deliveries_for_take",
                   lambda *_a, **_k: None):
            row = service.promote_recording_attempt_to_take(**ARGS)
        self.assertEqual(row["take_id"], TAKE_ID)
        self.assertEqual([c[0] for c in client.calls],
                         ["promote_recording_attempt_to_take_v1"] * 2)

    def test_the_outbox_promotion_is_retried_the_same_way(self):
        client = _Client(drops=2)
        service = _service(client)
        with patch.object(service, "_build_supabase_client", lambda: client), \
             patch("services.db.time.sleep", lambda _s: None):
            row = service.promote_recording_attempt_with_confidence_outbox(
                **ARGS, source_manifest={"producer": "confidence-v3"})
        self.assertEqual(row["take_id"], TAKE_ID)
        self.assertEqual(len(client.calls), 3)

    def test_a_refusal_is_not_retried(self):
        class _Refusing(_Client):
            def rpc(self, name, params):
                self.calls.append((name, params))
                raise RuntimeError("confidence producer lacks current model-improvement consent")
        client = _Refusing()
        service = _service(client)
        with patch("services.db.time.sleep", lambda _s: None):
            row = service.promote_recording_attempt_with_confidence_outbox(
                **ARGS, source_manifest={"producer": "confidence-v3"})
        self.assertIsNone(row)
        self.assertEqual(len(client.calls), 1)


if __name__ == "__main__":
    unittest.main()
