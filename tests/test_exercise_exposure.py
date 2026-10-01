"""The "exercise rendered" confirmation (0387; label spec exercise-adequacy-label-v2).

Pins:
  * only the moment's owner can confirm, and only the exercise the draw chose;
  * a moment with no draw (nothing fitted, coach-shared) answers
    recorded:false without an error, so the client can send it for any card;
  * nothing but "recorded" comes back to the speaker;
  * the route is authenticated and behind the exercise purpose gate.
"""
from __future__ import annotations

import pathlib
import unittest

from services import exercise_exposure as ex

ROOT = pathlib.Path(__file__).resolve().parent.parent


class _Db:
    def __init__(self, *, owner="user-1", refuse=None):
        self.owner = owner
        self.refuse = refuse
        self.calls = []

    def get_snippet_by_id(self, snippet_id):
        return {"id": snippet_id, "session_id": "take-1"} if snippet_id != "gone" else None

    def v2_get_session_by_id(self, session_id):
        return {"id": session_id, "user_id": self.owner}

    def record_exercise_rendered(self, **kwargs):
        self.calls.append(kwargs)
        if self.refuse:
            raise RuntimeError(self.refuse)
        return {"id": "exp-1", "rendered_at": "2026-09-28T16:00:00Z",
                "exercise_id": kwargs["exercise_id"]}


def _send(db, body=None, user="user-1", snippet="snip-1"):
    return ex.record_rendered(db, user_id=user, snippet_id=snippet,
                              body={"exercise_id": "room"} if body is None else body)


class RecordRenderedTests(unittest.TestCase):
    def test_the_owner_s_confirmation_is_recorded(self):
        db = _Db()
        self.assertEqual(_send(db), (200, {"recorded": True}))
        self.assertEqual(db.calls, [{"owner_user_id": "user-1",
                                     "take_session_id": "take-1",
                                     "snippet_id": "snip-1",
                                     "exercise_id": "room"}])

    def test_nothing_else_reaches_the_speaker(self):
        status, payload = _send(_Db())
        self.assertEqual(set(payload), {"recorded"})

    def test_someone_else_s_moment_is_not_found(self):
        db = _Db(owner="someone-else")
        self.assertEqual(_send(db)[0], 404)
        self.assertEqual(db.calls, [])
        self.assertEqual(_send(_Db(), snippet="gone")[0], 404)

    def test_a_moment_with_no_draw_is_quietly_not_an_exposure(self):
        status, payload = _send(_Db(refuse="EXERCISE_RENDERED_NOT_DRAWN"))
        self.assertEqual((status, payload), (200, {"recorded": False}))

    def test_the_wrong_exercise_is_refused(self):
        status, payload = _send(_Db(refuse="EXERCISE_RENDERED_WRONG_EXERCISE"))
        self.assertEqual((status, payload["code"]), (409, "EXERCISE_OFFER_STALE"))

    def test_the_database_owner_check_is_honoured_too(self):
        status, _ = _send(_Db(refuse="EXERCISE_RENDERED_NOT_OWNER"))
        self.assertEqual(status, 404)

    def test_an_exercise_id_is_required(self):
        for body in ({}, {"exercise_id": ""}, {"exercise_id": 7}, None, "x"):
            status, _ = ex.record_rendered(_Db(), user_id="user-1",
                                           snippet_id="snip-1", body=body)
            self.assertEqual(status, 400, body)

    def test_an_unknown_failure_is_raised_not_swallowed(self):
        with self.assertRaises(RuntimeError):
            _send(_Db(refuse="connection reset"))


class RouteTests(unittest.TestCase):
    def test_authenticated_and_behind_the_purpose_gate(self):
        source = (ROOT / "routes/v2/user_sessions.py").read_text()
        start = source.index('@v2_bp.route("/user/snippets/<snippet_id>/exercise-rendered"')
        head = source[start:source.index("def v2_exercise_rendered", start)]
        self.assertIn("@require_auth", head)
        self.assertIn(
            '@operational_purpose_disabled("personalized_exercise_recommendation")',
            head)
