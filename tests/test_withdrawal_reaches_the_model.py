"""
STORY    As a speaker who withdraws, I want the next model trained without my
         data, so that my withdrawal reaches the model. (Critical path:
         consent withdrawn -> the thing stops.)
OUTCOME
  O1  A promotion reads the withdrawal live: a passing report promotes while
      everyone's yes stands, and the same report is refused as STALE the
      moment a speaker withdraws (no weekly sweep in between); nothing is
      served.
  O2  A freshness that cannot be read refuses the promotion; nothing served.
  O3  A candidate that reproduces a withdrawn speaker's text is failed for
      good and never promoted, whatever report is offered.
  O4  The retraining is the NEXT run, built only from still-releasable pairs
      no run trained on: the withdrawn speaker's pairs stay out.
PROVES   O1 -> test_a_withdrawal_makes_a_passing_report_stale_at_once
         O2 -> test_an_unreadable_freshness_refuses_the_promotion
         O3 -> test_a_regurgitating_candidate_is_failed_and_never_promoted
         O4 -> test_the_retraining_is_the_next_run_on_never_trained_pairs
WHY      Counsel 2026-10-01; audit DOOR-4-WITHDRAWN and DOOR-3-RETRAIN.

Python seam (services/model_training.py, services/model_promotion.py) over
the shared fake in tests/doors_fakes.py.
"""
from __future__ import annotations

import unittest
from unittest import mock

from services import golden_set as gs
from services import model_promotion as mp
from services import model_training as mt
from services.ml_surface_contracts import locked_prompt_hash
from tests.doors_fakes import (
    NOW,
    _judged_db,
    _open3,
    _open4,
    _pair,
    _Provider,
)

CANDIDATE = "ft:gpt-4.1-mini:willab:praise:abc"
WITHDRAWN_PASSAGE = "we trained on this sentence about quarterly revenue numbers today in the room"


def _trained(i, owner):
    """A pair run-1 learned from: texts unlike the golden moments'."""
    row = _pair(1000 + i, owner=owner,
                passage_text=f"{WITHDRAWN_PASSAGE} {i}" if owner == "w-1" else
                f"another speaker said line {i} about the launch plan for spring",
                final_text=f"a coach line {i} written by hand for this speaker today",
                trained_run_id="run-1")
    return row


def _world():
    """A sealed golden set and a succeeded run-1 that learned from ten pairs
    of two owners, w-1 and w-2, both still saying yes."""
    db = _judged_db()
    gs.seal(db, surface="praise_line", judge="founder@w.com")
    db.pairs += [_trained(i, "w-1" if i < 5 else "w-2") for i in range(10)]
    db.runs.append({"id": "run-1", "surface": "praise_line", "status": "succeeded",
                    "candidate_model": CANDIDATE, "files_deleted_at": "t",
                    "finished_at": "2026-10-05T07:00:00+00:00"})
    return db


def _regurgitating_candidate(**kw):
    from services.ml_surface_contracts import active_evaluation_override
    if active_evaluation_override("praise_line"):
        return {"text": WITHDRAWN_PASSAGE}
    return {"text": "nice"}


def _passing_report(db):
    """A passing report on run-1, written against the withdrawals of now."""
    return db.insert_evaluation_report(
        surface="praise_line", candidate_model=CANDIDATE, passed=True,
        run_id="run-1", prompt_lock_sha256=locked_prompt_hash("praise_line"),
        report={"regurgitation": {
            "ok": True,
            "withdrawn_owners_sha256": mt.withdrawn_basis(db, "run-1")["owners_sha256"]}})


def _promote(db, report):
    return mp.promote(db, surface="praise_line", candidate_model=CANDIDATE,
                      evaluation_report_id=report["id"], by="founder@w.com",
                      config=_open4("praise_line"), now=NOW)


class WithdrawalReachesTheModelTests(unittest.TestCase):

    def test_a_withdrawal_makes_a_passing_report_stale_at_once(self):
        db = _world()
        report = _passing_report(db)
        self.assertEqual(_promote(db, report)["model"], CANDIDATE)
        db.runtime.clear()
        db.active = {"w-2"}                      # w-1 withdraws, nothing else runs
        with self.assertRaises(mp.PromotionRefusal) as refused:
            _promote(db, report)
        self.assertEqual(refused.exception.code, "REPORT_STALE")
        self.assertEqual(db.runtime, {})

    def test_an_unreadable_freshness_refuses_the_promotion(self):
        db = _world()
        report = _passing_report(db)
        with mock.patch.object(db, "list_trained_pairs", side_effect=RuntimeError("db down")), \
                self.assertRaises(mp.PromotionRefusal) as refused:
            _promote(db, report)
        self.assertEqual(refused.exception.code, "REPORT_FRESHNESS_UNKNOWN")
        self.assertEqual(db.runtime, {})

    def test_a_regurgitating_candidate_is_failed_and_never_promoted(self):
        db = _world()
        db.active = {"w-2"}
        with mock.patch("services.coach_request_drafts.compose_draft",
                        side_effect=_regurgitating_candidate):
            (row,) = mt.reevaluate_stale(db, config=_open3("praise_line"))
        self.assertTrue(row["run_failed"])
        self.assertEqual(db.runs[0]["status"], "failed")
        # Never evaluated again, and no report, however fresh, promotes it.
        self.assertEqual(mt.reevaluate_stale(db, config=_open3("praise_line")), [])
        with self.assertRaises(mp.PromotionRefusal) as refused:
            _promote(db, _passing_report(db))
        self.assertEqual(refused.exception.code, "RUN_FAILED")
        self.assertEqual(db.runtime, {})

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


if __name__ == "__main__":
    unittest.main()
