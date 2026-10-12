"""willab — the INSTANT ideal-text lane (founder re-lock 2026-07-17).

The frozen MACHINE copy (auto_text) serves FREE the moment take 3 lands.
(The student GET's legacy per-payment variants were retired with the $25
model — see test_single_deliverable for the single-deliverable payload.)

Pinned here:
  * persist_auto_ideal_text dual-write (auto always refreshed, coach text
    never clobbered; migration-pending fallback = legacy guard);
  * the idempotent instant bubble with an HONEST insert count.

Run: python3 -m unittest tests.test_instant_ideal_text
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch
from config import Config
import config as _config_module

try:
    from flask import Flask, jsonify, request
    from routes.v2 import explore_ideal_text as v2_explore_ideal_text
    from services.db import DatabaseService
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    jsonify = None
    request = None
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
            ideal_text=SimpleNamespace(get_coach_arc_ideal_text=lambda a: row),
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
@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class FlagDefaultTests(unittest.TestCase):
    def test_flag_defaults_off(self):
        import os
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INSTANT_IDEAL_TEXT_ENABLED", None)
            # Boot-time Config read (audit Q-A5): an unset variable parses off.
            self.assertFalse(_config_module._env_flag("INSTANT_IDEAL_TEXT_ENABLED", "0"))
        with patch.object(Config, "INSTANT_IDEAL_TEXT_ENABLED", False):
            self.assertFalse(v2_explore_ideal_text._instant_ideal_enabled())
        with patch.object(Config, "INSTANT_IDEAL_TEXT_ENABLED", True):
            self.assertTrue(v2_explore_ideal_text._instant_ideal_enabled())


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

        @property
        def takes(self):
            # audit Q-A2: production now calls db.takes.<method>();
            # this fake implements those methods directly on itself.
            return self

        def insert_lounge_messages(self, user_id, messages):
            self.rows.extend(messages)
            return list(messages)

    def _meta(self, db):
        return db.rows[0]["metadata"]

    def test_the_version_bubble_carries_the_topic(self):
        from services.arc_notifications import fire_ideal_version_ready
        db = self._Db()
        fire_ideal_version_ready(db, "u1", "arc-1", 2)
        self.assertEqual(self._meta(db)["topic"], "Book really")
