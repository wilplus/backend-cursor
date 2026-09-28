"""Every refusal of finalize_later_take_review, pinned by its exact reason
before the function was split into named stages (audit W1, 2026-09-28).

A later Take either establishes its durable review state or says precisely
why not; these pin the why for each guard, in the order they are checked.
"""
from __future__ import annotations

import unittest

from services.ideal_text_confirmation import IdealTextUnconfirmedError
from services.take_review import (
    TakeReviewFinalizationError,
    finalize_later_take_review,
)
from tests.test_take_review import _ReviewDb


def _run(database, **over):
    kwargs = {"arc_id": "arc-1", "owner_user_id": "user-1",
              "take_session_id": "take-2", "take_index": 2}
    kwargs.update(over)
    return finalize_later_take_review(database, **kwargs)


class LaterTakeGuardPins(unittest.TestCase):
    def _refused(self, database, reason, **over):
        with self.assertRaises(TakeReviewFinalizationError) as caught:
            _run(database, **over)
        self.assertEqual(caught.exception.reason, reason)
        self.assertEqual(str(caught.exception),
                         f"Take review was not finalized: {reason}")

    def test_the_arguments(self):
        for index in (1, 0, True, "2", None):
            self._refused(_ReviewDb(), "later Take index is invalid",
                          take_index=index)
        for over in ({"arc_id": ""}, {"owner_user_id": None},
                     {"take_session_id": ""}):
            self._refused(_ReviewDb(),
                          "Project, owner, and Take identities are required",
                          **over)

    def test_the_stored_session(self):
        self._refused(_ReviewDb(), "Take is missing", take_session_id="take-9")
        cases = [
            ({"arc_id": "arc-2"}, "Take belongs to a different Project"),
            ({"user_id": "user-2"}, "Take belongs to a different owner"),
            ({"take_index": 3},
             "Take index does not match its stored session"),
            ({"recording_kind": "read"},
             "only a spoken Take has a review version"),
            ({"paired_session_id": "take-1"},
             "only a spoken Take has a review version"),
        ]
        for change, reason in cases:
            database = _ReviewDb()
            database.session.update(change)
            self._refused(database, reason)

    def test_no_confirmed_document_is_the_creation_failure(self):
        database = _ReviewDb()
        database.ideal = {"arc_id": "arc-1", "version": 1, "text": ""}
        with self.assertRaises(IdealTextUnconfirmedError):
            _run(database)

    def test_the_atomic_write(self):
        class _Raises(_ReviewDb):
            def finalize_ideal_text_take(self, *args, **kwargs):
                raise RuntimeError("rpc down")

        self._refused(_Raises(), "atomic database finalizer failed")

        for broken in ({"version": 3}, {"arc_id": "arc-2"},
                       {"take_session_id": "take-9"}, {"take_index": 1},
                       {"text_confirmed": "yes"}, None):
            class _Bad(_ReviewDb):
                def finalize_ideal_text_take(self, *args, _b=broken, **kw):
                    receipt = super().finalize_ideal_text_take(*args, **kw)
                    return None if _b is None else {**receipt, **_b}

            self._refused(_Bad(), "database finalizer returned no confirmation")

    def test_the_fresh_reads(self):
        class _Stale(_ReviewDb):
            reads = 0

            def get_coach_arc_ideal_text(self, arc_id):
                self.reads += 1
                row = super().get_coach_arc_ideal_text(arc_id)
                return {**row, "version": 1} if self.reads > 1 else row

        self._refused(_Stale(), "current review version was not observable")

        class _NoSnapshot(_ReviewDb):
            def get_ideal_text_version(self, arc_id, version):
                return {"text": "  "}

        self._refused(_NoSnapshot(),
                      "historical review snapshot was not observable")

        class _EditLost(_ReviewDb):
            def get_user_ideal_edit(self, arc_id, user_id):
                if self.snapshots:
                    return {"text": "Something else", "version": 2}
                return super().get_user_ideal_edit(arc_id, user_id)

        self._refused(_EditLost(), "owner edit was not preserved")

    def test_a_suggestions_read_failure_writes_an_empty_snapshot(self):
        class _NoSuggestions(_ReviewDb):
            def get_moment_suggestions_by_arc(self, arc_id):
                raise RuntimeError("down")

        database = _NoSuggestions()
        out = _run(database)
        self.assertEqual(database.snapshots[2]["moments"], [])
        self.assertEqual(
            {k: out[k] for k in ("version", "current_version",
                                 "take_session_id", "take_index",
                                 "review_finalized")},
            {"version": 2, "current_version": 2, "take_session_id": "take-2",
             "take_index": 2, "review_finalized": True})


if __name__ == "__main__":
    unittest.main()
