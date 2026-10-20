"""
STORY    As a speaker, I want the strongest moments of each of my Takes shown
         without any score or rank, so that feedback stays in words.
OUTCOME
  O1  Each Take shows its own strongest moments, strongest first, up to the
      limit, with their words and audio.
  O2  Never-1: no moment carries a score, rank, probability or metrics block,
      at any depth of the payload.
PROVES   O1 -> test_each_take_shows_its_strongest_moments_first
         O2 -> test_ac9_no_score_in_any_moment
WHY      AC-9: the ranking score is used internally and never serialized.
"""
from __future__ import annotations

import unittest

import services.cross_take_selection as cts

_BANNED = {"power_score", "overall_score", "score", "rank", "selection_score",
           "classifier_charisma_probability", "classifier_confidence",
           "probability", "metrics", "voice_confidence"}


class _FakeDB:
    def __init__(self, sessions, snippets_by_session):
        self._sessions = sessions
        self._snips = snippets_by_session

    def get_arc_sessions(self, arc_id):
        return list(self._sessions)

    @property
    def takes(self):
        # Production calls db.takes.<method>(); the fake answers both.
        return self

    def get_snippets_by_session(self, sid):
        return list(self._snips.get(sid, []))


def _snip(sid, text, overall, rank):
    return {
        "id": sid,
        "transcript": text,
        "storage_path": f"s3://{sid}.webm",
        "start_ms": 1000,
        "duration_ms": 4000,
        "metrics": {"overall_score": overall, "rank": rank,
                    "voice_confidence": {"score": 0.4}},
        "features": {"pause_strength": 0.3},
    }


def _keys(value):
    """Every dict key anywhere inside ``value``."""
    if isinstance(value, dict):
        for key, inner in value.items():
            yield key
            yield from _keys(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _keys(inner)


def _db():
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


class TakeLevelTests(unittest.TestCase):

    def test_each_take_shows_its_strongest_moments_first(self):
        out = cts.select_cross_take("arc1", database=_db(), max_moments_per_take=2)
        chosen = {take["session_id"]: [m["snippet_id"] for m in take["moments"]]
                  for take in out["takes"]}
        self.assertEqual(chosen, {"s1": ["b", "c"], "s2": ["d"]})
        first = out["takes"][0]["moments"][0]
        self.assertEqual((first["transcript"], first["audio_ref"]),
                         ("strong line", "s3://b.webm"))

    def test_ac9_no_score_in_any_moment(self):
        out = cts.select_cross_take("arc1", database=_db())
        moments = [m for take in out["takes"] for m in take["moments"]]
        self.assertEqual(len(moments), 4)
        self.assertTrue(all(m["transcript"] for m in moments))
        leaked = _BANNED & set(_keys(out))
        self.assertEqual(leaked, set(), f"score leaked: {leaked}")


if __name__ == "__main__":
    unittest.main()
