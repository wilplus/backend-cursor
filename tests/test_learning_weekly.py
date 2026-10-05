"""The weekly learning job and the pace (founder 2026-09-30; ML-3, ML-4).

Pins:
  * one snapshot per ISO week, replaced on a second fire (idempotent);
  * a READY cue gets its migration drafted, never merged or promoted;
  * pairs export nothing while door 2 is closed, and the job says why;
  * the pace reads a rate only from two or more readings and never guesses;
  * the cron route is dead without its secret, refuses a wrong one, and
    the founder's route needs the founder.
"""
from __future__ import annotations

import pathlib
import unittest
from datetime import datetime, timezone
from unittest import mock

from services import learning_pace as lp
from services import learning_weekly as lw

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Db:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    def upsert_ledger_snapshot(self, **row):
        self.rows[row["week_start"]] = row
        return row


def _ledger(ready=False, unexported=3, releasable=None):
    return {
        "ledger_version": "learning-ledger-v1",
        "pairs": {"praise_line": {"total": 5, "unexported": unexported, "run_bar": 200, "ready_for_run": False,
                                  **({} if releasable is None else {"releasable": releasable})},
                  "clearer_version": {"total": 0, "unexported": 0}, "exercise_script": {"total": 0, "unexported": 0}},
        "exercise_jar": {"counted": 12},
        "shadow_cues": {"hedging": {"named": 31 if ready else 4, "named_bar": 30, "caught_rate": 0.85 if ready else None,
                                    "caught_bar": 0.8, "clips_measured": 100, "false_alarm_rate": None, "ready": ready}},
        "doors": {"consent": {"open": False}, "dataset_release": {"open": False},
                  "training": {"open": False}, "promotion": {"open": False}},
        "unavailable": [],
    }


class WeeklyTests(unittest.TestCase):
    def test_one_snapshot_per_week_replaced_on_a_second_fire(self):
        db = _Db()
        with mock.patch("services.learning_ledger.ledger", return_value=_ledger()):
            first = lw.run_weekly(db, config=object(), now=datetime(2026, 9, 30, 12, tzinfo=timezone.utc))
            again = lw.run_weekly(db, config=object(), now=datetime(2026, 10, 2, 8, tzinfo=timezone.utc))
        self.assertEqual(first["week_start"], "2026-09-28")
        self.assertEqual(again["week_start"], "2026-09-28")
        self.assertEqual(len(db.rows), 1)
        self.assertTrue(again["stored"])
        self.assertEqual(again["ready_cues"], [])
        self.assertEqual(again["exported"][0]["exported"], 0)
        self.assertIn("door 2 closed", again["exported"][0]["why"])

    def test_a_ready_cue_gets_its_migration_drafted_not_merged(self):
        db = _Db()
        with mock.patch("services.learning_ledger.ledger", return_value=_ledger(ready=True)):
            report = lw.run_weekly(db, config=object(), now=datetime(2026, 9, 30, tzinfo=timezone.utc))
        self.assertEqual(report["ready_cues"], ["hedging"])
        draft = report["migration_drafts"]["hedging"]
        self.assertEqual(draft["file"], "migrations/hedging_is_detected.sql")
        self.assertIn("SET status = 'detected'", draft["sql"])
        self.assertIn("detector_ref = 'verbal_cues:hedging'", draft["sql"])
        self.assertFalse((ROOT / "migrations/hedging_is_detected.sql").exists())

    def test_the_week_starts_on_monday(self):
        self.assertEqual(lw.week_start(datetime(2026, 10, 4, 23, tzinfo=timezone.utc)).isoformat(), "2026-09-28")
        self.assertEqual(lw.week_start(datetime(2026, 10, 5, 0, tzinfo=timezone.utc)).isoformat(), "2026-10-05")


class PaceTests(unittest.TestCase):
    def test_a_rate_needs_two_readings_and_never_guesses(self):
        self.assertIsNone(lp.observed_rate([5]))
        self.assertEqual(lp.observed_rate([2, 5, 11]), 4.5)
        self.assertIsNone(lp.weeks_to_bar(10, 200, None))
        self.assertIsNone(lp.weeks_to_bar(10, 200, 0))
        self.assertEqual(lp.weeks_to_bar(10, 200, 4.5), 43.0)
        self.assertEqual(lp.weeks_to_bar(250, 200, 4.5), 0.0)
        self.assertIsNone(lp.weeks_to_bar(None, 200, 4.5))

    def test_the_pace_rows_read_the_snapshots_oldest_first(self):
        weeks = [_ledger(releasable=0), _ledger(releasable=2)]
        rows = {r["jar"]: r for r in lp.pace(_ledger(releasable=3), weeks)}
        praise = rows["pairs.praise_line"]
        self.assertEqual((praise["current"], praise["bar"], praise["observed_rate"]), (3, 200, 1.5))
        self.assertEqual(praise["weeks_to_bar"], 132.0)
        self.assertEqual(rows["exercise_jar.counted"]["observed_rate"], 0.0)
        cue = rows["shadow_cues.hedging"]
        self.assertEqual((cue["current"], cue["bar"], cue["ready"]), (4, 30, False))


class PairJarTests(unittest.TestCase):
    """Second plan, 2026-10-05: the pair jar counts every releasable pair
    ever written, so a weekly export no longer empties it."""

    def test_an_export_does_not_empty_the_jar(self):
        # Before: 40 waiting. The export takes them all (unexported 0); the
        # releasable count keeps them, and the week's growth is the rate.
        weeks = [_ledger(unexported=40, releasable=40)]
        rows = {r["jar"]: r for r in lp.pace(_ledger(unexported=5, releasable=45), weeks)}
        praise = rows["pairs.praise_line"]
        self.assertEqual((praise["current"], praise["observed_rate"]), (45, 5.0))
        self.assertEqual(praise["weeks_to_bar"], 31.0)

    def test_a_snapshot_from_before_the_count_is_unknown_not_zero(self):
        weeks = [_ledger(unexported=40)]
        rows = {r["jar"]: r for r in lp.pace(_ledger(releasable=45), weeks)}
        self.assertIsNone(rows["pairs.praise_line"]["observed_rate"])


class RouteTests(unittest.TestCase):
    def setUp(self):
        try:
            from app import app
        except Exception as e:  # pragma: no cover
            self.skipTest(f"app import failed: {e}")
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_the_cron_route_is_dead_without_its_secret(self):
        from config import Config
        with mock.patch.object(Config, "LEARNING_WEEKLY_SECRET", ""):
            response = self.client.post("/v2/internal/learning/weekly", json={})
        self.assertEqual(response.status_code, 503)

    def test_the_cron_route_refuses_a_wrong_secret(self):
        from config import Config
        with mock.patch.object(Config, "LEARNING_WEEKLY_SECRET", "right"):
            response = self.client.post("/v2/internal/learning/weekly", json={},
                                        headers={"X-Internal-Secret": "wrong"})
        self.assertEqual(response.status_code, 401)

    def test_the_founder_routes_need_a_token(self):
        for path in ("/v2/admin/learning/ledger", "/v2/research/overview", "/v2/research/golden"):
            self.assertIn(self.client.get(path).status_code, (401, 403), path)
        self.assertIn(self.client.post("/v2/research/golden/confidence/seal").status_code, (401, 403))

    def test_the_gates_are_named_on_every_route(self):
        source = (ROOT / "routes/v2/research.py").read_text()
        for name, gate in (("v2_research_overview", "@require_research_read"),
                           ("v2_research_golden_next", "@require_founder"),
                           ("v2_research_golden_judge", "@require_founder"),
                           ("v2_research_golden_seal", "@require_founder")):
            start = source.index(f"def {name}")
            head = source[source.rindex("@v2_bp.route", 0, start):start]
            self.assertIn(gate, head, name)
        admin = (ROOT / "routes/admin.py").read_text()
        self.assertIn('if request.method != "GET":', admin)


if __name__ == "__main__":
    unittest.main()
