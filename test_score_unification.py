import unittest

try:
    from services import homework_completion as hc
    _IMPORT_ERROR = None
except Exception as import_err:  # pragma: no cover - environment bootstrap guard
    hc = None
    _IMPORT_ERROR = import_err


@unittest.skipIf(_IMPORT_ERROR is not None, f"score tests require full app deps: {_IMPORT_ERROR}")
class ScoreUnificationTests(unittest.TestCase):
    def setUp(self):
        self._orig_get_sniper = hc.db.get_session_sniper_metrics

    def tearDown(self):
        hc.db.get_session_sniper_metrics = self._orig_get_sniper

    def test_unified_score_returns_consistent_pair(self):
        hc.db.get_session_sniper_metrics = lambda _sid: {
            "stage_score": 0.62,
            "pause_ms": 430,
            "dynamic_db": 17.5,
            "energy_ratio": 0.74,
            "pitch_frame_count": 42,
            "student_rating_1_10": 4,
        }
        score_100, score_01, meta = hc._build_unified_score_payload(
            session={"score": 0.57, "self_rating_submitted_at": "2026-01-01T00:00:00Z"},
            session_id="s1",
            user_id="u1",
            recording={"performance_metrics_v2": {"scoring_debug": {"score_01": 0.57}}},
            transcript="Today I present a concise talk about confidence and pacing.",
            context_short="talk about confidence and pacing",
            filler_count=0,
        )
        self.assertGreaterEqual(score_100, 0)
        self.assertLessEqual(score_100, 100)
        self.assertAlmostEqual(score_01, round(score_100 / 100.0, 4), places=4)
        self.assertEqual(meta["canonical"]["score_for_display"], score_100)

    def test_filler_cap_blocks_100(self):
        hc.db.get_session_sniper_metrics = lambda _sid: {
            "stage_score": 1.0,
            "pause_ms": 450,
            "dynamic_db": 17.0,
            "energy_ratio": 0.72,
            "pitch_frame_count": 50,
            "student_rating_1_10": 5,
        }
        score_100, score_01, _meta = hc._build_unified_score_payload(
            session={"score": 1.0, "self_rating_submitted_at": "2026-01-01T00:00:00Z"},
            session_id="s2",
            user_id="u2",
            recording={"performance_metrics_v2": {"scoring_debug": {"score_01": 1.0}}},
            transcript="Very strong transcript with all expected context words included.",
            context_short="strong transcript context words",
            filler_count=2,
        )
        self.assertLessEqual(score_100, 99)
        self.assertLessEqual(score_01, 0.99)


if __name__ == "__main__":
    unittest.main()
