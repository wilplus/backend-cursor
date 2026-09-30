"""The pairs (founder 2026-09-30, C2, C5; build plan P2-1).

Pins:
  * a pair is recorded only when a draft was shown AND the final differs;
  * the coach is required as its author (never from an owner's answer, L3);
  * a write that fails never breaks the answer, and the ledger mirror is
    best-effort;
  * the counts name every surface, at zero when nothing was written, and a
    count that fails reads as unavailable upstream (the ledger), not as zero;
  * the three surfaces stay three (services.ml_surface_contracts).
"""
from __future__ import annotations

import unittest

from services import feedback_pairs as fp


class _Db:
    def __init__(self, *, fail=False):
        self.rows = []
        self.mirrored = []
        self.fail = fail

    def insert_feedback_pair(self, **fields):
        if self.fail:
            raise RuntimeError("duplicate key")
        row = {"id": f"pair-{len(self.rows) + 1}", **fields}
        self.rows.append(row)
        return row

    def create_admin_annotation_event(self, **fields):
        self.mirrored.append(fields)


class RuleTests(unittest.TestCase):
    def test_a_differing_final_is_recorded_with_its_provenance(self):
        db = _Db()
        row = fp.record_pair(
            db, surface="praise_line", draft="You held the pause.",
            final="You let the number land.", coach_id="coach-1",
            model_version="gpt-x", pattern_key="pause_before_point",
            owner_user_id="owner-1", take_session_id="take-1",
            snippet_id="snip-1", request_id="req-1")
        self.assertEqual(row["surface"], "praise_line")
        self.assertEqual(row["coach_id"], "coach-1")
        self.assertEqual(row["owner_user_id"], "owner-1")
        self.assertEqual(row["draft_model_version"], "gpt-x")
        self.assertEqual(db.mirrored[0]["field_name"], "praise_line")
        self.assertEqual(db.mirrored[0]["ai_original_text"], "You held the pause.")

    def test_an_unchanged_final_is_no_pair(self):
        db = _Db()
        self.assertIsNone(fp.record_pair(
            db, surface="praise_line", draft="Same  words.", final="Same words.",
            coach_id="coach-1", request_id="req-1"))
        self.assertEqual(db.rows, [])

    def test_no_draft_shown_is_no_pair(self):
        db = _Db()
        self.assertIsNone(fp.record_pair(
            db, surface="clearer_version", draft=None, final="Clear.",
            coach_id="coach-1", request_id="req-1"))
        self.assertEqual(db.rows, [])

    def test_a_pair_needs_its_coach(self):
        db = _Db()
        self.assertIsNone(fp.record_pair(
            db, surface="clearer_version", draft="a", final="b", coach_id="",
            request_id="req-1"))
        self.assertEqual(db.rows, [])

    def test_an_unknown_surface_is_refused(self):
        db = _Db()
        self.assertIsNone(fp.record_pair(
            db, surface="moment_suggestion", draft="a", final="b",
            coach_id="c", request_id="req-1"))
        self.assertEqual(db.rows, [])

    def test_a_failed_write_never_raises(self):
        db = _Db(fail=True)
        self.assertIsNone(fp.record_pair(
            db, surface="exercise_script", draft="a", final="b", coach_id="c",
            exercise_id="ex-1", exercise_version=2))

    def test_a_transcript_is_a_second_final_on_the_exercise_lane(self):
        db = _Db()
        row = fp.record_pair(
            db, surface="exercise_script", draft="Say it once, then pause.",
            final="say it once and then pause before you go on",
            final_kind="transcript", coach_id="c", exercise_id="ex-1",
            exercise_version=2)
        self.assertEqual(row["final_kind"], "transcript")


class CountTests(unittest.TestCase):
    def test_every_surface_is_named_at_zero(self):
        class _Counts:
            def count_feedback_pairs(self):
                return {"praise_line": {"total": 3, "unexported": 1}}
        self.assertEqual(fp.counts(_Counts()), {
            "praise_line": {"total": 3, "unexported": 1},
            "clearer_version": {"total": 0, "unexported": 0},
            "exercise_script": {"total": 0, "unexported": 0},
        })

    def test_the_surfaces_are_locked_prompts_and_not_yet_model_slots(self):
        """A pair surface is a prompt id namespace with a golden dataset; a
        promotable model slot (services.ml_surface_contracts) is door 3/4
        work and comes with its own authorisation (build plan ML-11)."""
        import json
        import pathlib
        from services.ml_surface_contracts import SURFACES
        from services.mlc2_foundation import REJECTED_LEARNING_ALIASES
        root = pathlib.Path(__file__).resolve().parents[1]
        locked = json.loads((root / "services/prompts/prompts.lock.json").read_text())["prompts"]
        for surface in fp.SURFACES:
            self.assertNotIn(surface, REJECTED_LEARNING_ALIASES)
            self.assertNotIn(surface, SURFACES)
            self.assertIn(f"{surface}.system", locked)


if __name__ == "__main__":
    unittest.main()
