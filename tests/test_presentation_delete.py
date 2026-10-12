"""DELETE /v2/user/presentations/<id> and .../takes/<n> (FE PR #161).

Hard-delete semantics (founder call): a presentation deletes ALL its takes'
sessions; a take deletes the one session at that 1-based chronological
position. take_number ordering must MATCH /user/strengths (so the FE's "take
3" deletes the same session the user sees). Owner-scoped. Durable — drops the
library rows AND the underlying session so the readout re-ingest can't
resurrect it.

Route tests: skip locally (no flask), run in CI.
Run: python3 -m unittest tests.test_presentation_delete
"""
from __future__ import annotations

import unittest

try:
    from flask import Flask, request

    from routes.v2 import user_sessions as v2_user_sessions
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class PresentationDeleteTests(unittest.TestCase):
    UID = "user-1"

    def setUp(self):
        self.app = Flask(__name__)
        self.originals = {}
        # Two UPLOADED decks: A has two takes (s1 oldest, s2 newest), B has
        # one (s3); s4 is deckless (→ general, never a presentation).
        #
        # `presentation_ref` is what marks a deck as UPLOADED (2026-08-15) —
        # a real deck always has the PDF behind it, and it is now what
        # identifies the presentation. Slides alone stopped being enough the
        # day the generic default deck started shipping on deckless takes.
        self._sessions = {
            "s1": {"created_at": "2026-01-01T00:00:00Z",
                   "intake_context": {"slides": [{"title": "Intro", "body": "hello"}],
                                      "presentation_ref": "https://x/a.pdf"}},
            "s2": {"created_at": "2026-02-01T00:00:00Z",
                   "intake_context": {"slides": [{"title": "Intro", "body": "hello"}],
                                      "presentation_ref": "https://x/a.pdf"}},
            "s3": {"created_at": "2026-03-01T00:00:00Z",
                   "intake_context": {"slides": [{"title": "Other", "body": "x"}],
                                      "presentation_ref": "https://x/b.pdf"}},
            "s4": {"created_at": "2026-04-01T00:00:00Z",
                   "intake_context": {"slides": []}},
        }
        self.deleted_sessions: list = []
        self._patch_db("v2_get_session_by_id", lambda sid: dict(self._sessions.get(sid, {}), id=sid))
        # 4.4 fix: the presentation DELETE now resolves its target set from
        # the user's lab sessions (complete set), not the library grouping.
        self._patch_db("v2_list_user_lab_sessions", lambda uid, **kw: [
            dict(meta, id=sid) for sid, meta in self._sessions.items()
        ])
        self._patch_db(
            "v2_delete_sessions",
            lambda sids, uid: self.deleted_sessions.extend(
                (sid, uid) for sid in sids),
        )

    def tearDown(self):
        for target, attr, orig in self.originals.values():
            setattr(target, attr, orig)

    def _patch_db(self, attr, fn):
        # audit Q-A2: takes-family methods now live on db.takes, not db.
        target = db.takes if hasattr(db.takes, attr) else db
        self.originals[f"db:{attr}"] = (target, attr, getattr(target, attr, None))
        setattr(target, attr, fn)

    def _pid(self, n_takes):
        """The presentation_id of the group with exactly n_takes sessions."""
        groups = v2_user_sessions._user_presentation_groups(self.UID)
        for pid, sids in groups.items():
            if len(sids) == n_takes:
                return pid, sids
        raise AssertionError(f"no group with {n_takes} takes: {groups}")

    # ── grouping / take_number ──


    # ── DELETE presentation ──

    def test_delete_presentation_removes_all_takes(self):
        pid, sids = self._pid(2)
        with self.app.test_request_context():
            request.user_id = self.UID
            resp, status = v2_user_sessions.v2_user_delete_presentation.__wrapped__(pid)
        self.assertEqual(status, 200)
        self.assertEqual(resp.get_json()["deleted_sessions"], 2)
        self.assertEqual({s for s, _ in self.deleted_sessions}, {"s1", "s2"})


    # ── DELETE take ──


if __name__ == "__main__":
    unittest.main()
