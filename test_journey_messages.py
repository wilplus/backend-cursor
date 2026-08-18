from __future__ import annotations

import unittest

from services.journey_messages import journey_client_id, journey_message, journey_seen
from routes.v2.explore_ideal_text import _completed_spoken_sessions


class _Db:
    def __init__(self, found=None):
        self.found = found

    def get_lounge_message_by_client_id(self, user_id, client_id):
        return self.found


class JourneyMessageTests(unittest.TestCase):
    def test_idempotency_key_is_stable_per_owner_project_and_take(self):
        first = journey_client_id("u1", "a1", 1)
        self.assertEqual(first, journey_client_id("u1", "a1", 1))
        self.assertNotEqual(first, journey_client_id("u1", "a1", 2))
        self.assertNotEqual(first, journey_client_id("u1", "a2", 1))

    def test_take_one_copy_and_action_are_locked(self):
        row = journey_message("u1", "a1", 1)
        self.assertEqual(row["kind"], "cadence")
        self.assertTrue(row["body"].startswith("Your first talk track is ready."))
        self.assertEqual(row["metadata"]["actions"], ["prepare_take_2"])

    def test_take_three_has_completion_actions(self):
        row = journey_message("u1", "a1", 3)
        self.assertEqual(row["metadata"]["actions"], [
            "presentation_mode", "export", "keep_practising",
        ])

    def test_fourth_take_has_no_guided_next_steps(self):
        self.assertIsNone(journey_message("u1", "a1", 4))
        self.assertTrue(journey_seen(_Db(), "u1", "a1", 4))

    def test_seen_reads_the_deterministic_event(self):
        self.assertFalse(journey_seen(_Db(), "u1", "a1", 2))
        self.assertTrue(journey_seen(_Db({"id": "m1"}), "u1", "a1", 2))

    def test_only_successfully_processed_spoken_takes_advance_journey(self):
        rows = _completed_spoken_sessions([
            {"id": "ready", "analysis_state": "ready"},
            {"id": "legacy"},
            {"id": "pending", "analysis_state": "processing"},
            {"id": "failed", "analysis_state": "failed"},
            {"id": "read", "recording_kind": "read",
             "analysis_state": "ready"},
            {"id": "paired", "paired_session_id": "ready",
             "analysis_state": "ready"},
        ])
        self.assertEqual([row["id"] for row in rows], ["ready", "legacy"])


if __name__ == "__main__":
    unittest.main()
