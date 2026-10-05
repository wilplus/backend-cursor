"""A withdrawal reaches the model (counsel 2026-10-01; audit DOOR-4-WITHDRAWN
and DOOR-3-RETRAIN).

Pins:
  * the withdrawal basis is read live: an owner whose yes is no longer in
    force, or whose pairs went not-releasable, counts at once, not at the
    next weekly sweep;
  * a report keeps the basis it checked; a withdrawal after the evaluation
    makes it STALE, promotion refuses it, and the weekly pass evaluates the
    candidate again, after which a fresh, passing report may promote;
  * a candidate that fails the regurgitation check is marked failed for
    good: never promoted (whatever report is offered), never evaluated
    again; a served candidate that fails is named loudly;
  * "retrained without the withdrawn pairs" is the NEXT run: it is built
    only from still-releasable pairs no run has trained on (a pair trains
    once), so the withdrawn pairs and the failed run's pairs stay out;
  * a freshness that cannot be read refuses the promotion.
"""
from __future__ import annotations

import unittest
from unittest import mock

from services import golden_set as gs
from services import model_promotion as mp
from services import model_training as mt
from tests.test_doors_three_and_four import (
    NOW, _Provider, _judged_db, _open3, _open4, _pair,
)

CANDIDATE = "ft:gpt-4.1-mini:willab:praise:abc"
WITHDRAWN_PASSAGE = "we trained on this sentence about quarterly revenue numbers today in the room"


def _trained(i, owner, **over):
    """A pair run-1 learned from: texts unlike the golden moments'."""
    row = _pair(1000 + i, owner=owner,
                passage_text=f"{WITHDRAWN_PASSAGE} {i}" if owner == "w-1" else
                f"another speaker said line {i} about the launch plan for spring",
                final_text=f"a coach line {i} written by hand for this speaker today",
                trained_run_id="run-1")
    row.update(over)
    return row


def _world():
    """A sealed golden set, a succeeded run-1 that learned from ten pairs of
    two owners, and a report on it written while both still said yes."""
    db = _judged_db()
    gs.seal(db, surface="praise_line", judge="founder@w.com")
    db.pairs += [_trained(i, "w-1" if i < 5 else "w-2") for i in range(10)]
    db.runs.append({"id": "run-1", "surface": "praise_line", "status": "succeeded",
                    "candidate_model": CANDIDATE, "files_deleted_at": "t",
                    "finished_at": "2026-10-05T07:00:00+00:00"})
    return db


def _good_candidate(**kw):
    from services.ml_surface_contracts import active_evaluation_override
    if active_evaluation_override("praise_line"):
        i = kw["passage"].split()[5]
        return {"text": f"you held the pause before the number {i}"}
    return {"text": "nice"}


def _regurgitating_candidate(**kw):
    from services.ml_surface_contracts import active_evaluation_override
    if active_evaluation_override("praise_line"):
        return {"text": WITHDRAWN_PASSAGE}
    return {"text": "nice"}


def _evaluate_now(db, compose=_good_candidate):
    with mock.patch("services.coach_request_drafts.compose_draft", side_effect=compose):
        return mt._evaluate(db, db.runs[0], CANDIDATE, _open3("praise_line"))


def _promote(db, report_id):
    return mp.promote(db, surface="praise_line", candidate_model=CANDIDATE,
                      evaluation_report_id=report_id, by="founder", config=_open4("praise_line"),
                      now=NOW)


class BasisTests(unittest.TestCase):
    def test_the_basis_is_read_live_and_names_no_one(self):
        db = _world()
        clean = mt.withdrawn_basis(db, "run-1")
        self.assertEqual((clean["owners"], clean["withdrawn_texts"]), (0, []))
        self.assertEqual(len(clean["trained_texts"]), 20)
        # w-1 withdraws: the view says so at once, before any weekly sweep.
        db.active = {"w-2"}
        gone = mt.withdrawn_basis(db, "run-1")
        self.assertEqual(gone["owners"], 1)
        self.assertEqual(len(gone["withdrawn_texts"]), 10)
        self.assertNotEqual(gone["owners_sha256"], clean["owners_sha256"])
        self.assertNotIn("w-1", gone["owners_sha256"])
        # A deletion request flips the pairs not releasable: that counts too.
        db.active = None
        for pair in db.pairs:
            if pair.get("owner_principal_id") == "w-2" and pair.get("trained_run_id"):
                pair["releasable"] = False
        self.assertEqual(mt.withdrawn_basis(db, "run-1")["owners"], 1)


class StaleReportTests(unittest.TestCase):
    def test_a_withdrawal_after_the_evaluation_makes_the_report_stale(self):
        db = _world()
        first = _evaluate_now(db)
        self.assertTrue(first["passed"])
        report = db.reports[-1]
        self.assertEqual(report["report"]["regurgitation"]["withdrawn_owners"], 0)
        # Fresh: it promotes.
        self.assertEqual(_promote(db, first["report_id"])["model"], CANDIDATE)
        mp.kill(db, surface="praise_line", by="founder", reason="test", now=NOW)
        # w-1 withdraws after the report: the same report is now refused.
        db.active = {"w-2"}
        with self.assertRaises(mp.PromotionRefusal) as stale:
            _promote(db, first["report_id"])
        self.assertEqual(stale.exception.code, "REPORT_STALE")

    def test_the_weekly_pass_evaluates_again_and_a_fresh_pass_may_promote(self):
        db = _world()
        first = _evaluate_now(db)
        db.active = {"w-2"}
        with mock.patch("services.coach_request_drafts.compose_draft", side_effect=_good_candidate):
            rows = mt.reevaluate_stale(db, config=_open3("praise_line"))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["reevaluated"] and rows[0]["passed"])
        second = rows[0]["report_id"]
        self.assertNotEqual(second, first["report_id"])
        self.assertEqual(db.reports[-1]["report"]["regurgitation"]["withdrawn_owners"], 1)
        self.assertEqual(db.reports[-1]["report"]["regurgitation"]["withdrawn_texts"], 10)
        self.assertEqual(_promote(db, second)["model"], CANDIDATE)
        # Fresh now: the next pass leaves it alone.
        with mock.patch("services.coach_request_drafts.compose_draft") as compose:
            self.assertEqual(mt.reevaluate_stale(db, config=_open3("praise_line")), [])
        compose.assert_not_called()

    def test_a_report_from_before_the_basis_is_fresh_only_while_nobody_withdrew(self):
        self.assertTrue(mt.report_is_fresh({"report": {"regurgitation": {}}}, {"owners": 0}))
        self.assertFalse(mt.report_is_fresh({"report": {}}, {"owners": 1, "owners_sha256": "x"}))
        self.assertFalse(mt.report_is_fresh(None, {"owners": 2}))

    def test_a_freshness_that_cannot_be_read_refuses(self):
        db = _world()
        first = _evaluate_now(db)

        def down(_owners):
            raise RuntimeError("the consent view is down")
        db.list_active_training_grants = down
        with self.assertRaises(mp.PromotionRefusal) as unknown:
            _promote(db, first["report_id"])
        self.assertEqual(unknown.exception.code, "REPORT_FRESHNESS_UNKNOWN")


class FailedCandidateTests(unittest.TestCase):
    def test_a_regurgitating_candidate_fails_for_good(self):
        db = _world()
        good = _evaluate_now(db)
        db.active = {"w-2"}                      # w-1 withdraws
        with mock.patch("services.coach_request_drafts.compose_draft",
                        side_effect=_regurgitating_candidate):
            rows = mt.reevaluate_stale(db, config=_open3("praise_line"))
        self.assertTrue(rows[0]["run_failed"])
        self.assertIn("never promoted", rows[0]["why"])
        self.assertNotIn("served_now", rows[0])
        run = db.runs[0]
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["failure"], mt.REGURGITATION_FAILURE)
        self.assertEqual(run["finished_at"], "2026-10-05T07:00:00+00:00")  # the job's own end
        # Never promoted, not even from the earlier passing report, and not
        # if the speaker comes back.
        db.active = None
        for report_id in (good["report_id"], rows[0]["report_id"]):
            with self.assertRaises(mp.PromotionRefusal) as refused:
                _promote(db, report_id)
            self.assertIn(refused.exception.code, ("RUN_FAILED", "REPORT_FAILED"))
        with self.assertRaises(mp.PromotionRefusal) as failed_run:
            _promote(db, good["report_id"])
        self.assertEqual(failed_run.exception.code, "RUN_FAILED")
        # Never evaluated again.
        with mock.patch("services.coach_request_drafts.compose_draft") as compose:
            self.assertEqual(mt.reevaluate_stale(db, config=_open3("praise_line")), [])
        compose.assert_not_called()

    def test_a_served_candidate_that_fails_is_named_loudly(self):
        db = _world()
        first = _evaluate_now(db)
        _promote(db, first["report_id"])
        db.active = {"w-2"}
        with mock.patch("services.coach_request_drafts.compose_draft",
                        side_effect=_regurgitating_candidate):
            rows = mt.reevaluate_stale(db, config=_open3("praise_line"))
        self.assertTrue(rows[0]["served_now"])
        self.assertIn("kill", rows[0]["why"])
        # Nothing here kills it by itself: that stays the founder's hand.
        self.assertEqual(db.runtime["openai_surface_model_praise_line"], CANDIDATE)

    def test_the_retraining_is_the_next_run_on_never_trained_pairs(self):
        db = _world()
        db.active = {"w-2"}
        with mock.patch("services.coach_request_drafts.compose_draft",
                        side_effect=_regurgitating_candidate):
            mt.reevaluate_stale(db, config=_open3("praise_line"))
        self.assertEqual(db.runs[0]["status"], "failed")
        # Two hundred and ten new pairs arrive; ten belong to w-1, who said no.
        fresh = [_pair(2000 + i, owner=f"n-{i % 40}") for i in range(200)]
        fresh += [_pair(3000 + i, owner="w-1", releasable=False) for i in range(10)]
        db.pairs += fresh
        provider = _Provider()
        out = mt.start_run(db, provider, surface="praise_line", config=_open3("praise_line"), now=NOW)
        self.assertTrue(out["started"], out)
        run_id, marked = db.marked[-1]
        self.assertNotEqual(run_id, "run-1")
        # The failed run's pairs never train again (a pair trains once), and
        # the withdrawn speaker's new pairs never train at all.
        failed_runs_pairs = {f"pair-{1000 + i}" for i in range(10)}
        withdrawn_pairs = {f"pair-{3000 + i}" for i in range(10)}
        self.assertEqual(failed_runs_pairs & set(marked), set())
        self.assertEqual(withdrawn_pairs & set(marked), set())
        self.assertEqual(len([p for p in db.pairs if p.get("trained_run_id") == "run-1"]), 10)
        self.assertTrue(any(p.startswith("pair-2") for p in marked))


class WeeklyPassTests(unittest.TestCase):
    def test_the_pass_reports_the_reevaluation_and_does_not_double_up(self):
        db = _world()
        db.runs[0]["status"] = "running"
        db.runs[0]["openai_job_id"] = "job-1"
        db.runs[0]["openai_file_id"] = "file-1"
        db.runs[0]["files_deleted_at"] = None
        provider = _Provider(status="succeeded")
        provider.model = CANDIDATE
        with mock.patch("services.coach_request_drafts.compose_draft", side_effect=_good_candidate):
            out = mt.run_training_pass(db, config=_open3("praise_line"), provider=provider, now=NOW)
        self.assertTrue(out["polled"][0]["evaluation"]["passed"])
        # The poll's fresh report stands: no second evaluation in the pass.
        self.assertEqual(out["reevaluated"], [])
        self.assertEqual(len(db.reports), 1)


if __name__ == "__main__":
    unittest.main()
