"""
STORY    As a speaker who bought a paid audit, I want the Take 1 vs Take 2
         comparison to describe what changed in words only, so that I never
         see a score or verdict.
OUTCOME
  O1  The comparison names the real difference (a wider pitch range reads
      "widened") and no verdict word ("better", "improved", "score" ...).
  O2  Never-1: the comparison carries no measurement numbers.
PROVES   O1 -> test_names_what_changed_without_a_verdict
         O2 -> test_no_measurement_numbers_reach_the_speaker (KNOWN BREACH,
               strict xfail: turns red once fixed)
"""
from __future__ import annotations

import json
import unittest

import pytest

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


    def test_names_what_changed_without_a_verdict(self):
        out = build_take_comparison("arc1", database=self._two_takes())
        self.assertEqual(out["comparison"]["f0_range"], "widened")
        blob = json.dumps(out).lower()
        for word in _VERDICT_DENYLIST:
            self.assertNotIn(word, blob, f"leaked verdict word: {word}")

    @pytest.mark.xfail(strict=True, reason=(
        "KNOWN BREACH Never-1: GET /v2/explore/arc/<id>/take-comparison "
        "(routes/v2/arcs.py v2_explore_arc_take_comparison) serves raw Hz, "
        "wpm, pause-ms values and their deltas from "
        "services/take_comparison.py build_take_comparison to the speaker"))
    def test_no_measurement_numbers_reach_the_speaker(self):
        out = build_take_comparison("arc1", database=self._two_takes())
        self.assertEqual(out["comparison"]["f0_range"], "widened")

        def numbers(node, key=None):
            if isinstance(node, dict):
                for k, v in node.items():
                    yield from numbers(v, k)
            elif isinstance(node, list):
                for v in node:
                    yield from numbers(v, key)
            elif (isinstance(node, (int, float)) and not isinstance(node, bool)
                  and key != "take_index"):
                yield key, node

        self.assertEqual(list(numbers(out)), [])


if __name__ == "__main__":
    unittest.main()
