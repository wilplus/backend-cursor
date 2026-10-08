"""The Lounge bubble's "new" (D-FW-5; 0439; the Feedback walk lock, flow 1
and "Amendments: Lounge").

Pins: the Lounge's first page carries one yes/no per project, never a
count; a failed read is no flag and the Lounge still mounts; an older page
carries nothing; the POST marks the Take's note or one moment seen, refuses
bad ids and someone else's Take; the purge knows the table."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest

from services import coach_feedback_signal as signal

ROOT = Path(__file__).resolve().parents[1]
TAKE = str(uuid.uuid4())
SNIPPET = str(uuid.uuid4())


class _Db:
    def __init__(self, flags=None, raises=None):
        self.flags = flags or {}
        self.raises = raises
        self.marked: list = []

    def new_coach_feedback_by_project(self, user_id):
        if self.raises:
            raise self.raises
        return self.flags

    def mark_coach_feedback_seen(self, *, user_id, take_session_id, item):
        if self.raises:
            raise self.raises
        self.marked.append((user_id, take_session_id, item))
        return "2026-10-07T10:00:00+00:00"


def test_one_boolean_per_project_never_a_count():
    flags = signal.lounge_flags(_Db({"arc-1": True, "arc-2": False, "arc-3": 2}), "u")
    assert flags == {"arc-1": True, "arc-2": False, "arc-3": False}
    assert all(isinstance(value, bool) for value in flags.values())


def test_a_failed_read_is_no_flag():
    assert signal.lounge_flags(_Db(raises=RuntimeError("down")), "u") == {}
    assert signal.lounge_flags(object(), "u") == {}
    assert signal.lounge_flags(_Db({"a": True}), None) == {}


def test_the_walk_marks_the_take_note_or_one_moment_seen():
    db = _Db()
    assert signal.mark_seen(db, "u", {"take_session_id": TAKE}) == (200, {"seen": True})
    assert signal.mark_seen(db, "u", {"take_session_id": TAKE, "snippet_id": SNIPPET}) == (
        200, {"seen": True})
    assert db.marked == [("u", TAKE, "take_word"), ("u", TAKE, SNIPPET)]


@pytest.mark.parametrize("body", [
    None, {}, {"take_session_id": "not-a-take"},
    {"take_session_id": TAKE, "snippet_id": "take_word"},
    {"take_session_id": TAKE, "snippet_id": ""},
])
def test_bad_ids_are_refused_before_any_write(body):
    db = _Db()
    status, out = signal.mark_seen(db, "u", body)
    assert (status, out["code"]) == (400, "INVALID_INPUT")
    assert db.marked == []


def test_someone_else_s_take_is_not_found_and_a_fault_is_an_error():
    not_owned = _Db(raises=RuntimeError({"message": "COACH_FEEDBACK_TAKE_NOT_OWNED"}))
    assert signal.mark_seen(not_owned, "u", {"take_session_id": TAKE}) == (
        404, {"code": "NOT_FOUND", "error": "take not found"})
    down = _Db(raises=RuntimeError("connection reset"))
    assert signal.mark_seen(down, "u", {"take_session_id": TAKE})[0] == 500


def test_the_routes_are_authenticated_and_wired():
    source = (ROOT / "routes/v2/lounge.py").read_text()
    head = source[source.index('@v2_bp.route("/user/coach-feedback/seen"'):]
    head = head[:head.index("def ")]
    assert 'methods=["POST"]' in head and "@require_auth" in head


def test_the_lounge_page_carries_the_flags_on_the_first_page_only():
    from unittest.mock import patch

    from flask import Flask, request

    from routes.v2 import lounge

    class _LoungeDb(_Db):
        def get_lounge_messages_page(self, user_id, *, limit, before):
            return []

    app = Flask(__name__)
    with patch.object(lounge, "db", _LoungeDb({"arc-1": True, "arc-2": False})):
        with app.test_request_context("/v2/user/lounge/messages"):
            request.user_id = "u"
            response, status = lounge.v2_user_lounge_messages_get.__wrapped__()
        assert status == 200
        assert response.get_json()["new_coach_feedback"] == {"arc-1": True, "arc-2": False}
        with app.test_request_context(
                "/v2/user/lounge/messages?before=2026-10-01T00:00:00Z"):
            request.user_id = "u"
            response, status = lounge.v2_user_lounge_messages_get.__wrapped__()
        assert status == 200
        assert "new_coach_feedback" not in response.get_json()
    with patch.object(lounge, "db", _LoungeDb(raises=RuntimeError("down"))):
        with app.test_request_context("/v2/user/lounge/messages"):
            request.user_id = "u"
            response, status = lounge.v2_user_lounge_messages_get.__wrapped__()
    # A failed read never stops the Lounge: the page, with no flag.
    assert status == 200 and response.get_json()["new_coach_feedback"] == {}


def test_the_seen_route_reaches_the_service():
    from unittest.mock import patch

    from flask import Flask, request

    from routes.v2 import lounge

    db = _Db()
    app = Flask(__name__)
    with patch.object(lounge, "db", db):
        with app.test_request_context("/v2/x", method="POST",
                                      json={"take_session_id": TAKE}):
            request.user_id = "u"
            response, status = lounge.v2_user_coach_feedback_seen.__wrapped__()
        assert (status, response.get_json()) == (200, {"seen": True})
        with app.test_request_context("/v2/x", method="POST", json={}):
            request.user_id = "u"
            assert lounge.v2_user_coach_feedback_seen.__wrapped__()[1] == 400
    assert db.marked == [("u", TAKE, "take_word")]


def test_the_migration_is_listed_and_the_purge_knows_the_table():
    from services import data_purge_project_scope as scope
    from services.data_purge_registry import DEPENDENCIES

    manifest = (ROOT / "migrations" / "manifest.txt").read_text()
    assert "0439\tnew_coach_feedback_waits_on_the_lounge_bubble.sql" in manifest
    sql = (ROOT / "migrations" / "new_coach_feedback_waits_on_the_lounge_bubble.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS public.coach_feedback_seen" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "count(" not in re.sub(r"--.*", "", sql).lower()
    assert "DROP " not in re.sub(r"--.*", "", sql).upper()
    selectors = {(d.relation, d.selector_column, d.locator_kind) for d in DEPENDENCIES
                 if d.relation == "coach_feedback_seen"}
    assert selectors == {("coach_feedback_seen", "take_session_id", "take"),
                         ("coach_feedback_seen", "owner_user_id", "user")}
    assert scope.PROJECT_SELECTORS["coach_feedback_seen_by_owner"] == (
        "take_session_id", "take")
