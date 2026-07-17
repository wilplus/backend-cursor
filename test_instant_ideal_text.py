"""willab — the INSTANT ideal-text lane (founder re-lock 2026-07-17).

The June rule "the raw auto-assembled draft must NEVER reach the student" is
explicitly reversed for this labeled lane: the frozen MACHINE copy
(auto_text) serves FREE the moment take 3 lands; the coach-perfected text +
takes 2/3 feedback stay behind approval + the $25 unlock. Everything is
gated on INSTANT_IDEAL_TEXT_ENABLED (default OFF).

Pinned here:
  * the student GET's three variants (perfected / instant / legacy locked)
    per flag x payment x approval combination;
  * L1: the coach's WORKING text NEVER leaks through the free lane;
  * persist_auto_ideal_text dual-write (auto always refreshed, coach text
    never clobbered; migration-pending fallback = legacy guard);
  * the idempotent instant bubble with an HONEST insert count.

Run: python3 -m unittest test_instant_ideal_text
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from flask import Flask, jsonify, request
    from routes import v2_routes as v2
    from services.db import DatabaseService
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    jsonify = None
    request = None
    v2 = None
    DatabaseService = None
    _IMPORT_ERROR = e

ARC = "a1"


def _machine_row(**over):
    row = {"arc_id": ARC, "text": "machine text", "auto_text": "machine auto",
           "updated_by": None, "approved_at": None}
    row.update(over)
    return row


def _coach_row(**over):
    row = {"arc_id": ARC, "text": "coach secret text",
           "auto_text": "machine auto", "updated_by": "coach1",
           "approved_at": None}
    row.update(over)
    return row


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class StudentIdealTextVariantsTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)

    def _get(self, *, flag, paid, row, owned=True):
        with self.app.test_request_context():
            request.user_id = "u1"

            def _gate(arc_id):
                if paid:
                    return None
                return jsonify({"code": "ARC_NOT_UNLOCKED",
                                "error": "unlock required"}), 402

            with patch.object(v2, "_arc_owned_by_caller",
                              return_value=(owned, [])), \
                 patch.object(v2, "_instant_ideal_enabled",
                              return_value=flag), \
                 patch.object(v2, "_arc_payment_gate", side_effect=_gate), \
                 patch.object(v2, "_paywall_block",
                              return_value={"price": {"credits": 25},
                                            "credits_current": 3,
                                            "arc_id": ARC}), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=row), \
                 patch.object(v2.db, "get_user_arc_ideal_notes",
                              return_value="my notes"):
                out = v2.v2_explore_get_ideal_text.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status

    def test_flag_on_unpaid_serves_instant_with_paywall(self):
        body, status = self._get(flag=True, paid=False, row=_machine_row())
        self.assertEqual(status, 200)
        self.assertEqual(body["variant"], "instant")
        self.assertEqual(body["text"], "machine auto")
        self.assertFalse(body["approved"])
        self.assertIn("paywall", body)          # the upsell info
        self.assertNotIn("notes_text", body)    # notes stay perfected-lane
        self.assertNotIn("notes", body)

    def test_flag_on_paid_unapproved_serves_instant_without_paywall(self):
        body, status = self._get(flag=True, paid=True, row=_machine_row())
        self.assertEqual(status, 200)
        self.assertEqual(body["variant"], "instant")
        self.assertNotIn("paywall", body)       # already entitled

    def test_coach_working_text_never_leaks_through_the_free_lane(self):
        # L1: coach-owned row WITHOUT a machine copy (pre-migration) must NOT
        # serve the coach's text free — legacy 402 instead.
        import json
        body, status = self._get(
            flag=True, paid=False, row=_coach_row(auto_text=None))
        self.assertEqual(status, 402)
        self.assertNotIn("coach secret text", json.dumps(body))

    def test_coach_owned_row_still_serves_its_machine_copy(self):
        # The frozen auto copy is machine content — free even mid-coach-edit.
        body, status = self._get(flag=True, paid=False, row=_coach_row())
        self.assertEqual(status, 200)
        self.assertEqual(body["variant"], "instant")
        self.assertEqual(body["text"], "machine auto")
        self.assertNotIn("coach secret", body["text"])

    def test_prebackfill_machine_row_falls_back_to_text(self):
        body, status = self._get(
            flag=True, paid=False, row=_machine_row(auto_text=None))
        self.assertEqual(status, 200)
        self.assertEqual(body["variant"], "instant")
        self.assertEqual(body["text"], "machine text")

    def test_paid_approved_serves_perfected_regardless_of_flag(self):
        for flag in (True, False):
            body, status = self._get(
                flag=flag, paid=True,
                row=_coach_row(approved_at="2026-07-17T10:00:00Z"))
            self.assertEqual(status, 200)
            self.assertEqual(body["variant"], "perfected")
            self.assertEqual(body["text"], "coach secret text")
            self.assertTrue(body["approved"])
            self.assertEqual(body["notes_text"], "my notes")

    def test_flag_off_is_the_legacy_flow(self):
        body, status = self._get(flag=False, paid=False, row=_machine_row())
        self.assertEqual(status, 402)           # payment gate, no instant
        body, status = self._get(flag=False, paid=True, row=_machine_row())
        self.assertEqual(status, 200)
        self.assertTrue(body["locked"])          # unapproved → locked
        self.assertEqual(body["reason"], "NOT_APPROVED")

    def test_no_machine_copy_yet_keeps_legacy_shape(self):
        body, status = self._get(flag=True, paid=True, row=None)
        self.assertEqual(status, 200)
        self.assertTrue(body["locked"])

    def test_unowned_arc_404s(self):
        body, status = self._get(flag=True, paid=False, row=_machine_row(),
                                 owned=False)
        self.assertEqual(status, 404)

    def test_instant_payload_is_score_free(self):
        import json
        body, _ = self._get(flag=True, paid=False, row=_machine_row())
        raw = json.dumps(body)
        for banned in ("potentiometer", "acoustic_read", "overall_score",
                       "slide_stickiness", "rank"):
            self.assertNotIn(banned, raw)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class PersistAutoIdealDualWriteTests(unittest.TestCase):
    """persist_auto_ideal_text: auto always refreshed; coach text never
    clobbered; migration-pending fallback = the legacy guard."""

    class _Client:
        def __init__(self, auto_cols=True):
            self.auto_cols = auto_cols
            self.upserts = []
            self._pending = None

        def table(self, name):
            return self

        def upsert(self, payload, on_conflict=None):
            self._pending = payload
            return self

        def execute(self):
            if not self.auto_cols and "auto_text" in (self._pending or {}):
                raise RuntimeError(
                    'column "auto_text" of relation '
                    '"coach_arc_ideal_text" does not exist')
            self.upserts.append(self._pending)
            return self

    def _persist(self, row, *, auto_cols=True, text="fresh machine"):
        client = self._Client(auto_cols=auto_cols)
        fake = SimpleNamespace(
            client=client,
            get_coach_arc_ideal_text=lambda a: row,
        )
        ok = DatabaseService.persist_auto_ideal_text(fake, ARC, text)
        return ok, client.upserts

    def test_machine_owned_writes_both_copies(self):
        ok, ups = self._persist(_machine_row())
        self.assertTrue(ok)
        self.assertEqual(len(ups), 1)
        self.assertEqual(ups[0]["text"], "fresh machine")
        self.assertEqual(ups[0]["auto_text"], "fresh machine")
        self.assertIsNone(ups[0]["updated_by"])

    def test_coach_owned_refreshes_auto_only(self):
        ok, ups = self._persist(_coach_row())
        self.assertTrue(ok)
        self.assertEqual(len(ups), 1)
        self.assertNotIn("text", ups[0])         # the coach's copy untouched
        self.assertNotIn("updated_by", ups[0])
        self.assertEqual(ups[0]["auto_text"], "fresh machine")

    def test_migration_pending_falls_back_to_legacy_guard(self):
        # machine-owned → legacy single-column write still lands
        ok, ups = self._persist(_machine_row(), auto_cols=False)
        self.assertTrue(ok)
        self.assertEqual(len(ups), 1)
        self.assertNotIn("auto_text", ups[0])
        self.assertEqual(ups[0]["text"], "fresh machine")
        # coach-owned → refuse entirely (never clobber pre-migration)
        ok, ups = self._persist(_coach_row(), auto_cols=False)
        self.assertFalse(ok)
        self.assertEqual(ups, [])

    def test_empty_text_refused(self):
        ok, ups = self._persist(_machine_row(), text="   ")
        self.assertFalse(ok)
        self.assertEqual(ups, [])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class InstantBubbleTests(unittest.TestCase):

    def _fire(self, insert_returns):
        from services.arc_notifications import fire_instant_ideal_ready
        captured = {}

        class _Db:
            def insert_lounge_messages(self, uid, msgs):
                captured["uid"] = uid
                captured["msgs"] = msgs
                return insert_returns

        ok = fire_instant_ideal_ready(_Db(), "u1", ARC)
        return ok, captured

    def test_fires_idempotent_variant_tagged_bubble(self):
        ok, cap = self._fire(insert_returns=[{"id": "row"}])
        self.assertTrue(ok)
        msg = cap["msgs"][0]
        from services.lounge_messages import VALID_KINDS
        self.assertIn(msg["kind"], VALID_KINDS)   # no CHECK migration needed
        self.assertEqual(msg["kind"], "ideal_text")
        self.assertEqual(msg["metadata"]["variant"], "instant")
        self.assertEqual(msg["metadata"]["arc_id"], ARC)
        # deterministic client_id = idempotent per arc
        ok2, cap2 = self._fire(insert_returns=[{"id": "row"}])
        self.assertEqual(msg["client_id"], cap2["msgs"][0]["client_id"])
        # ...and distinct from the publish-time purple bubble's key
        import uuid as _uuid
        purple = str(_uuid.uuid5(_uuid.NAMESPACE_URL,
                                 f"willab-idealtext:{ARC}"))
        self.assertNotEqual(msg["client_id"], purple)

    def test_swallowed_rejection_reads_as_not_fired(self):
        # The #201 lesson: insert_lounge_messages returns [] on a DB refusal.
        with self.assertLogs("services.arc_notifications",
                             level="ERROR") as logs:
            ok, _ = self._fire(insert_returns=[])
        self.assertFalse(ok)
        self.assertTrue(any("dropped" in line for line in logs.output))

    def test_missing_ids_no_fire(self):
        from services.arc_notifications import fire_instant_ideal_ready
        self.assertFalse(fire_instant_ideal_ready(None, None, ARC))
        self.assertFalse(fire_instant_ideal_ready(None, "u1", None))


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class FlagDefaultTests(unittest.TestCase):
    def test_flag_defaults_off(self):
        import os
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INSTANT_IDEAL_TEXT_ENABLED", None)
            self.assertFalse(v2._instant_ideal_enabled())
        with patch.dict(os.environ, {"INSTANT_IDEAL_TEXT_ENABLED": "1"}):
            self.assertTrue(v2._instant_ideal_enabled())


if __name__ == "__main__":
    unittest.main()
