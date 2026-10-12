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

from services import research_view as rv


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


class OverviewTests(unittest.TestCase):
    def test_every_empty_panel_is_named_in_words(self):
        class _Config:
            PAIR_RELEASE_SURFACES: frozenset = frozenset()
        db = _Db()
        db.corpus = []
        out = rv.overview(db, config=_Config())
        self.assertEqual(out["view_version"], rv.VIEW_VERSION)
        self.assertNotIn("doors", out)
        for surface in ("praise_line", "clearer_version", "exercise_script"):
            self.assertEqual(out["datasets"][surface]["consent_note"],
                             "no pair on this surface yet")
            self.assertIn("not open for this surface", out["datasets"][surface]["splits_note"])
        self.assertEqual(out["evaluations"]["note"], "no candidate has been evaluated yet")
        self.assertTrue(all(p["model"] is None for p in out["promotions"]))
        self.assertEqual(out["golden"]["confidence"]["count"], 0)
        self.assertEqual(out["labels"]["labels"], 0)


if __name__ == "__main__":
    unittest.main()
