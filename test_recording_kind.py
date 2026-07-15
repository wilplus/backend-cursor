"""willab — spoken vs read recording (founder 2026-07-14).

The re-read of the suggestion-corrected text is a PAIRED VARIANT of its spoken
take: tagged 'read', linked via paired_session_id, inheriting the spoken take's
arc/number, and NOT counted as one of the 3 takes.

Covers the two db seams (fake PostgREST client, no live DB — mirrors
test_priming's technique): set_session_recording_kind + count_arc_sessions
(spoken-only via paired_session_id IS NULL). The metrics.recording_kind stamp
+ its serve are covered in test_readout_reread.

Run: python3 -m unittest test_recording_kind
"""
from __future__ import annotations

import unittest

try:
    from services.db import DatabaseService
    _DB_IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    DatabaseService = None
    _DB_IMPORT_ERROR = e


class _FakeUpdateClient:
    def __init__(self, raise_missing=False):
        self.raise_missing = raise_missing
        self.payload = None
        self.filter = None

    def table(self, name):
        assert name == "v2_sessions"
        return self

    def update(self, payload):
        self.payload = payload
        return self

    def eq(self, c, v):
        self.filter = (c, v)
        return self

    def execute(self):
        if self.raise_missing:
            raise Exception("column v2_sessions.recording_kind does not exist")
        return type("R", (), {"data": [{"id": "s1"}]})()


@unittest.skipIf(_DB_IMPORT_ERROR is not None, f"needs db deps: {_DB_IMPORT_ERROR}")
class SetSessionRecordingKindTests(unittest.TestCase):

    def _svc(self, **kw):
        s = DatabaseService.__new__(DatabaseService)
        fake = _FakeUpdateClient(**kw)
        s.client = fake
        return s, fake

    def test_read_tags_kind_and_pairs(self):
        svc, fake = self._svc()
        self.assertTrue(svc.set_session_recording_kind("s2", "read", "s1"))
        self.assertEqual(fake.payload,
                         {"recording_kind": "read", "paired_session_id": "s1"})
        self.assertEqual(fake.filter, ("id", "s2"))

    def test_spoken_tags_kind_only(self):
        svc, fake = self._svc()
        self.assertTrue(svc.set_session_recording_kind("s1", "spoken"))
        self.assertEqual(fake.payload, {"recording_kind": "spoken"})

    def test_bad_kind_is_false_no_write(self):
        svc, fake = self._svc()
        self.assertFalse(svc.set_session_recording_kind("s1", "sung"))
        self.assertIsNone(fake.payload)

    def test_missing_column_degrades_false_not_raise(self):
        svc, _ = self._svc(raise_missing=True)
        self.assertFalse(svc.set_session_recording_kind("s2", "read", "s1"))


class _FakeCountClient:
    def __init__(self, count):
        self._count = count
        self.filters = []

    def table(self, name):
        assert name == "v2_sessions"
        return self

    def select(self, *a, **k):
        return self

    def eq(self, c, v):
        self.filters.append(("eq", c, v)); return self

    def neq(self, c, v):
        self.filters.append(("neq", c, v)); return self

    def is_(self, c, v):
        self.filters.append(("is", c, v)); return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return type("R", (), {"count": self._count})()


@unittest.skipIf(_DB_IMPORT_ERROR is not None, f"needs db deps: {_DB_IMPORT_ERROR}")
class CountArcSpokenOnlyTests(unittest.TestCase):
    """count_arc_sessions counts SPOKEN takes only (paired_session_id IS NULL)
    so a read never inflates the 3-take count."""

    def _svc(self, count):
        s = DatabaseService.__new__(DatabaseService)
        fake = _FakeCountClient(count)
        s.client = fake
        return s, fake

    def test_filters_out_reads_via_paired_null(self):
        svc, fake = self._svc(2)
        n = svc.count_arc_sessions("arc1", exclude_session_id="cur")
        self.assertEqual(n, 2)
        self.assertIn(("is", "paired_session_id", "null"), fake.filters)
        self.assertIn(("neq", "id", "cur"), fake.filters)


if __name__ == "__main__":
    unittest.main()
