"""Paid Audits — take-1-vs-take-2 comparison (BE chunk A6). Pure (fake db).

Run: python3 -m unittest tests.test_take_comparison
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

    @property
    def takes(self):
        # audit Q-A2: production now calls db.takes.<method>();
        # this fake implements those methods directly on itself.
        return self

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


    def test_no_verdict_vocabulary_serialized(self):
        # The whole point of D8: the teaser must never leak a score/verdict word.
        out = build_take_comparison("arc1", database=self._two_takes())
        blob = json.dumps(out).lower()
        for word in _VERDICT_DENYLIST:
            self.assertNotIn(word, blob, f"leaked verdict word: {word}")


if __name__ == "__main__":
    unittest.main()
