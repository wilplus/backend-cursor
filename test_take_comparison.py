"""Paid Audits — take-1-vs-take-2 comparison (BE chunk A6). Pure (fake db).

Run: python3 -m unittest test_take_comparison
"""
from __future__ import annotations

import json
import unittest

from services.take_comparison import build_take_comparison


class _FakeDB:
    def __init__(self, sessions, snips_by_sid):
        self._sessions = sessions
        self._snips = snips_by_sid

    def get_arc_sessions(self, arc_id):
        return list(self._sessions)

    def get_snippets_by_session(self, sid):
        return list(self._snips.get(sid, []))


def _snip(f0, wpm, pause):
    return {"metrics": {"f0_mean": f0, "wpm": wpm, "pause_ms": pause}}


# AC-9 / D8: none of these may EVER appear in the serialized comparison.
_VERDICT_DENYLIST = (
    "score", "verdict", "rating", "better", "worse", "stronger", "weaker",
    "improved", "improve", "charisma", "charismatic", "stress", "threat",
    "challenge", "confident", "confidence", "ratio", "percentile", "rank",
)


class TakeComparisonTests(unittest.TestCase):
    def _two_takes(self):
        sessions = [
            {"id": "s1", "take_index": 1},
            {"id": "s2", "take_index": 2},
        ]
        snips = {
            # take 1: f0 110/120 (range 10), wpm 100/120, pause 400/600
            "s1": [_snip(110, 100, 400), _snip(120, 120, 600)],
            # take 2: f0 100/160 (range 60 → widened), wpm 140/160, pause 300/300
            "s2": [_snip(100, 140, 300), _snip(160, 160, 300)],
        }
        return _FakeDB(sessions, snips)

    def test_per_take_aggregates(self):
        out = build_take_comparison("arc1", database=self._two_takes())
        self.assertEqual(out["take_count"], 2)
        t1 = out["takes"][0]["metrics"]
        self.assertEqual(t1["f0_mean_hz"], 115.0)
        self.assertEqual(t1["speech_rate_wpm"], 110.0)
        self.assertEqual(t1["f0_range_hz"], 10.0)
        self.assertEqual(t1["pause_ms_mean"], 500.0)

    def test_range_descriptor_widened(self):
        out = build_take_comparison("arc1", database=self._two_takes())
        # take1 range 10 → take2 range 60 → widened.
        self.assertEqual(out["comparison"]["f0_range"], "widened")
        self.assertIn(out["comparison"]["f0_range"],
                      ("widened", "narrowed", "steadied"))

    def test_signed_deltas_are_raw(self):
        out = build_take_comparison("arc1", database=self._two_takes())
        d = out["comparison"]["deltas"]
        self.assertEqual(d["f0_range_hz"], 50.0)        # 60 - 10
        self.assertEqual(d["speech_rate_wpm"], 40.0)    # 150 - 110

    def test_steadied_when_range_change_small(self):
        sessions = [{"id": "s1", "take_index": 1}, {"id": "s2", "take_index": 2}]
        snips = {
            "s1": [_snip(100, 120, 400), _snip(120, 120, 400)],  # range 20
            "s2": [_snip(101, 120, 400), _snip(122, 120, 400)],  # range 21
        }
        out = build_take_comparison("arc1", database=_FakeDB(sessions, snips))
        self.assertEqual(out["comparison"]["f0_range"], "steadied")

    def test_single_take_no_comparison(self):
        sessions = [{"id": "s1", "take_index": 1}]
        snips = {"s1": [_snip(110, 100, 400)]}
        out = build_take_comparison("arc1", database=_FakeDB(sessions, snips))
        self.assertIsNone(out["comparison"])
        self.assertEqual(out["take_count"], 1)

    def test_empty_arc(self):
        out = build_take_comparison("arc1", database=_FakeDB([], {}))
        self.assertEqual(out["take_count"], 0)
        self.assertIsNone(out["comparison"])

    def test_no_verdict_vocabulary_serialized(self):
        # The whole point of D8: the teaser must never leak a score/verdict word.
        out = build_take_comparison("arc1", database=self._two_takes())
        blob = json.dumps(out).lower()
        for word in _VERDICT_DENYLIST:
            self.assertNotIn(word, blob, f"leaked verdict word: {word}")


if __name__ == "__main__":
    unittest.main()
