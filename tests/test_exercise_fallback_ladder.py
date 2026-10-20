"""
STORY    As the founder, I want the retired exercise fallback ladder to stay gone
         and any fallback rows already stored kept out of learning, so that no
         evaluation learns from a rung we switched off.
OUTCOME
  O1  A "general" exercise or the warm-up is offered as an ordinary exercise:
      no offer or stored trace names a fallback rung.
  O2  The learning-readiness counter excludes a stored fallback and counts it
      as excluded.
PROVES   O1 -> NoLadderTests::test_no_rung_is_ever_served
         O2 -> NeverLearnedFromTests::test_the_counter_leaves_a_fallback_out
WHY      Founder 2026-10-01 F2, ladder kept off (Q30 A), deleted 2026-10-11.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services import confident_voice_practice as cvp
from services import exercise_learning_readiness as lr


def _snippet(**over):
    return {"id": "snippet-a", "session_id": "take-1", "transcript": "the words",
            "audio_segment_path": "s3://a", "duration_ms": 4000,
            "metrics": {"wpm": 180.0}, **over}


class _Db:
    def __init__(self, rows):
        self._rows = rows
        self.assigned = []

    def list_diagnostic_exercises(self):
        return [{"exercise_id": r["exercise_id"]} for r in self._rows]

    def get_active_diagnostic_exercise(self, exercise_id):
        return next((dict(r) for r in self._rows if r["exercise_id"] == exercise_id), None)

    def list_speaking_errors(self):
        return [{"error_id": e, "status": "detected"}
                for e in ("rushing", "word_compression", "ending_compression")]

    def get_confident_voice_practice_by_take(self, _take):
        return None

    def get_confident_voice_practice_candidates(self, ids):
        return [_snippet(id=i) for i in ids]

    def get_snippets_by_session(self, _take):
        return [{"metrics": {"wpm": 150.0}}]

    def assign_confident_voice_exercise(self, **kwargs):
        self.assigned.append(kwargs)
        return {"selected_exercise_id": kwargs["candidates"][0]["exercise_id"]}

    def completed_exercise_before(self, *_args):
        return False


def _row(exercise_id, tags, *, primary=None, general=None):
    criteria = {}
    if primary:
        criteria["primary_problem_tag"] = primary
    if general:
        criteria["general_for"] = general
    return {"exercise_id": exercise_id, "version": 1, "title": exercise_id,
            "instruction": "", "introduction_copy": "",
            "explanation_video_url": "https://cdn.example/x.mp4",
            "acoustic_problem_tags": tags, "matching_criteria": criteria,
            "supported_confidence_patterns": [
                "low_confidence_rushing_dominant", "near_confident", "confident"]}


WARMUP = _row(cvp.EXERCISE_ID, ["rushing", "word_compression", "ending_compression"])
GENERAL_RUSHING = _row("general-rushing", ["rushing"], general=["rushing"])
SPECIFIC_RUSHING = _row("specific-rushing", ["rushing"], primary="rushing")
ENDING_ONLY = _row("land-it", ["ending_compression"], primary="ending_compression")
RUSHING = {"insufficient_pauses": True}


def _offer(db, fired):
    target = {"source": "confident_voice", "bookmark_tier": "exercise",
              "snippet_id": "snippet-a"}
    verdict = {"eligible": True, "pattern": "low_confidence_rushing_dominant",
               "priority": 1, "signals": fired, "snapshot": {}}
    with patch.object(cvp, "exercise_eligibility", lambda *_a, **_k: verdict):
        rows = cvp.attach_v3_exercise_offer(
            [target], take_session_id="take-1", owner_user_id="owner-1",
            database=db, ground=lambda _row: {"slide_index": 0})
    return rows[0]


class NoLadderTests(unittest.TestCase):
    def test_no_rung_is_ever_served(self):
        db = _Db([ENDING_ONLY, GENERAL_RUSHING, WARMUP])
        row = _offer(db, RUSHING)
        # Without the ladder a "general" exercise is an ordinary one, and
        # the warm-up, if active, an ordinary one too: both target rushing.
        self.assertIn(row["practice_exercise"]["exercise_id"],
                      ("general-rushing", cvp.EXERCISE_ID))
        self.assertNotIn("fallback", row["practice_exercise"])
        self.assertIsNone(db.assigned[0]["trace"]["fallback"])


class NeverLearnedFromTests(unittest.TestCase):
    def test_the_counter_leaves_a_fallback_out(self):
        self.assertIn("fallback", lr.EXCLUSIONS)
        exposure = {"assignment_id": "a1", "exercise_id": "general-rushing",
                    "owner_user_id": "u", "rendered_at": "2026-10-01"}
        trace = {"fallback": "general", "fit": "general", "observed_tags": ["rushing"],
                 "signal_rules_version": cvp.SIGNAL_RULES_VERSION,
                 "candidates": [{"exercise_id": "general-rushing", "outcome": "ranked",
                                 "main_targets": ["rushing"], "secondary_targets": []}]}
        records = lr.cohort_records(
            exposures=[exposure], assignments={"a1": {"selection_mode": "deterministic_singleton"}},
            traces={"a1": trace}, practices={}, attempts={},
            signal_rules_version=cvp.SIGNAL_RULES_VERSION)
        self.assertEqual(records[0]["excluded"], "fallback")
        self.assertFalse(records[0]["in_cohort"])
        out = lr.build_readiness(
            exposures=[exposure], assignments={"a1": {}}, traces={"a1": trace},
            practices={}, attempts={}, signal_rules_version=cvp.SIGNAL_RULES_VERSION)
        self.assertEqual(out["counted"], 0)
        self.assertEqual(out["excluded"]["fallback"], 1)


if __name__ == "__main__":
    unittest.main()
