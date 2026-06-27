"""Candidate-pool capture (automation-audit fix #1). Pure.

Run: python3 -m unittest test_candidate_capture
"""
from __future__ import annotations

import unittest

from services.candidate_capture import (
    build_candidate_rows, SELECTOR_VERSION, FEATURES_VERSION,
)


def _cand(start, dur=1000, **m):
    return {"start_ms": start, "dur_ms": dur,
            "metrics": {"f0_mean": 110.0, "wpm": 120.0, **m},
            "transcript": f"line at {start}"}


class BuildCandidateRowsTests(unittest.TestCase):
    def _pool(self):
        # 5-window pool; notable = {0,1000,2000,3000}; surfaced = {0,2000}.
        candidates = [_cand(s) for s in (0, 1000, 2000, 3000, 4000)]
        notable_starts = {0, 1000, 2000, 3000}
        surfaced_info = {
            0: {"rank": 2, "snippet_id": "snip-a"},
            2000: {"rank": 1, "snippet_id": "snip-b"},
        }
        return candidates, notable_starts, surfaced_info

    def _rows(self):
        candidates, notable_starts, surfaced_info = self._pool()
        return build_candidate_rows(
            candidates, notable_starts=notable_starts, surfaced_info=surfaced_info,
            session_id="sess1", recording_id="rec1", user_id="u1",
        )

    def test_full_pool_persisted(self):
        rows = self._rows()
        self.assertEqual(len(rows), 5)  # ALL windows, not just the surfaced 2
        self.assertEqual([r["start_offset_ms"] for r in rows],
                         [0, 1000, 2000, 3000, 4000])

    def test_surfaced_and_notable_flags(self):
        by_start = {r["start_offset_ms"]: r for r in self._rows()}
        self.assertTrue(by_start[0]["surfaced"])
        self.assertTrue(by_start[2000]["surfaced"])
        self.assertFalse(by_start[1000]["surfaced"])  # notable but not surfaced
        self.assertFalse(by_start[4000]["surfaced"])  # dropped entirely
        self.assertTrue(by_start[1000]["notable"])
        self.assertFalse(by_start[4000]["notable"])

    def test_surfaced_carries_rank_and_snippet_id(self):
        by_start = {r["start_offset_ms"]: r for r in self._rows()}
        self.assertEqual(by_start[2000]["surfaced_rank"], 1)
        self.assertEqual(by_start[2000]["snippet_id"], "snip-b")
        self.assertEqual(by_start[0]["surfaced_rank"], 2)
        # dropped windows have no rank / snippet link
        self.assertIsNone(by_start[4000]["surfaced_rank"])
        self.assertIsNone(by_start[4000]["snippet_id"])

    def test_pool_position_and_provenance(self):
        rows = self._rows()
        self.assertEqual([r["pool_position"] for r in rows], [0, 1, 2, 3, 4])
        # Both stamps present: selector generation AND feature-extractor
        # generation (they drift independently — corpus stays segmentable).
        self.assertTrue(all(r["heuristic_version"] == SELECTOR_VERSION for r in rows))
        self.assertTrue(all(r["features_version"] == FEATURES_VERSION for r in rows))

    def test_metrics_is_raw_vector_no_selection_score(self):
        # FENCE (snippet_salience.py): the raw acoustic vector is stored; NO
        # salience/control/overall selection SCORE is injected into metrics by
        # the capture. (Checked on the metrics blob — NOT the heuristic_version
        # provenance stamp, which legitimately names the selector.)
        for r in self._rows():
            mkeys = " ".join(str(k).lower() for k in (r["metrics"] or {}))
            for banned in ("salience", "overall_score", "control",
                           "power_score", "rank"):
                self.assertNotIn(banned, mkeys, banned)
        self.assertIn("f0_mean", self._rows()[0]["metrics"])

    def test_malformed_candidate_skipped(self):
        rows = build_candidate_rows(
            [_cand(0), {"no_start": True}, None, _cand(1000)],
            notable_starts={0}, surfaced_info={}, session_id="s",
            recording_id="r", user_id=None,
        )
        self.assertEqual(len(rows), 2)  # the two valid windows only

    def test_empty_pool(self):
        self.assertEqual(build_candidate_rows(
            [], notable_starts=set(), surfaced_info={},
            session_id="s", recording_id="r", user_id=None), [])


if __name__ == "__main__":
    unittest.main()
