"""Cross-take selection (willab Prompt A §5). Pure gate + take-level assembly
with a fake db (no network). Asserts the AC-9 score-free fence hard.

Run: python3 -m unittest test_cross_take_selection
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


class GateTests(unittest.TestCase):
    def test_gate_is_take_level_while_data_blocked(self):
        # _LINE_LEVEL_ENABLED is False → always "take", even with many takes.
        self.assertEqual(
            cts.preflight_granularity([{"id": 1}, {"id": 2}, {"id": 3}]),
            "take",
        )

    def test_gate_take_on_empty(self):
        self.assertEqual(cts.preflight_granularity([]), "take")

    def test_line_branch_requires_two_takes_when_enabled(self):
        cts._LINE_LEVEL_ENABLED = True
        try:
            self.assertEqual(cts.preflight_granularity([{"id": 1}]), "take")
            self.assertEqual(
                cts.preflight_granularity([{"id": 1}, {"id": 2}]), "line",
            )
        finally:
            cts._LINE_LEVEL_ENABLED = False


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

    def test_payload_shape_and_granularity(self):
        out = cts.select_cross_take("arc1", database=self._db())
        self.assertEqual(out["granularity"], "take")
        self.assertEqual(out["arc_id"], "arc1")
        self.assertEqual(out["take_count"], 2)
        self.assertEqual(len(out["takes"]), 2)
        self.assertEqual(out["takes"][0]["take_index"], 1)
        self.assertEqual(out["takes"][0]["mode"], "Baseline (natural)")
        self.assertEqual(out["takes"][1]["mode"], "Confidant (chill)")

    def test_moments_ordered_strongest_first(self):
        out = cts.select_cross_take("arc1", database=self._db())
        texts = [m["transcript"] for m in out["takes"][0]["moments"]]
        self.assertEqual(texts[0], "strong line")  # overall 0.9 wins
        self.assertEqual(texts[-1], "weak line")

    def test_max_moments_per_take_caps(self):
        out = cts.select_take_level("arc1", database=self._db(),
                                    max_moments_per_take=2)
        self.assertEqual(len(out["takes"][0]["moments"]), 2)

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

    def test_moment_has_study_fields(self):
        out = cts.select_cross_take("arc1", database=self._db())
        m = out["takes"][0]["moments"][0]
        for k in ("transcript", "audio_ref", "start_offset_ms",
                  "duration_ms", "rationale"):
            self.assertIn(k, m)

    def test_empty_arc_is_clean(self):
        out = cts.select_cross_take("arc1", database=_FakeDB([], {}))
        self.assertEqual(out["granularity"], "take")
        self.assertEqual(out["take_count"], 0)
        self.assertEqual(out["takes"], [])


class RationaleTests(unittest.TestCase):
    def test_rationale_is_plain_language_not_numbers(self):
        snip = {"metrics": {"wpm": 130, "f0_sd": 30, "pause_ratio": 0.15}}
        r = cts._moment_rationale(snip)
        # plain words, and never a raw metric token
        for token in ("wpm", "f0", "0.15", "130", "db", "score"):
            self.assertNotIn(token, r.lower())

    def test_rationale_empty_when_no_metrics(self):
        self.assertEqual(cts._moment_rationale({"metrics": None}), "")


if __name__ == "__main__":
    unittest.main()
