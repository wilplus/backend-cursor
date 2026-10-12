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
from services import model_training as mt
from tests.test_doors_three_and_four import (
    NOW,
    _judged_db,
    _open3,
    _pair,
    _Provider,
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


def _regurgitating_candidate(**kw):
    from services.ml_surface_contracts import active_evaluation_override
    if active_evaluation_override("praise_line"):
        return {"text": WITHDRAWN_PASSAGE}
    return {"text": "nice"}


class FailedCandidateTests(unittest.TestCase):


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
