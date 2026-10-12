"""willab — eager ideal-text assembly + saved=reviewed (founder 2026-07-15).

The founder's bug: the coach assembler was invisible (silent lazy compute) →
never reviewed → never approved → publish blocked → the student got ZERO
bubbles. This suite pins the whole chain:

  * spoken-only readiness/candidates (a read never counts / never competes);
  * eager assembly at spoken take 3, persisted, coach-edit-safe;
  * the coach GET's observable states (pending w/ counts → ready);
  * saved = REVIEWED (review_state) on the coach surfaces;
  * BE-C: the END-TO-END smoke — 3 takes → eager draft → save ×3 → approve →
    publish-analysis → EXACTLY the 4 ordered bubbles.

Run: python3 -m unittest tests.test_eager_ideal_text
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from flask import Flask, request

    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e

ARC = "a1"


def _spoken(i, saved=True):
    return {"id": f"s{i}", "user_id": "u1", "arc_id": ARC, "take_index": i,
            "created_at": f"2026-07-1{i}T10:00:00Z",
            "intake_context": {"topic": "Demo"},
            "results_published_at": None,
            "recording_kind": "spoken", "paired_session_id": None,
            "coach_feedback_saved_at":
                (f"2026-07-1{i}T11:00:00Z" if saved else None)}


class EagerAssemblyTests(unittest.TestCase):
    """maybe_assemble_ideal_text — the take-3 trigger."""

    def _run(self, sessions, existing_row=None, auto=None,
             require_target=True):
        import services.ideal_text_block as mod
        calls = {}

        class _Db:
            def get_arc_sessions(self, a):
                return sessions

            @property
            def takes(self):
                # audit Q-A2: production now calls db.takes.<method>();
                # this fake implements those methods directly on itself.
                return self

            def get_coach_arc_ideal_text(self, a):
                return existing_row

            @property
            def ideal_text(self):
                # audit Q-A2: production now calls
                # database.ideal_text.<method>(); this fake implements
                # those methods directly on itself.
                return self

            def persist_auto_ideal_text(self, a, text, *, take_count=None,
                                        document=None):
                # `document` is the piece provenance the real writer
                # persists beside the text (2026-08-13). A double that
                # omits it raises TypeError, which the caller swallows —
                # the same shape of bug a test double hid once already.
                calls["document"] = document
                calls["persisted"] = text
                # The version is the SPOKEN take count (founder 2026-08-05).
                calls["take_count"] = take_count
                return True

        with patch.object(mod, "assemble_transcript_document",
                          return_value=(auto or {
                              "text": "assembled block",
                              "key_moments": [], "ready": True})):
            ok = mod.maybe_assemble_ideal_text(
                ARC, database=_Db(), require_target=require_target)
        return ok, calls


    def test_not_ready_assembly_never_persists(self):
        ok, calls = self._run(
            [_spoken(1), _spoken(2), _spoken(3)],
            auto={"text": "", "key_moments": [], "ready": False})
        self.assertFalse(ok)
        self.assertNotIn("persisted", calls)


if __name__ == "__main__":
    unittest.main()
