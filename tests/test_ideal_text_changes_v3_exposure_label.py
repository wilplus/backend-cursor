"""The stored record of a V3 Take says V3, and lists what was shown.

A-2 (major) and A-1's write half, audit 2026-09-22.

`_claim_or_filter` writes one `take_feedback_exposure` row per Take. Since
the V3 cutover that row has been wrong in two ways at once, on every V3
Take:

  * `policy_version` is V2's `take-feedback-manager-v2`, because the
    constant is imported from `take_feedback_manager` and never varies;
  * `candidate_set` is `self.feedback_exposure`, the snapshot taken up in
    `_select()` — the V2 candidate pool, computed BEFORE
    `_first_client_feedback` replaced the served rows. V2 ids look like
    `confident-voice:{sid}`; V3 ids look like `relative-confidence:{take}:
    {snippet}`. They share no identity, so the stored pool never contains
    one id the speaker actually saw.

That is A-2. It is also the whole of A-1's WRITE half for a Take whose
canonical lineage could not be frozen: this row is the durable record that
a bookmark was served, and a durable record listing the wrong candidates is
not a record of anything. Fixing the label fixes both.

Nothing here refuses to serve. A-1's SERVE half — standing down when the
lineage is missing — reverses the founder's 2026-09-20 decision and is
explicitly sequenced after this by the order of work ("A-1's write first
and only then the tightening of its serve"). It is not in this change.
"""
from __future__ import annotations

import unittest

ARC = "11111111-1111-4111-8111-111111111111"
TAKE = "22222222-2222-4222-8222-222222222222"
SNIPPET = "33333333-3333-4333-8333-333333333333"
DOC = "Our approach is different, and that matters."


def _v3_row(snippet_id: str = SNIPPET) -> dict:
    """One served V3 Confident Voice row, in the shape the service emits."""
    return {
        "id": f"relative-confidence:{TAKE}:{snippet_id}",
        "kind": "moment",
        "source": "mlc3_service",
        "feedback_family": "confident_voice",
        "snippet_id": snippet_id,
        "span": {"start": 0, "end": 12},
    }


def _v2_pool_row() -> dict:
    """A row from the V2 candidate pool, which is what gets stored today."""
    return {
        "id": f"confident-voice:{SNIPPET}",
        "kind": "moment",
        "source": "acoustic",
        "feedback_family": "confident_voice",
        "snippet_id": SNIPPET,
        "span": {"start": 0, "end": 12},
    }


class _Db:
    """Only the reads and the one write `_claim_or_filter` makes."""

    def __init__(self):
        self.exposures: list[dict] = []
        self.claimed: dict | None = None

    def v2_get_session_by_id(self, sid):
        return {"id": TAKE, "take_index": 1} if sid == TAKE else {}

    def insert_take_feedback_exposure(self, **kwargs):
        self.exposures.append(kwargs)
        return True

    def __getattr__(self, name):
        def _missing(*a, **k):
            raise AttributeError(f"_Db has no {name}")
        return _missing


def _run(db):
    from services.degradation import DegradationLog
    from services.ideal_text_changes import ChangesDeps, _ChangesRun
    return _ChangesRun(
        ARC, DOC, "user-1", TAKE, 1,
        ChangesDeps(
            database=db,
            first_client_repository=None,
            applied_map=lambda ids: {},
            playback_map=lambda ids: {},
            previous_spoken_session=lambda arc_id, sid: None,
            locked_parts=lambda arc_id, user_id, text: [],
            with_evidence_coordinates=lambda rows, **k: rows,
            record_arms=lambda result, sid, uid: None,
        ),
        DegradationLog("ideal_text"),
    )


def _a_fresh_v3_take(db):
    """A Take with no frozen set yet, served by V3. The claim path."""
    run = _run(db)
    run.arm_sid = TAKE
    run.take_contract_on = True
    run.feedback_set = None
    run.changes = [_v3_row()]
    run.styles = []
    # The snapshot as it stands today: taken in `_select()`, from V2's pool,
    # long before V3 replaced the rows.
    run.feedback_exposure = [_v2_pool_row()]
    run.v3_replaced_changes = True
    return run


class TheStoredRecordNamesThePolicyThatServed(unittest.TestCase):

    def _claim(self, monkey_claim):
        """Run the claim stage with the freeze stubbed to accept."""
        from unittest.mock import patch

        db = _Db()
        run = _a_fresh_v3_take(db)
        with patch("services.take_feedback_set.claim_feedback_set",
                   side_effect=monkey_claim):
            run._claim_or_filter()
        return db, run

    def test_v3_served_take_records_v3_policy_and_matching_candidate_set(self):
        """The named regression test for A-2."""
        from services.take_feedback_policy_v3 import (
            POLICY_VERSION as V3_POLICY,
        )

        def _accept(db, **kwargs):
            # The freeze accepts exactly the rows it was handed.
            return {"selected_keys": list(kwargs["changes"])}

        db, run = self._claim(_accept)

        self.assertEqual(len(db.exposures), 1, "no exposure row was written")
        row = db.exposures[0]

        self.assertEqual(
            row["policy_version"], V3_POLICY,
            "a V3-served Take stored V2's policy version",
        )

        stored = {str(c.get("id") or "") for c in row["candidate_set"]}
        selected = {str(k.get("id") or "") for k in row["selected_keys"]}
        self.assertTrue(selected, "nothing was recorded as selected")
        self.assertTrue(
            selected <= stored,
            f"selected ids {selected - stored} are in no stored candidate",
        )

    def test_every_served_v3_row_has_a_persisted_exposure(self):
        """A-1's write half, from the other end.

        Whatever reached the speaker must be findable afterwards. This is
        the record that makes a served bookmark accountable when the
        canonical lineage could not be frozen.
        """
        def _accept(db, **kwargs):
            return {"selected_keys": list(kwargs["changes"])}

        db, run = self._claim(_accept)
        row = db.exposures[0]
        stored = {str(c.get("id") or "") for c in row["candidate_set"]}

        for served in run.changes:
            with self.subTest(row=served["id"]):
                self.assertIn(
                    str(served["id"]), stored,
                    "a row the speaker saw is in no persisted record",
                )

    def test_a_take_v3_did_not_serve_still_records_v2(self):
        """The other half of the same rule — do not over-correct.

        When V3 does not apply, the Take really was served by V2 and the
        stored row must keep saying so.
        """
        from unittest.mock import patch

        from services.take_feedback_manager import POLICY_VERSION as V2_POLICY

        db = _Db()
        run = _run(db)
        run.arm_sid = TAKE
        run.take_contract_on = True
        run.feedback_set = None
        v2 = _v2_pool_row()
        run.changes = [v2]
        run.styles = []
        run.feedback_exposure = [v2]
        run.v3_replaced_changes = False

        with patch("services.take_feedback_set.claim_feedback_set",
                   side_effect=lambda db, **k: {
                       "selected_keys": list(k["changes"])}):
            run._claim_or_filter()

        self.assertEqual(db.exposures[0]["policy_version"], V2_POLICY)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
