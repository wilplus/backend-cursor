"""Cross-take selection (willab Prompt A §5). Pure gate + take-level assembly
with a fake db (no network). Asserts the AC-9 score-free fence hard.

Run: python3 -m unittest tests.test_cross_take_selection
"""
from __future__ import annotations

import unittest

import services.cross_take_selection as cts


class _FakeDB:
    def __init__(self, sessions, snippets_by_session):
        self._sessions = sessions
        self._snips = snippets_by_session

    def get_arc_sessions(self, arc_id):
        return list(self._sessions)

    @property
    def takes(self):
        # audit Q-A2: production now calls db.takes.<method>();
        # this fake implements those methods directly on itself.
        return self

    def get_snippets_by_session(self, sid):
        return list(self._snips.get(sid, []))


def _snip(sid, text, overall, rank, label=None):
    return {
        "id": sid,
        "transcript": text,
        "storage_path": f"s3://{sid}.webm",
        "start_ms": 1000,
        "duration_ms": 4000,
        "coach_label": label,
        "metrics": {"overall_score": overall, "rank": rank},
        "features": {"pause_strength": 0.3},
    }


class TakeLevelTests(unittest.TestCase):
    def _db(self):
        sessions = [
            {"id": "s1", "user_id": "u1", "take_index": 1},
            {"id": "s2", "user_id": "u1", "take_index": 2},
        ]
        snips = {
            "s1": [
                _snip("a", "weak line", overall=0.2, rank=3),
                _snip("b", "strong line", overall=0.9, rank=1),
                _snip("c", "mid line", overall=0.5, rank=2),
            ],
            "s2": [_snip("d", "chill line", overall=0.7, rank=1)],
        }
        return _FakeDB(sessions, snips)


    def test_ac9_no_score_in_any_moment(self):
        out = cts.select_cross_take("arc1", database=self._db())
        banned = {"power_score", "overall_score", "score", "rank",
                  "classifier_charisma_probability", "classifier_confidence",
                  "selection_score", "metrics"}
        for take in out["takes"]:
            for m in take["moments"]:
                leaked = banned & set(m.keys())
                self.assertEqual(leaked, set(), f"score leaked: {leaked}")
                # And no nested metrics dict either.
                self.assertNotIn("metrics", m)


if __name__ == "__main__":
    unittest.main()
