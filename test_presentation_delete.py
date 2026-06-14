"""DELETE /v2/user/presentations/<id> and .../takes/<n> (FE PR #161).

Hard-delete semantics (founder call): a presentation deletes ALL its takes'
sessions; a take deletes the one session at that 1-based chronological
position. take_number ordering must MATCH /user/strengths (so the FE's "take
3" deletes the same session the user sees). Owner-scoped. Durable — drops the
library rows AND the underlying session so the readout re-ingest can't
resurrect it.

Route tests: skip locally (no flask), run in CI.
Run: python3 -m unittest test_presentation_delete
"""
from __future__ import annotations

import unittest

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
    _IMPORT_ERROR = e


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class PresentationDeleteTests(unittest.TestCase):
    UID = "user-1"

    def setUp(self):
        self.app = Flask(__name__)
        self.originals = {}
        # Two decks: A has two takes (s1 oldest, s2 newest), B has one (s3);
        # s4 is deckless (→ general, never a presentation).
        self._sessions = {
            "s1": {"created_at": "2026-01-01T00:00:00Z",
                   "intake_context": {"slides": [{"title": "Intro", "body": "hello"}]}},
            "s2": {"created_at": "2026-02-01T00:00:00Z",
                   "intake_context": {"slides": [{"title": "Intro", "body": "hello"}]}},
            "s3": {"created_at": "2026-03-01T00:00:00Z",
                   "intake_context": {"slides": [{"title": "Other", "body": "x"}]}},
            "s4": {"created_at": "2026-04-01T00:00:00Z",
                   "intake_context": {"slides": []}},
        }
        self._lib = [
            {"session_id": sid, "tag": "strong", "note": "n", "snippet_ref": {}}
            for sid in ("s1", "s2", "s3", "s4")
        ]
        self.deleted_lib: list = []
        self.deleted_sessions: list = []
        self._patch_db("get_strong_sides_library", lambda uid, **kw: list(self._lib))
        self._patch_db("v2_get_session_by_id", lambda sid: dict(self._sessions.get(sid, {}), id=sid))
        self._patch_db(
            "delete_strong_sides_library_for_session",
            lambda uid, sid: self.deleted_lib.append((uid, sid)) or 1,
        )
        self._patch_db(
            "v2_delete_session",
            lambda sid, uid: self.deleted_sessions.append((sid, uid)) or True,
        )

    def tearDown(self):
        for target, attr, orig in self.originals.values():
            setattr(target, attr, orig)

    def _patch_db(self, attr, fn):
        self.originals[f"db:{attr}"] = (v2.db, attr, getattr(v2.db, attr, None))
        setattr(v2.db, attr, fn)

    def _pid(self, n_takes):
        """The presentation_id of the group with exactly n_takes sessions."""
        groups = v2._user_presentation_groups(self.UID)
        for pid, sids in groups.items():
            if len(sids) == n_takes:
                return pid, sids
        raise AssertionError(f"no group with {n_takes} takes: {groups}")

    # ── grouping / take_number ──

    def test_groups_match_strengths_ordering(self):
        groups = v2._user_presentation_groups(self.UID)
        # deck A → [s1, s2] (oldest first = take 1); deck B → [s3]; s4 excluded
        two = [sids for sids in groups.values() if len(sids) == 2]
        self.assertEqual(two, [["s1", "s2"]])
        self.assertNotIn("s4", [s for sids in groups.values() for s in sids])

    # ── DELETE presentation ──

    def test_delete_presentation_removes_all_takes(self):
        pid, sids = self._pid(2)
        with self.app.test_request_context():
            request.user_id = self.UID
            resp, status = v2.v2_user_delete_presentation.__wrapped__(pid)
        self.assertEqual(status, 200)
        self.assertEqual(resp.get_json()["deleted_sessions"], 2)
        self.assertEqual({s for s, _ in self.deleted_sessions}, {"s1", "s2"})
        self.assertEqual({s for _, s in self.deleted_lib}, {"s1", "s2"})

    def test_delete_unknown_presentation_404(self):
        with self.app.test_request_context():
            request.user_id = self.UID
            resp, status = v2.v2_user_delete_presentation.__wrapped__("deadbeef")
        self.assertEqual(status, 404)
        self.assertEqual(self.deleted_sessions, [])

    # ── DELETE take ──

    def test_delete_take_targets_the_right_session(self):
        pid, sids = self._pid(2)  # [s1, s2]
        with self.app.test_request_context():
            request.user_id = self.UID
            resp, status = v2.v2_user_delete_take.__wrapped__(pid, "2")
        self.assertEqual(status, 200)
        self.assertEqual(resp.get_json()["deleted_session"], "s2")  # take 2 = newest
        self.assertEqual(self.deleted_sessions, [("s2", self.UID)])

    def test_delete_take_one_is_oldest(self):
        pid, sids = self._pid(2)
        with self.app.test_request_context():
            request.user_id = self.UID
            resp, status = v2.v2_user_delete_take.__wrapped__(pid, "1")
        self.assertEqual(resp.get_json()["deleted_session"], "s1")

    def test_delete_take_bad_number_400(self):
        pid, _ = self._pid(2)
        with self.app.test_request_context():
            request.user_id = self.UID
            _resp, status = v2.v2_user_delete_take.__wrapped__(pid, "abc")
        self.assertEqual(status, 400)
        self.assertEqual(self.deleted_sessions, [])

    def test_delete_take_out_of_range_404(self):
        pid, _ = self._pid(2)
        with self.app.test_request_context():
            request.user_id = self.UID
            _resp, status = v2.v2_user_delete_take.__wrapped__(pid, "9")
        self.assertEqual(status, 404)
        self.assertEqual(self.deleted_sessions, [])


if __name__ == "__main__":
    unittest.main()
