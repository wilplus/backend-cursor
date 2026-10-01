"""The research screen's read and the golden set (founder 2026-09-30; ML-7).

Pins:
  * the quorum counts human labels only, two-human agreement, and kappa
    only from a hundred labels;
  * every closed door is named in words, never a zero that reads as a
    measurement;
  * the golden set serves unjudged moments from the coach-labelled pool
    without a label or a machine read, records one judgement per moment,
    and seals only at fifty, once, with a hash that ignores order.
"""
from __future__ import annotations

import unittest

from services import golden_set as gs
from services import research_quorum as rq
from services import research_view as rv


def _label(snippet, rater, value, **extra):
    return {"snippet_id": snippet, "rater_id": rater, "value": value, "lane": "coach", **extra}


class QuorumTests(unittest.TestCase):
    def test_two_human_agreement_and_human_only(self):
        rows = [
            _label("s1", "a", "yes"), _label("s1", "b", "yes"),
            _label("s2", "a", "no"), _label("s2", "b", "in_between"),
            _label("s3", "a", "yes"),
            _label("s4", "owner", "yes", self_report=True), _label("s4", "a", "no"),
        ]
        out = rq.quorum(rows)
        self.assertEqual(out["labels"], 6)
        self.assertEqual(out["moments"], 4)
        self.assertEqual(out["moments_with_two_humans"], 2)
        self.assertEqual(out["two_human_agreement"], 0.5)
        self.assertIsNone(out["kappa"])

    def test_kappa_from_a_hundred_labels(self):
        rows = []
        for i in range(60):
            value = "yes" if i % 2 else "no"
            rows.append(_label(f"s{i}", "a", value))
            rows.append(_label(f"s{i}", "b", value if i % 3 else "in_between"))
        out = rq.quorum(rows)
        self.assertEqual(out["labels"], 120)
        self.assertIsNotNone(out["kappa"])
        self.assertGreaterEqual(out["kappa"], 0.5)
        self.assertEqual(rq.cohen_kappa([("yes", "yes"), ("no", "no")]), 1.0)
        self.assertIsNone(rq.cohen_kappa([]))


class _Db:
    def __init__(self):
        self.judgements = []
        self.sealed = None
        self.corpus = [{"snippet_id": "s1"}, {"snippet_id": "s2"}, {"snippet_id": "s1"}]

    def get_confidence_label_corpus(self, limit=5000):
        return self.corpus

    def get_snippet_by_id(self, sid, user_id=None):
        return {"id": sid, "session_id": "take-1", "transcript": f"words of {sid}",
                "audio_segment_path": "https://r2/x.webm", "start_offset_ms": 10, "duration_ms": 900}

    def list_golden_judgements(self, *, surface, judge=None):
        return [j for j in self.judgements if j["surface"] == surface and (judge is None or j["judge_email"] == judge)]

    def insert_golden_judgement(self, **fields):
        self.judgements.append(fields)
        return fields

    def get_golden_set(self, surface):
        return self.sealed

    def seal_golden_set(self, **fields):
        self.sealed = fields
        return fields

    def get_runtime_config(self, key):
        return None

    def list_dataset_releases(self):
        return []

    def list_dataset_exclusions(self):
        return []

    def list_annotation_export_runs(self, limit=20):
        return []

    def list_ledger_snapshots(self, limit=8):
        return []

    def list_pair_releases(self, limit=20):
        return []

    def list_evaluation_reports(self, limit=20):
        return []

    def list_fine_tune_runs(self, status=None, limit=20):
        return []

    def list_model_promotions(self, limit=20):
        return []

    def count_feedback_pairs(self):
        return {}

    def list_verbal_cue_shadow_observations(self, cue, version):
        return []

    def list_coach_named_moments(self, cue):
        return []


class GoldenTests(unittest.TestCase):
    def test_the_next_moment_carries_no_label_and_no_read(self):
        db = _Db()
        moment = gs.next_moment(db, surface="confidence", judge="artur@willonski.com")
        self.assertEqual(set(moment), {"snippet_id", "take_session_id", "passage", "audio_url",
                                       "start_offset_ms", "duration_ms"})
        self.assertEqual(moment["snippet_id"], "s1")
        gs.record(db, surface="confidence", judge="artur@willonski.com",
                  body={"snippet_id": "s1", "value": "yes"})
        self.assertEqual(gs.next_moment(db, surface="confidence", judge="artur@willonski.com")["snippet_id"], "s2")

    def test_sealing_needs_fifty_and_happens_once(self):
        db = _Db()
        for i in range(49):
            gs.record(db, surface="confidence", judge="f", body={"snippet_id": f"s{i}", "value": "no"})
        with self.assertRaises(gs.GoldenRefusal) as refused:
            gs.seal(db, surface="confidence", judge="f")
        self.assertEqual(refused.exception.code, "GOLDEN_SET_INCOMPLETE")
        gs.record(db, surface="confidence", judge="f", body={"snippet_id": "s49", "value": "yes"})
        sealed = gs.seal(db, surface="confidence", judge="f")["sealed"]
        self.assertEqual(sealed["count"], 50)
        self.assertRegex(sealed["sha256"], r"^[0-9a-f]{64}$")
        with self.assertRaises(gs.GoldenRefusal):
            gs.record(db, surface="confidence", judge="f", body={"snippet_id": "s50", "value": "yes"})
        with self.assertRaises(gs.GoldenRefusal):
            gs.seal(db, surface="confidence", judge="f")

    def test_the_hash_ignores_order(self):
        a = gs.digest([{"snippet_id": "s1", "value": "yes"}, {"snippet_id": "s2", "value": "no"}])
        b = gs.digest([{"snippet_id": "s2", "value": "no"}, {"snippet_id": "s1", "value": "yes"}])
        self.assertEqual(a, b)

    def test_an_unknown_surface_is_refused(self):
        with self.assertRaises(gs.GoldenRefusal):
            gs.counts(_Db(), surface="score")


class OverviewTests(unittest.TestCase):
    def test_every_closed_door_is_named_in_words(self):
        class _Config:
            MLC2_TRAINING_SWITCH_ENABLED = False
            MLC2_PAIR_RELEASES_ENABLED = False
            MLC2_TRAINING_ENABLED = False
            MLC2_PROMOTION_ENABLED = False
        db = _Db()
        db.corpus = []
        out = rv.overview(db, config=_Config())
        self.assertEqual(out["view_version"], rv.VIEW_VERSION)
        for surface in ("praise_line", "clearer_version", "exercise_script"):
            self.assertIn("door 1 closed", out["datasets"][surface]["consent_note"])
            self.assertIn("door 2 closed", out["datasets"][surface]["splits_note"])
        self.assertIn("door 3 closed", out["evaluations"]["note"])
        self.assertTrue(all(p["model"] is None for p in out["promotions"]))
        self.assertEqual(out["golden"]["confidence"]["count"], 0)
        self.assertEqual(out["labels"]["labels"], 0)


if __name__ == "__main__":
    unittest.main()
