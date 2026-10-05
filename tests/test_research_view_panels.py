"""The research screen's panels carry real data (build plan ML-7, ML DONE
"the research screen shows ... drift with pseudonyms only"; audit ML-7,
ML-DONE-2).

Pins:
  * datasets: the consent-authorised share is the pairs whose speaker's
    yes is in force over all pairs, once door 1 is open; the splits are
    summed from the signed manifests of the releases still standing (a
    voided release counts for nothing); every missing value says why;
  * drift: the weekly learning job stores the PSI 2x2 with its week, and
    the screen reads the newest stored reading, most urgent first;
  * monitors: the confidence readiness checks are read now, the way the
    five-minute cron reads them, without judging the cron's own variables;
    a monitor that cannot be read is named, never shown as ready;
  * nothing on the screen names a person.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from unittest import mock

from services import drift_job
from services import learning_weekly as lw
from services import research_view as rv


class _Config:
    MLC2_TRAINING_SWITCH_ENABLED = True
    MLC2_PAIR_RELEASES_ENABLED = True
    PAIR_RELEASE_SURFACES = frozenset({"exercise_script", "praise_line", "clearer_version"})
    MLC2_TRAINING_ENABLED = False
    MLC2_PROMOTION_ENABLED = False
    MLC2_DATASET_RELEASES_ENABLED = False
    MLC2_CONFIDENCE_CUTOVER_MODE = "founder_canary"
    MLC2_CONFIDENCE_MONITORING_ENABLED = False      # set on the cron service, not the web
    SENTRY_DSN = None


def _ledger_pairs():
    return {
        "praise_line": {"total": 8, "unexported": 2, "releasable": 6, "exposures": 11},
        "clearer_version": {"total": 0, "unexported": 0, "releasable": 0, "exposures": 0},
        "exercise_script": {"total": 4, "unexported": 4, "releasable": 1, "exposures": 9},
        "coach_moment_line": {"total": 3, "unexported": 3, "releasable": 3, "exposures": 3},
        "coach_take_word": {"total": 0, "unexported": 0, "releasable": 0, "exposures": None},
    }


def _release(surface, week, splits, voided=False):
    return {"id": f"rel-{surface}-{week}", "surface": surface, "week_start": week,
            "item_count": sum(splits.values()), "storage_key": f"pair-releases/{surface}/{week}/pairs.jsonl",
            "manifest": {"split_counts": splits, "owners_sha256": "a" * 64, "owner_count": 3},
            "manifest_sha256": "b" * 64, "voided_at": "2026-10-12T06:00:00Z" if voided else None}


HEALTH = {"readiness_contract_version": "mlc2-confidence-canary-readiness-v1",
          "active_consent_policy_count": 1, "valid_active_consent_policy_count": 1,
          # The chain's one consent authority is the training yes (0431).
          "active_training_consent_policy_count": 1,
          "valid_active_training_consent_policy_count": 1,
          "pending_confidence_outbox_count": 0, "failed_confidence_outbox_count": 0,
          "receipt_without_outbox_count": 0, "processed_without_frame_count": 0,
          "blind_assignment_without_packet_count": 0, "revealed_without_judgment_count": 0,
          "oldest_pending_confidence_outbox_at": None, "dataset_creation_enabled": False,
          "training_enabled": False, "promotion_enabled": False}
RING = {"ring_readiness_contract_version": "rings-confidence-readiness-v1",
        "confidence_ring_row_present": True, "confidence_ring_row_killed": False,
        "confidence_ring_row_one_way": True, "canonical_take_rows_row_present": True,
        "canonical_take_rows_row_killed": False, "eligible_principal_count": 1,
        "eligible_bundled_consent_grant_count": 1, "eligible_training_consent_grant_count": 1,
        "noneligible_producer_receipt_count": 0,
        "noneligible_canonical_event_count": 0, "eligible_producer_receipt_count": 4}

DRIFT = {"version": "frozen_v1", "minted": 0, "note": None, "worst": "PIPELINE_CHANGED",
         "sessions_by_dimension": {"wpm": 60, "fillers": 58},
         "dimensions": {
             "fillers": {"psi": 0.02, "psi_band": "STABLE", "n_sessions": 58,
                         "chart_signal": "IN_CONTROL", "triage": "HEALTHY"},
             "wpm": {"psi": 0.04, "psi_band": "STABLE", "n_sessions": 60,
                     "chart_signal": "OUT_OF_CONTROL_HIGH", "triage": "PIPELINE_CHANGED"}}}


class _Db:
    def __init__(self, releases=(), snapshots=(), monitor_down=False):
        self.releases = list(releases)
        self.snapshots = list(snapshots)
        self.monitor_down = monitor_down

    def list_pair_releases(self, limit=20):
        return self.releases[:limit]

    def list_ledger_snapshots(self, limit=8):
        return self.snapshots[:limit]

    def get_mlc2_confidence_canary_readiness(self):
        if self.monitor_down:
            raise RuntimeError("rpc down")
        return HEALTH

    def get_ring_confidence_readiness(self):
        return RING

    def get_runtime_config(self, key):
        return None

    def list_annotation_export_runs(self, limit=20):
        return []

    def list_dataset_exclusions(self):
        return []

    def get_confidence_label_corpus(self, limit=5000):
        return []

    def list_evaluation_reports(self, limit=20):
        return []

    def list_fine_tune_runs(self, status=None, limit=20):
        return []

    def list_model_promotions(self, limit=20):
        return []


def _overview(db):
    ledger = {"pairs": _ledger_pairs(), "doors": {
        "consent": {"open": True}, "dataset_release": {
            "open": True, "surfaces": ["clearer_version", "exercise_script", "praise_line"]},
        "training": {"open": False}, "promotion": {"open": False}}}
    with mock.patch("services.learning_ledger.ledger", return_value=ledger), \
         mock.patch("services.golden_set.counts", return_value={"count": 0}), \
         mock.patch("services.coach_video_storage.coach_videos_use_r2", return_value=True):
        return rv.overview(db, config=_Config())


class DatasetTests(unittest.TestCase):
    def test_the_share_and_the_splits_are_computed(self):
        out = _overview(_Db(releases=[
            _release("praise_line", "2026-10-12", {"train": 4, "validation": 1, "test": 1}),
            _release("praise_line", "2026-10-05", {"train": 2, "validation": 0, "test": 1}),
            _release("praise_line", "2026-09-28", {"train": 9, "validation": 9, "test": 9}, voided=True),
        ]))
        praise = out["datasets"]["praise_line"]
        self.assertEqual(praise["consent_authorised_share"], 0.75)
        self.assertIsNone(praise["consent_note"])
        self.assertEqual(praise["splits"], {"train": 6, "validation": 1, "test": 2})
        self.assertIsNone(praise["splits_note"])
        self.assertEqual(praise["exposures"], 11)
        self.assertEqual(len(praise["releases"]), 3)
        exercise = out["datasets"]["exercise_script"]
        self.assertEqual(exercise["consent_authorised_share"], 0.25)
        self.assertIsNone(exercise["splits"])
        self.assertIn("no release yet", exercise["splits_note"])
        empty = out["datasets"]["clearer_version"]
        self.assertIsNone(empty["consent_authorised_share"])
        self.assertEqual(empty["consent_note"], "no pair on this surface yet")
        held = out["datasets"]["coach_moment_line"]
        self.assertEqual(held["consent_authorised_share"], 1.0)
        self.assertIn("not open for this surface", held["splits_note"])

    def test_with_door_2_open_and_no_release_the_exports_note_says_so(self):
        note = _overview(_Db())["exports"]["note"]
        self.assertIn("door 2 is open", note)
        self.assertNotIn("door 2 closed", note)


class DriftTests(unittest.TestCase):
    def test_the_newest_stored_reading_most_urgent_first(self):
        out = _overview(_Db(snapshots=[
            {"week_start": "2026-10-12", "snapshot": {"pairs": {}}},          # no reading
            {"week_start": "2026-10-05", "snapshot": {"drift": DRIFT}},
            {"week_start": "2026-09-28", "snapshot": {"drift": {**DRIFT, "worst": "HEALTHY"}}},
        ]))["drift"]
        self.assertEqual(out["week_start"], "2026-10-05")
        self.assertEqual(out["worst"], "PIPELINE_CHANGED")
        self.assertEqual([d["dimension"] for d in out["dimensions"]], ["wpm", "fillers"])
        self.assertEqual(out["dimensions"][0]["chart_signal"], "OUT_OF_CONTROL_HIGH")
        self.assertEqual(out["sessions_by_dimension"], {"wpm": 60, "fillers": 58})

    def test_no_stored_reading_is_said_in_words(self):
        out = _overview(_Db())["drift"]
        self.assertEqual(out["dimensions"], [])
        self.assertIn("no stored week carries a drift reading yet", out["note"])


class MonitorTests(unittest.TestCase):
    def test_the_monitor_is_read_now_without_judging_the_crons_variables(self):
        out = _overview(_Db())
        canary = out["monitors"]["confidence_canary"]
        # The web service has no monitoring switch or Sentry here: those are
        # the cron's, so they are not blockers on this screen.
        self.assertTrue(canary["ready"], canary)
        self.assertEqual(canary["blocker_codes"], [])
        self.assertEqual(canary["cutover_mode"], "founder_canary")
        self.assertNotIn("monitors", out["unavailable"])

    def test_a_real_blocker_shows(self):
        db = _Db()
        db.get_ring_confidence_readiness = lambda: {**RING, "confidence_ring_row_killed": True}
        canary = _overview(db)["monitors"]["confidence_canary"]
        self.assertFalse(canary["ready"])
        self.assertIn("confidence_ring_row_killed", canary["blocker_codes"])

    def test_a_monitor_that_cannot_be_read_is_named_never_ready(self):
        out = _overview(_Db(monitor_down=True))
        self.assertIn("monitors", out["unavailable"])
        self.assertIsNone(out["monitors"]["confidence_canary"])

    def test_nothing_on_the_screen_names_a_person(self):
        text = json.dumps(_overview(_Db(releases=[
            _release("praise_line", "2026-10-12", {"train": 1, "validation": 0, "test": 0})],
            snapshots=[{"week_start": "2026-10-05", "snapshot": {"drift": DRIFT}}])))
        for leak in ("owner_principal", "user_id", "@", "acquisition_principal_id"):
            self.assertNotIn(leak, text)


class WeeklyDriftTests(unittest.TestCase):
    def test_the_weekly_job_stores_the_drift_reading_with_its_week(self):
        class _Weekly:
            def upsert_ledger_snapshot(self, **row):
                self.row = row
                return row

            def refresh_feedback_pair_consent(self, surfaces):
                return {"refreshed": 0}

            def list_voided_unpurged_pair_releases(self):
                return []
        db = _Weekly()
        ledger = {"ledger_version": "v", "pairs": {}, "shadow_cues": {}, "doors": {}, "unavailable": []}
        with mock.patch("services.learning_ledger.ledger", return_value=ledger), \
             mock.patch("services.drift_job.run_weekly", return_value=DRIFT) as drift, \
             mock.patch("services.learning_weekly._training_pass", return_value={}):
            out = lw.run_weekly(db, config=_Config(), now=datetime(2026, 10, 12, 6, tzinfo=timezone.utc))
        self.assertIs(drift.call_args.kwargs["database"], db)
        self.assertEqual(db.row["snapshot"]["drift"]["worst"], "PIPELINE_CHANGED")
        self.assertEqual(out["drift"]["worst"], "PIPELINE_CHANGED")

    def test_a_drift_fault_never_stops_the_week(self):
        with mock.patch("services.drift_job.run_weekly", side_effect=RuntimeError("boom")):
            self.assertEqual(lw._drift_pass(object()), {"unavailable": "boom"})

    def test_the_drift_run_reads_the_database_it_is_given(self):
        class _Quiet:
            def get_dimension_evaluations_since(self, weeks, limit=50000):
                self.weeks = weeks
                return []
        quiet = _Quiet()
        report = drift_job.run_weekly(weeks=4, database=quiet)
        self.assertEqual(quiet.weeks, drift_job.REFERENCE_WEEKS)
        self.assertIn("no evaluations yet", report["note"])
        # A database that cannot answer is a note, never a raise.
        self.assertIn("read failed", drift_job.run_weekly(database=object())["note"])


if __name__ == "__main__":
    unittest.main()
