"""Unit tests for the Lab recording session-reuse boundary."""
from __future__ import annotations

import unittest
from unittest.mock import Mock

from services.lab_session_identity import choose_guest_session_id


class SessionIdentityTests(unittest.TestCase):

    def test_missing_id_mints_a_new_session_without_a_lookup(self):
        database = Mock()
        result = choose_guest_session_id(
            None,
            database=database,
            log=Mock(),
            mint_id=lambda: "new-session",
        )
        self.assertEqual(result, "new-session")
        database.v2_get_session_by_id.assert_not_called()

    def test_fresh_existing_session_is_reused(self):
        database = Mock()
        database.v2_get_session_by_id.return_value = {"id": "fresh"}
        result = choose_guest_session_id(
            " fresh ",
            database=database,
            log=Mock(),
            mint_id=lambda: "new-session",
        )
        self.assertEqual(result, "fresh")

    def test_every_lane_marker_makes_the_session_spent(self):
        for field in (
            "recording_1_id",
            "recording_kind",
            "paired_session_id",
            "analysis_state",
            "results_published_at",
        ):
            with self.subTest(field=field):
                database = Mock()
                database.v2_get_session_by_id.return_value = {field: "set"}
                result = choose_guest_session_id(
                    "old-session",
                    database=database,
                    log=Mock(),
                    mint_id=lambda: "new-session",
                )
                self.assertEqual(result, "new-session")

    def test_lookup_failure_fails_closed_and_mints_fresh(self):
        database = Mock()
        database.v2_get_session_by_id.side_effect = RuntimeError("db down")
        log = Mock()
        result = choose_guest_session_id(
            "unknown-session",
            database=database,
            log=log,
            mint_id=lambda: "new-session",
        )
        self.assertEqual(result, "new-session")
        log.warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
