"""Unit tests for the snippet-level persisted readout preparation stage."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from services.readout_snippets import (
    prepare_readout_snippets,
    replay_applied_upgrades,
)


def _snippet() -> dict:
    return {
        "id": "snip-1",
        "transcript": "original words",
        "audio_segment_path": "r2://parent.webm",
        "start_offset_ms": 1200,
        "duration_ms": 3400,
        "say_it_stronger": {"upgrades": [{"text": "draft"}]},
        "say_it_stronger_final": {
            "upgrades": [{"text": "final one"}, {"text": "final two"}],
        },
        "metrics": {
            "piece": {"index": 2, "slide_index": 1},
            "recording_kind": "spoken",
            "stickiness": {"composite": 0.6, "comment": "clear"},
            "slide_stickiness": {"composite": 0.7},
            "overall_score": 0.8,
            "rank": 1,
            "acoustic_read": {"potentiometer": 0.4},
            "voice_confidence": {"score": 0.99},
        },
    }


def _database() -> MagicMock:
    database = MagicMock()
    database.get_user_transcript_edits.return_value = []
    database.get_suggestion_feedback_by_session.return_value = []
    return database


def _prepare(database, *, coach=False, upgrades=True, insights=False):
    return prepare_readout_snippets(
        database,
        "session-1",
        [_snippet()],
        include_insights=insights,
        include_slide_scores=coach,
        include_upgrade_cards=upgrades,
        playable=lambda ref: f"playable:{ref}",
        feature_builder=lambda metrics: {"f0_mean": metrics.get("f0_mean")},
        coach_prefill_enabled=lambda: False,
    )


class ReadoutSnippetPreparationTests(unittest.TestCase):

    def test_user_surface_is_an_allowlist_and_prefers_final_upgrade_card(self):
        rows, _ = _prepare(_database())
        row = rows[0]

        self.assertEqual(row["audio_ref"], "playable:r2://parent.webm")
        self.assertEqual(row["piece_index"], 2)
        self.assertEqual(row["slide_index"], 1)
        self.assertEqual(row["recording_kind"], "spoken")
        self.assertEqual(
            row["say_it_stronger"]["upgrades"][0]["text"],
            "final one",
        )
        for private in (
            "slide_stickiness",
            "overall_score",
            "rank",
            "acoustic_read",
            "voice_confidence",
        ):
            self.assertNotIn(private, row)

    def test_coach_surface_gets_coach_fields_but_never_confidence_composite(self):
        rows, _ = _prepare(_database(), coach=True)
        row = rows[0]

        self.assertEqual(row["slide_stickiness"], {"composite": 0.7})
        self.assertEqual(row["overall_score"], 0.8)
        self.assertEqual(row["rank"], 1)
        self.assertNotIn("acoustic_read", row)
        self.assertEqual(
            row["say_it_stronger_draft"]["upgrades"][0]["text"],
            "draft",
        )
        self.assertNotIn("voice_confidence", row)

    def test_user_edits_and_current_applied_state_are_folded(self):
        database = _database()
        database.get_user_transcript_edits.return_value = [
            {"snippet_id": "snip-1", "text": "  edited moment  "},
            {"chunk_index": 3, "text": " edited chunk "},
        ]
        database.get_suggestion_feedback_by_session.return_value = [
            {"snippet_id": "snip-1", "action": "apply_all"},
            {
                "snippet_id": "snip-1",
                "target": "upgrade",
                "upgrade_index": 0,
                "action": "reverted",
            },
        ]

        rows, chunk_edits = _prepare(database)

        self.assertEqual(rows[0]["user_edited_text"], "edited moment")
        self.assertEqual(rows[0]["applied_upgrade_indexes"], [1])
        self.assertEqual(chunk_edits, {3: "edited chunk"})

    def test_disabled_upgrade_cards_have_no_applied_state(self):
        database = _database()
        database.get_suggestion_feedback_by_session.return_value = [
            {"snippet_id": "snip-1", "action": "apply_all"},
        ]

        rows, _ = _prepare(database, upgrades=False)

        self.assertIsNone(rows[0]["say_it_stronger"])
        self.assertNotIn("applied_upgrade_indexes", rows[0])

class AppliedUpgradeReplayTests(unittest.TestCase):

    def test_unknown_rows_booleans_and_out_of_range_indexes_are_ignored(self):
        rows = [
            None,
            {"snippet_id": "s", "action": "applied", "target": "upgrade",
             "upgrade_index": True},
            {"snippet_id": "s", "action": "applied", "target": "upgrade",
             "upgrade_index": 9},
            {"snippet_id": "s", "action": "applied", "target": "upgrade",
             "upgrade_index": 1},
        ]

        self.assertEqual(replay_applied_upgrades(rows, {"s": 2}), {"s": [1]})


if __name__ == "__main__":
    unittest.main()
