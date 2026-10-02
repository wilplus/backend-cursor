"""The exercise fallback ladder (founder 2026-10-01, F2; Phase 1 of the
after-practice paths), dark behind EXERCISE_FALLBACK_LADDER_ENABLED.

Pins: off, nothing changes; on, a moment whose fired error no pooled
exercise targets gets the general exercise for that error, else the
warm-up, else nothing; a general exercise never enters the ranked pool; the
rung is marked in the trace and the offer; the readiness counter leaves a
fallback out, so no label, fair test or evaluation ever learns from it; the
coach request still rises.
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


class OffTests(unittest.TestCase):
    """The off behaviour, under the switch patched off (the live default is
    on since the founder's yes of 2026-10-02)."""
    def setUp(self):
        self._off = patch("config.Config.EXERCISE_FALLBACK_LADDER_ENABLED", False)
        self._off.start()
        self.addCleanup(self._off.stop)

    def test_the_switch_is_on_since_the_founders_yes(self):
        self._off.stop()
        from config import Config as _live
        self.assertTrue(_live.EXERCISE_FALLBACK_LADDER_ENABLED)
        self._off.start()

    def test_off_is_exactly_yesterday(self):
        db = _Db([ENDING_ONLY, GENERAL_RUSHING, WARMUP])
        row = _offer(db, RUSHING)
        # With the ladder off a "general" exercise is an ordinary one, and
        # the warm-up, if active, an ordinary one too: both target rushing.
        self.assertIn(row["practice_exercise"]["exercise_id"],
                      ("general-rushing", cvp.EXERCISE_ID))
        self.assertNotIn("fallback", row["practice_exercise"])
        self.assertIsNone(db.assigned[0]["trace"]["fallback"])


@patch("config.Config.EXERCISE_FALLBACK_LADDER_ENABLED", True)
class LadderTests(unittest.TestCase):
    def test_the_general_exercise_serves_when_nothing_pooled_targets_the_error(self):
        db = _Db([ENDING_ONLY, GENERAL_RUSHING, WARMUP])
        row = _offer(db, RUSHING)
        offer = row["practice_exercise"]
        self.assertEqual(offer["exercise_id"], "general-rushing")
        self.assertEqual(offer["fallback"], "general")
        self.assertTrue(row["problem_recognised"])
        trace = db.assigned[0]["trace"]
        self.assertEqual((trace["fallback"], trace["fit"]), ("general", "general"))
        self.assertEqual(db.assigned[0]["matching_policy_version"],
                         "exercise-fit-tier-v1:general")
        self.assertEqual([c["exercise_id"] for c in trace["candidates"]
                          if c["outcome"] == "ranked"], ["general-rushing"])

    def test_the_warm_up_is_the_last_rung(self):
        db = _Db([ENDING_ONLY, WARMUP])
        offer = _offer(db, RUSHING)["practice_exercise"]
        self.assertEqual((offer["exercise_id"], offer["fallback"]),
                         (cvp.EXERCISE_ID, "warmup"))

    def test_no_rung_is_still_nothing_and_the_coach_still_hears(self):
        db = _Db([ENDING_ONLY])
        row = _offer(db, RUSHING)
        self.assertNotIn("practice_exercise", row)
        self.assertTrue(row["problem_recognised"])
        self.assertEqual(db.assigned, [])

    def test_nothing_spotted_gets_no_rung(self):
        db = _Db([GENERAL_RUSHING, WARMUP])
        row = _offer(db, {})
        self.assertNotIn("practice_exercise", row)
        self.assertEqual(db.assigned, [])

    def test_a_general_exercise_never_enters_the_ranked_pool(self):
        db = _Db([SPECIFIC_RUSHING, GENERAL_RUSHING, WARMUP])
        row = _offer(db, RUSHING)
        offer = row["practice_exercise"]
        self.assertEqual(offer["exercise_id"], "specific-rushing")
        self.assertNotIn("fallback", offer)
        trace = db.assigned[0]["trace"]
        self.assertIsNone(trace["fallback"])
        self.assertEqual([c["exercise_id"] for c in trace["candidates"]
                          if c["outcome"] == "ranked"], ["specific-rushing"])

    def test_split_pool_sorts_the_catalogue(self):
        pool, generals, warmup = cvp.split_pool([SPECIFIC_RUSHING, GENERAL_RUSHING, WARMUP])
        self.assertEqual([e["exercise_id"] for e in pool], ["specific-rushing"])
        self.assertEqual([e["exercise_id"] for e in generals], ["general-rushing"])
        self.assertEqual(warmup["exercise_id"], cvp.EXERCISE_ID)


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
