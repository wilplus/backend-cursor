import unittest

from services.behavioral_profiles import BehavioralProfile, is_valid_profile
from services.session_diagnosis import (
    DYNAMIC_DB_HEALTHY_THRESHOLD,
    SessionMetrics,
    build_session_metrics,
    diagnose_and_persist_session,
    diagnose_session_state,
)


class BehavioralProfileEnumTests(unittest.TestCase):
    def test_profile_values_match_db_check_constraint(self):
        expected = {"The Stressor", "The Drifter", "The Overwhelmed", "The Master"}
        self.assertEqual({p.value for p in BehavioralProfile}, expected)

    def test_is_valid_profile(self):
        self.assertTrue(is_valid_profile("The Master"))
        self.assertFalse(is_valid_profile("the master"))
        self.assertFalse(is_valid_profile(""))
        self.assertFalse(is_valid_profile(None))
        self.assertFalse(is_valid_profile(42))


class DiagnoseSessionStateTests(unittest.TestCase):
    def test_stressor_from_high_wpm(self):
        profile = diagnose_session_state(
            SessionMetrics(wpm=185.0, pause_ms=300, filler_count=1, dynamic_db=5.0)
        )
        self.assertEqual(profile, BehavioralProfile.STRESSOR)

    def test_overwhelmed_from_low_wpm(self):
        profile = diagnose_session_state(
            SessionMetrics(wpm=95.0, pause_ms=1800, filler_count=0, dynamic_db=3.0)
        )
        self.assertEqual(profile, BehavioralProfile.OVERWHELMED)

    def test_drifter_from_high_filler_count_in_normal_band(self):
        profile = diagnose_session_state(
            SessionMetrics(wpm=150.0, pause_ms=700, filler_count=9, dynamic_db=10.0)
        )
        self.assertEqual(profile, BehavioralProfile.DRIFTER)

    def test_master_when_normal_band_low_filler_expressive(self):
        profile = diagnose_session_state(
            SessionMetrics(
                wpm=150.0,
                pause_ms=900,
                filler_count=1,
                dynamic_db=DYNAMIC_DB_HEALTHY_THRESHOLD + 2.0,
            )
        )
        self.assertEqual(profile, BehavioralProfile.MASTER)

    def test_monotone_speaker_is_drifter_not_master(self):
        """The approved fix to the Master-gap: flat speakers fall through to Drifter."""
        profile = diagnose_session_state(
            SessionMetrics(
                wpm=150.0,
                pause_ms=800,
                filler_count=1,
                dynamic_db=DYNAMIC_DB_HEALTHY_THRESHOLD - 1.0,
            )
        )
        self.assertEqual(profile, BehavioralProfile.DRIFTER)

    def test_missing_wpm_defaults_to_drifter(self):
        profile = diagnose_session_state(
            SessionMetrics(wpm=None, filler_count=1, dynamic_db=10.0)
        )
        self.assertEqual(profile, BehavioralProfile.DRIFTER)

    def test_missing_dynamic_db_in_master_slot_falls_to_drifter(self):
        profile = diagnose_session_state(
            SessionMetrics(wpm=150.0, filler_count=0, dynamic_db=None)
        )
        self.assertEqual(profile, BehavioralProfile.DRIFTER)

    def test_missing_filler_count_treated_as_zero(self):
        profile = diagnose_session_state(
            SessionMetrics(
                wpm=150.0,
                filler_count=None,
                dynamic_db=DYNAMIC_DB_HEALTHY_THRESHOLD + 1.0,
            )
        )
        self.assertEqual(profile, BehavioralProfile.MASTER)

    def test_wpm_boundary_170_exact_is_not_stressor(self):
        """Waterfall is strict `> 170` — exact 170 continues down the ladder."""
        profile = diagnose_session_state(
            SessionMetrics(
                wpm=170.0,
                filler_count=0,
                dynamic_db=DYNAMIC_DB_HEALTHY_THRESHOLD + 1.0,
            )
        )
        self.assertEqual(profile, BehavioralProfile.MASTER)

    def test_wpm_boundary_120_exact_is_not_overwhelmed(self):
        """Waterfall is strict `< 120` — exact 120 continues down the ladder."""
        profile = diagnose_session_state(
            SessionMetrics(
                wpm=120.0,
                filler_count=0,
                dynamic_db=DYNAMIC_DB_HEALTHY_THRESHOLD + 1.0,
            )
        )
        self.assertEqual(profile, BehavioralProfile.MASTER)

    def test_filler_boundary_5_exact_is_not_drifter_by_fillers(self):
        """Filler rule is strict `> 5` — exact 5 does not trip Drifter alone."""
        profile = diagnose_session_state(
            SessionMetrics(
                wpm=150.0,
                filler_count=5,
                dynamic_db=DYNAMIC_DB_HEALTHY_THRESHOLD + 1.0,
            )
        )
        self.assertEqual(profile, BehavioralProfile.MASTER)

    def test_dynamic_db_boundary_threshold_exact_is_master(self):
        """Dynamic-db rule is `>= threshold`; exact match qualifies for Master."""
        profile = diagnose_session_state(
            SessionMetrics(
                wpm=150.0,
                filler_count=0,
                dynamic_db=DYNAMIC_DB_HEALTHY_THRESHOLD,
            )
        )
        self.assertEqual(profile, BehavioralProfile.MASTER)

    def test_custom_dynamic_db_threshold_overrides_default(self):
        low_metrics = SessionMetrics(wpm=150.0, filler_count=0, dynamic_db=2.5)
        self.assertEqual(
            diagnose_session_state(low_metrics, dynamic_db_healthy_threshold=2.0),
            BehavioralProfile.MASTER,
        )
        self.assertEqual(
            diagnose_session_state(low_metrics, dynamic_db_healthy_threshold=5.0),
            BehavioralProfile.DRIFTER,
        )


class BuildSessionMetricsTests(unittest.TestCase):
    def test_happy_path(self):
        metrics = build_session_metrics(
            wpm=155.0,
            sniper_metrics={"pause_ms": 800, "dynamic_db": 7.5},
            filler_count=3,
        )
        self.assertEqual(metrics.wpm, 155.0)
        self.assertEqual(metrics.pause_ms, 800.0)
        self.assertEqual(metrics.filler_count, 3)
        self.assertEqual(metrics.dynamic_db, 7.5)

    def test_none_sniper_metrics_yields_none_fields(self):
        metrics = build_session_metrics(wpm=150.0, sniper_metrics=None, filler_count=None)
        self.assertEqual(metrics.wpm, 150.0)
        self.assertIsNone(metrics.pause_ms)
        self.assertIsNone(metrics.filler_count)
        self.assertIsNone(metrics.dynamic_db)

    def test_non_numeric_sniper_values_coerced_to_none(self):
        metrics = build_session_metrics(
            wpm="abc",
            sniper_metrics={"pause_ms": "not-a-number", "dynamic_db": None},
            filler_count="nope",
        )
        self.assertIsNone(metrics.wpm)
        self.assertIsNone(metrics.pause_ms)
        self.assertIsNone(metrics.filler_count)
        self.assertIsNone(metrics.dynamic_db)


class _FakeDB:
    def __init__(self, task_rows=None):
        self._task_rows = task_rows or []
        self.get_calls = []
        self.update_calls = []

    def v2_get_next_active_task_pool_template(self, **kwargs):
        self.get_calls.append(kwargs)
        return list(self._task_rows)

    def v2_update_session(self, session_id, user_id, payload):
        self.update_calls.append((session_id, user_id, dict(payload)))


class DiagnoseAndPersistSessionTests(unittest.TestCase):
    def test_persists_profile_and_task_id_when_template_found(self):
        fake = _FakeDB(task_rows=[{"id": "task-uuid-abc"}])
        profile = diagnose_and_persist_session(
            session_id="sess-1",
            user_id="user-1",
            wpm=185.0,
            sniper_metrics={"pause_ms": 300, "dynamic_db": 5.0},
            filler_count=1,
            db=fake,
        )
        self.assertEqual(profile, BehavioralProfile.STRESSOR)
        self.assertEqual(len(fake.get_calls), 1)
        self.assertEqual(fake.get_calls[0]["target_profile"], "The Stressor")
        self.assertEqual(fake.get_calls[0]["level"], 1)
        self.assertTrue(fake.get_calls[0]["is_behavioral"])
        self.assertEqual(len(fake.update_calls), 1)
        _, _, payload = fake.update_calls[0]
        self.assertEqual(payload["ai_suggested_profile"], "The Stressor")
        self.assertEqual(payload["ai_suggested_task_id"], "task-uuid-abc")

    def test_persists_null_task_id_when_no_template(self):
        fake = _FakeDB(task_rows=[])
        profile = diagnose_and_persist_session(
            session_id="sess-2",
            user_id="user-2",
            wpm=95.0,
            sniper_metrics={"pause_ms": 1800, "dynamic_db": 3.0},
            filler_count=0,
            db=fake,
        )
        self.assertEqual(profile, BehavioralProfile.OVERWHELMED)
        _, _, payload = fake.update_calls[0]
        self.assertEqual(payload["ai_suggested_profile"], "The Overwhelmed")
        self.assertIsNone(payload["ai_suggested_task_id"])


if __name__ == "__main__":
    unittest.main()
