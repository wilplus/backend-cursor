"""
STORY    As a speaker, I want a dropped database connection at the last step
         to be retried, so that my Take is not thrown away and processed
         again.
OUTCOME
  O1  When the connection drops while the recording becomes a Take, the
      step is retried once and the Take is returned.
PROVES   O1 -> PromotionRetryTests::test_a_dropped_connection_is_retried_and_the_take_returned
WHY      Founder's Takes of 2026-10-02 and 2026-10-03 were re-run from the
         start after one dropped call.
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


if __name__ == "__main__":
    unittest.main()
