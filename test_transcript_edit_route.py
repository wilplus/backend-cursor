"""PUT /v2/user/sessions/<sid>/transcript-edits — route-level tests (founder
2026-07-07 user transcript edits) + the db upsert's NULL-distinct manual
update-or-insert logic.

Flask-route classes skip locally (no Flask/Supabase in the dev sandbox) and
run in CI — the known gotcha; keep assertions in sync with the route.

Run: python3 -m unittest test_transcript_edit_route
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
    _IMPORT_ERROR = e


_SID = "11111111-1111-4111-8111-111111111111"
_SNIP = "22222222-2222-4222-8222-222222222222"


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class TranscriptEditRouteTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self._session = {"id": _SID, "user_id": "u1"}
        self._saved = []
        # Target-existence fixtures: the snippet _SNIP belongs to _SID; the
        # deckless transcript yields exactly 2 chunks (legacy blob ~289
        # chars re-chunked at <=200 chars).
        self._snippet_row = {"id": _SNIP, "session_id": _SID}
        self._stx = [{"index": 0,
                      "transcript": " ".join(f"w{i}" for i in range(60))}]

        def _upsert(session_id, *, snippet_id=None, chunk_index=None, text):
            self._saved.append({
                "session_id": session_id, "snippet_id": snippet_id,
                "chunk_index": chunk_index, "text": text,
            })
            return True

        self._patches = [
            patch.object(v2.db, "v2_get_session_by_id",
                         lambda sid: self._session),
            patch.object(v2.db, "get_snippet_by_id",
                         lambda sid: self._snippet_row),
            patch.object(v2.db, "get_session_slide_transcripts",
                         lambda sid: self._stx),
            patch.object(v2.db, "upsert_user_transcript_edit", _upsert),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def _call(self, body, session_id=_SID, user_id="u1"):
        with self.app.test_request_context(json=body):
            request.user_id = user_id
            resp, status = v2.v2_user_put_transcript_edit.__wrapped__(session_id)
            return resp.get_json(), status

    def test_snippet_edit_saves(self):
        body, status = self._call({"snippet_id": _SNIP, "text": "fixed"})
        self.assertEqual(status, 200)
        self.assertTrue(body["saved"])
        self.assertEqual(body["snippet_id"], _SNIP)
        self.assertEqual(self._saved[0]["snippet_id"], _SNIP)
        self.assertIsNone(self._saved[0]["chunk_index"])

    def test_chunk_edit_saves(self):
        body, status = self._call({"chunk_index": 0, "text": "fixed"})
        self.assertEqual(status, 200)
        self.assertEqual(body["chunk_index"], 0)
        self.assertEqual(self._saved[0]["chunk_index"], 0)
        self.assertIsNone(self._saved[0]["snippet_id"])

    def test_not_owner_404s(self):
        body, status = self._call({"snippet_id": _SNIP, "text": "x"},
                                  user_id="intruder")
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "SESSION_NOT_FOUND")
        self.assertEqual(self._saved, [])

    def test_blank_text_400s(self):
        _, status = self._call({"snippet_id": _SNIP, "text": "   "})
        self.assertEqual(status, 400)

    def test_over_long_text_400s(self):
        _, status = self._call({"snippet_id": _SNIP, "text": "x" * 2001})
        self.assertEqual(status, 400)

    def test_both_targets_400s(self):
        _, status = self._call(
            {"snippet_id": _SNIP, "chunk_index": 0, "text": "x"})
        self.assertEqual(status, 400)

    def test_neither_target_400s(self):
        _, status = self._call({"text": "x"})
        self.assertEqual(status, 400)

    def test_negative_chunk_index_400s(self):
        _, status = self._call({"chunk_index": -1, "text": "x"})
        self.assertEqual(status, 400)

    def test_bool_chunk_index_400s(self):
        # True is an int subclass — must not slip through as chunk 1.
        _, status = self._call({"chunk_index": True, "text": "x"})
        self.assertEqual(status, 400)

    def test_non_uuid_snippet_400s(self):
        _, status = self._call({"snippet_id": "not-a-uuid", "text": "x"})
        self.assertEqual(status, 400)

    def test_invalid_session_uuid_400s(self):
        _, status = self._call({"snippet_id": _SNIP, "text": "x"},
                               session_id="nope")
        self.assertEqual(status, 400)

    def test_db_failure_500s(self):
        with patch.object(v2.db, "upsert_user_transcript_edit",
                          lambda *a, **k: False):
            body, status = self._call({"snippet_id": _SNIP, "text": "x"})
        self.assertEqual(status, 500)

    # ── review must-fixes: type + target-existence validation ────────────

    def test_non_string_text_400s_not_500(self):
        body, status = self._call({"snippet_id": _SNIP, "text": 5})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "INVALID_INPUT")

    def test_non_string_snippet_id_400s_not_500(self):
        body, status = self._call({"snippet_id": 123, "text": "x"})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "INVALID_INPUT")

    def test_snippet_from_another_session_404s(self):
        self._snippet_row = {"id": _SNIP, "session_id": "other-session"}
        body, status = self._call({"snippet_id": _SNIP, "text": "x"})
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "SNIPPET_NOT_FOUND")
        self.assertEqual(self._saved, [])

    def test_unknown_snippet_404s(self):
        self._snippet_row = None
        _, status = self._call({"snippet_id": _SNIP, "text": "x"})
        self.assertEqual(status, 404)
        self.assertEqual(self._saved, [])

    def test_chunk_index_out_of_range_400s(self):
        # legacy blob → 2 chunks under the 200-char cut; index 2 is past the end.
        body, status = self._call({"chunk_index": 2, "text": "x"})
        self.assertEqual(status, 400)
        self.assertEqual(self._saved, [])

    def test_chunk_index_int_overflow_400s_not_500(self):
        _, status = self._call({"chunk_index": 2147483648, "text": "x"})
        self.assertEqual(status, 400)  # bounded by real count, never hits INT4

    def test_last_valid_chunk_index_saves(self):
        _, status = self._call({"chunk_index": 1, "text": "x"})
        self.assertEqual(status, 200)

    def test_chunk_edit_on_no_transcript_session_400s(self):
        self._stx = []
        _, status = self._call({"chunk_index": 0, "text": "x"})
        self.assertEqual(status, 400)


class _Resp:
    def __init__(self, data):
        self.data = data


class _FakeEditsTable:
    """Minimal PostgREST-ish fake for user_transcript_edits: supports the
    select→update-or-insert flow with NULL-distinct semantics."""

    def __init__(self, store):
        self._store = store  # list of row dicts
        self._mode = None
        self._filters = {}
        self._payload = None

    # chain starters
    def select(self, *_):
        self._mode = "select"
        return self

    def update(self, payload):
        self._mode = "update"
        self._payload = payload
        return self

    def insert(self, row):
        self._mode = "insert"
        self._payload = row
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def limit(self, _n):
        return self

    def execute(self):
        if self._mode == "select":
            rows = [r for r in self._store
                    if all(r.get(k) == v for k, v in self._filters.items())]
            return _Resp([{"id": r["id"]} for r in rows])
        if self._mode == "update":
            for r in self._store:
                if all(r.get(k) == v for k, v in self._filters.items()):
                    r.update(self._payload)
            return _Resp([])
        if self._mode == "insert":
            row = dict(self._payload)
            # Enforce the migration's per-kind unique pairs, like Postgres.
            for r in self._store:
                if r.get("session_id") != row.get("session_id"):
                    continue
                same_snip = ("snippet_id" in row and
                             r.get("snippet_id") == row.get("snippet_id"))
                same_chunk = ("chunk_index" in row and
                              r.get("chunk_index") == row.get("chunk_index"))
                if same_snip or same_chunk:
                    raise RuntimeError(
                        'duplicate key value violates unique constraint (23505)')
            row.setdefault("id", f"row{len(self._store)}")
            self._store.append(row)
            return _Resp([row])
        return _Resp([])


class _FakeEditsClient:
    def __init__(self, store):
        self._store = store

    def table(self, name):
        assert name == "user_transcript_edits"
        return _FakeEditsTable(self._store)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class UpsertUserTranscriptEditTests(unittest.TestCase):
    """The manual select→update-or-insert (NULL-distinct unique keys mean
    ON CONFLICT can't be used — see the db docstring)."""

    def _db(self, store):
        cls = v2.db.__class__
        s = cls.__new__(cls)  # bypass __init__ (no live connection)
        s.client = _FakeEditsClient(store)
        return s

    def test_insert_then_update_same_snippet(self):
        store: list = []
        d = self._db(store)
        self.assertTrue(d.upsert_user_transcript_edit(
            _SID, snippet_id=_SNIP, text="v1"))
        self.assertTrue(d.upsert_user_transcript_edit(
            _SID, snippet_id=_SNIP, text="v2"))
        self.assertEqual(len(store), 1)          # updated, not duplicated
        self.assertEqual(store[0]["text"], "v2")

    def test_snippet_and_chunk_edits_dont_collide(self):
        store: list = []
        d = self._db(store)
        self.assertTrue(d.upsert_user_transcript_edit(
            _SID, snippet_id=_SNIP, text="snip fix"))
        self.assertTrue(d.upsert_user_transcript_edit(
            _SID, chunk_index=0, text="chunk fix"))
        self.assertEqual(len(store), 2)

    def test_two_chunks_are_separate_rows(self):
        store: list = []
        d = self._db(store)
        self.assertTrue(d.upsert_user_transcript_edit(
            _SID, chunk_index=0, text="a"))
        self.assertTrue(d.upsert_user_transcript_edit(
            _SID, chunk_index=1, text="b"))
        self.assertEqual(len(store), 2)

    def test_exactly_one_target_enforced(self):
        d = self._db([])
        self.assertFalse(d.upsert_user_transcript_edit(
            _SID, snippet_id=_SNIP, chunk_index=0, text="x"))
        self.assertFalse(d.upsert_user_transcript_edit(_SID, text="x"))
        self.assertFalse(d.upsert_user_transcript_edit(
            _SID, snippet_id=_SNIP, text=""))

    def test_lost_insert_race_retries_as_update(self):
        # Review fix: a concurrent first-save landed a row between our select
        # (empty) and our insert (unique violation) — the retry must convert
        # this request into the update it really is, not a False → 500.
        store: list = []
        d = self._db(store)

        class _RacingTable(_FakeEditsTable):
            def execute(inner):
                if inner._mode == "select" and not getattr(
                        _RacingTable, "_raced", False):
                    _RacingTable._raced = True
                    # Simulate the concurrent writer landing AFTER our empty
                    # select: report empty now, but seed the store so the
                    # insert collides.
                    store.append({"id": "raced", "session_id": _SID,
                                  "snippet_id": _SNIP, "text": "theirs"})
                    return _Resp([])
                return super().execute()

        class _RacingClient(_FakeEditsClient):
            def table(inner, name):
                assert name == "user_transcript_edits"
                return _RacingTable(store)

        _RacingTable._raced = False
        d.client = _RacingClient(store)
        self.assertTrue(d.upsert_user_transcript_edit(
            _SID, snippet_id=_SNIP, text="mine"))
        self.assertEqual(len(store), 1)          # no duplicate row
        self.assertEqual(store[0]["text"], "mine")  # our edit won as an update


if __name__ == "__main__":
    unittest.main()
