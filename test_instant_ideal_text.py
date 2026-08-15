"""willab — the INSTANT ideal-text lane (founder re-lock 2026-07-17).

The frozen MACHINE copy (auto_text) serves FREE the moment take 3 lands.
(The student GET's legacy per-payment variants were retired with the $25
model — see test_single_deliverable for the single-deliverable payload.)

Pinned here:
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


class BubbleCarriesItsOwnNameTests(unittest.TestCase):
    """THE ROW KNOWS ITS PROJECT (founder 2026-08-15).

    The bubble carried `arc_id` and nothing else, so the card had to GET the
    document on mount just to render a heading — showing "Your ideal text"
    until it landed, on every bubble, on every app open. The name is free at
    write time; fetching it at read time was the whole defect."""

    class _Db:
        def __init__(self, sessions=None, boom=False):
            self._sessions = sessions if sessions is not None else [
                {"id": "s1", "user_id": "u1", "recording_kind": "spoken",
                 "intake_context": {"topic": "Book really"}},
            ]
            self._boom = boom
            self.rows = []

        def get_arc_sessions(self, arc_id):
            if self._boom:
                raise RuntimeError("db down")
            return list(self._sessions)

        def insert_lounge_messages(self, user_id, messages):
            self.rows.extend(messages)
            return list(messages)

    def _meta(self, db):
        return db.rows[0]["metadata"]

    def test_the_instant_bubble_carries_the_topic(self):
        from services.arc_notifications import fire_instant_ideal_ready
        db = self._Db()
        self.assertTrue(fire_instant_ideal_ready(db, "u1", "arc-1"))
        self.assertEqual(self._meta(db)["topic"], "Book really")

    def test_the_version_bubble_carries_the_topic(self):
        from services.arc_notifications import fire_ideal_version_ready
        db = self._Db()
        fire_ideal_version_ready(db, "u1", "arc-1", 2)
        self.assertEqual(self._meta(db)["topic"], "Book really")

    def test_a_missing_topic_is_None_not_an_empty_string(self):
        # The FE falls back on a falsy topic either way, but "" stored as if it
        # were a name is the same class of lie the FE cache refuses to persist.
        from services.arc_notifications import fire_instant_ideal_ready
        db = self._Db(sessions=[{"id": "s1", "user_id": "u1",
                                 "recording_kind": "spoken",
                                 "intake_context": {"topic": "   "}}])
        fire_instant_ideal_ready(db, "u1", "arc-1")
        self.assertIsNone(self._meta(db)["topic"])

    def test_a_topic_lookup_failure_NEVER_blocks_the_bubble(self):
        # The name is decoration; the bubble is the delivery. A DB hiccup must
        # cost a heading, never the card telling the student their text is
        # ready (LIVE LOOP).
        from services.arc_notifications import fire_instant_ideal_ready
        db = self._Db(boom=True)
        self.assertTrue(fire_instant_ideal_ready(db, "u1", "arc-1"))
        self.assertIsNone(self._meta(db)["topic"])
        self.assertEqual(self._meta(db)["arc_id"], "arc-1")
