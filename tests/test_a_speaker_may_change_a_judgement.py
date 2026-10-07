"""A speaker may change a judgement; the first answer stays (D-FW-9; 0440;
founder QA1 A, N51.5).

Pins: a different second Confident Voice answer is stored beside the first
(never 409 any more, never an overwrite); going back to the first answer
after a change is a new revision too; a true replay stays a replay; a
rewrite's answer is still final; every reader's row carries the latest
answer with the first beside it, and an unreadable revision table leaves
the first answers; the Album route and coach routing follow the latest
answer; the canonical ledger and the spend keep the first resolution."""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from unittest.mock import patch

from flask import Flask, request

from services import judgement_follow_up as jf
from services.db import DatabaseService

ROOT = Path(__file__).resolve().parents[1]
TAKE = str(uuid.uuid4())
OWNER = str(uuid.uuid4())
SNIP = str(uuid.uuid4())


# ── the readers see the latest answer ────────────────────────────────────

class _Query:
    def __init__(self, data, error=None):
        self.data, self.error = data, error
        self.filters: list = []

    def select(self, *_a):
        return self

    def in_(self, column, values):
        self.filters.append((column, list(values)))
        return self

    def execute(self):
        if self.error:
            raise self.error
        return self


class _Client:
    def __init__(self, revisions, error=None):
        self.query = _Query(revisions, error)

    def table(self, name):
        assert name == "take_feedback_self_report_revision"
        return self.query


def _latest(rows, revisions, error=None):
    from types import SimpleNamespace
    client = _Client(revisions, error)
    out = DatabaseService._latest_self_reports(
        SimpleNamespace(client=client), rows)  # type: ignore[arg-type]
    return out, client


FIRST = {"id": 7, "feedback_family": "confident_voice", "response": "no",
         "snippet_id": SNIP, "feedback_id": "f-1"}
REWRITE = {"id": 8, "feedback_family": "rewrite_clarity",
           "response": "keep_wording", "feedback_id": "f-2"}


def test_the_readers_get_the_latest_answer_and_keep_the_first():
    out, client = _latest([FIRST, REWRITE], [
        {"report_id": 7, "response": "in_between", "revision": 1, "created_at": "t1"},
        {"report_id": 7, "response": "yes", "revision": 2, "created_at": "t2"},
    ])
    assert out[0] == {**FIRST, "response": "yes", "first_response": "no",
                      "revised_at": "t2"}
    assert out[1] == REWRITE
    # Only Confident Voice judgements are looked up.
    assert client.query.filters == [("report_id", [7])]


def test_no_revision_no_change_and_an_unreadable_table_keeps_the_first():
    out, _ = _latest([FIRST], [])
    assert out == [FIRST]
    out, _ = _latest([FIRST], None, error=RuntimeError("missing"))
    assert out == [FIRST]
    out, client = _latest([REWRITE], [])
    assert out == [REWRITE] and client.query.filters == []


def test_the_three_answer_readers_overlay_and_the_writer_is_the_rpc():
    source = (ROOT / "services/db.py").read_text()
    for name in ("def list_take_feedback_self_reports(",
                 "def list_take_feedback_self_reports_by_snippet(",
                 "def list_confident_voice_self_reports("):
        body = source[source.index(name):]
        body = body[:body.index("\n    def ", 10)]
        assert "self._latest_self_reports(" in body, name
    body = source[source.index("def revise_take_feedback_self_report("):]
    body = body[:body.index("\n    def ", 10)]
    assert '"revise_take_feedback_response_v1"' in body
    assert ".update(" not in body and ".upsert(" not in body


# ── coach routing follows the latest answer ──────────────────────────────

class _Requests:
    def __init__(self, request=None):
        self.request = request
        self.kinds: list = []
        self.raised: list = []

    def get_exercise_coach_request(self, _take, _snip):
        return self.request

    def set_exercise_coach_request_answer_kind(self, **kwargs):
        self.kinds.append(kwargs)
        return {"id": "req"}

    def get_confident_voice_exercise_assignment(self, *_a):
        return None

    def request_exercise_from_coach(self, **kwargs):
        self.raised.append(kwargs)
        return {"id": "req", **kwargs}


def _revise(db, answer, *, read="weak", fired=False):
    clip = {"read": read, "observed": {"rushing"} if fired else set(),
            "verdict": {"pattern": "p"}, "snippet": {}}
    with patch.object(jf, "_clip_read", lambda *_a: clip), \
            patch("config.Config.JUDGEMENT_AFTER_FEEDBACK_ENABLED", False), \
            patch.object(jf, "_raise_request",
                         lambda _db, **kwargs: bool(db.raised.append(kwargs)) or True):
        return jf.follow_up_for_revision(
            db, take_session_id=TAKE, snippet_id=SNIP, owner_user_id=OWNER,
            answer=answer)


def test_an_unanswered_request_takes_the_latest_answers_kind():
    db = _Requests({"id": "req", "kind": "ambiguity", "resolution": None})
    assert _revise(db, "no") == "rewrite"
    assert db.kinds == [{"take_session_id": TAKE, "snippet_id": SNIP,
                         "answer_kind": "rewrite", "only_if_unset": False}]
    assert db.raised == []


def test_a_request_the_coach_answered_keeps_the_coachs_answer():
    db = _Requests({"id": "req", "kind": "ambiguity", "resolution": "note_written"})
    _revise(db, "no")
    assert db.kinds == []


def test_audio_unclear_changes_nothing_and_no_request_rises_the_ordinary_way():
    db = _Requests({"id": "req", "kind": "praise", "resolution": None})
    assert _revise(db, "audio_unclear") == "none"
    assert db.kinds == []
    fresh = _Requests(None)
    _revise(fresh, "no", fired=True)
    assert fresh.raised and fresh.raised[0]["kind"] == "error"


# ── the route ─────────────────────────────────────────────────────────────

class _RouteDb:
    def __init__(self, first_outcome="conflict", change=None):
        self.first_outcome = first_outcome
        self.change = change
        self.album: list = []
        self.canonical: list = []
        self.revise_calls: list = []

    def v2_get_session_by_id(self, _sid):
        return {"id": TAKE, "user_id": OWNER, "arc_id": "arc-1",
                "project_id": str(uuid.uuid4())}

    def insert_take_feedback_self_report(self, **kwargs):
        row = {**kwargs, "id": 7, "snippet_id": SNIP}
        return {"outcome": self.first_outcome, "row": row,
                "selected_keys": []}

    def revise_take_feedback_self_report(self, **kwargs):
        self.revise_calls.append(kwargs)
        return self.change

    def record_canonical_feedback_decision(self, **kwargs):
        self.canonical.append(kwargs)
        return {"id": "d"}

    def get_snippet_by_id(self, _sid):
        return {"metrics": {"piece": {"slide_index": 1}}}

    class takes:  # noqa: N801 -- the attribute the route reads
        @staticmethod
        def get_arc_sessions(_arc):
            return []

    def upsert_owner_voice_album_route(self, **kwargs):
        self.album.append(kwargs)
        return True


def _post(db, family="confident_voice", response="yes"):
    from routes.v2 import user_sessions as route

    body = {"feedback_id": "f-1", "feedback_family": family, "response": response}
    parsed = {"feedback_id": "f-1", "feedback_family": family,
              "response": response, "snippet_id": None}
    app = Flask(__name__)
    with patch.object(route, "db", db), \
            patch("services.take_feedback_responses.parse_feedback_response",
                  lambda _b: (dict(parsed), None)), \
            patch("services.voice_album.refresh_voice_album") as refresh, \
            patch("services.judgement_follow_up.follow_up_for_revision",
                  return_value="rewrite") as revision_follow, \
            patch("services.judgement_follow_up.follow_up_for_judgement",
                  return_value="praise") as first_follow, \
            patch("services.intervention_spend.spend") as spend, \
            patch.object(route, "text_update_for_answer", lambda *a, **k: {}):
        with app.test_request_context("/v2/x", method="POST", json=body):
            request.user_id = OWNER
            response, status = route.v2_post_take_feedback_response.__wrapped__(TAKE)
    return status, response.get_json(), {
        "refresh": refresh, "revision": revision_follow, "first": first_follow,
        "spend": spend}


def test_a_changed_judgement_is_stored_beside_the_first():
    change = {"outcome": "revised", "row": {
        "id": 7, "snippet_id": SNIP, "response": "yes", "first_response": "no",
        "revision": 1}}
    db = _RouteDb("conflict", change)
    status, body, calls = _post(db, response="yes")
    assert status == 200
    assert body["revised"] is True and body["response"] == "yes"
    assert body["follow_up"] == "rewrite"
    assert db.revise_calls == [{"take_session_id": TAKE, "owner_user_id": OWNER,
                                "feedback_id": "f-1", "response": "yes"}]
    # The Album and coach routing follow the latest answer...
    assert db.album[-1]["response"] == "yes"
    calls["refresh"].assert_called_once()
    calls["revision"].assert_called_once()
    assert calls["revision"].call_args.kwargs["answer"] == "yes"
    calls["first"].assert_not_called()
    # ...and the first resolution stays the canonical one.
    assert db.canonical == []
    calls["spend"].assert_not_called()


def test_going_back_to_the_first_answer_is_a_revision_too():
    change = {"outcome": "revised", "row": {"id": 7, "snippet_id": SNIP,
                                            "response": "no", "revision": 2}}
    db = _RouteDb("replayed", change)
    status, body, _ = _post(db, response="no")
    assert status == 200 and body["revised"] is True


def test_a_true_replay_stays_the_ordinary_replay():
    change = {"outcome": "replayed", "row": {"id": 7, "snippet_id": SNIP,
                                             "response": "no", "revision": 0}}
    db = _RouteDb("replayed", change)
    status, body, calls = _post(db, response="no")
    assert status == 200 and "revised" not in body
    calls["first"].assert_called_once()


def test_a_rewrites_answer_is_still_final_and_a_failed_revision_is_an_error():
    db = _RouteDb("conflict", None)
    status, body, _ = _post(db, family="rewrite_clarity", response="keep_wording")
    assert (status, body["code"]) == (409, "RESPONSE_ALREADY_FINAL")
    assert db.revise_calls == []
    status, body, _ = _post(_RouteDb("conflict", None))
    assert (status, body["code"]) == (500, "V2_ERROR")
    status, body, _ = _post(_RouteDb("conflict", {"outcome": "not_revisable"}))
    assert (status, body["code"]) == (409, "RESPONSE_ALREADY_FINAL")


def test_the_migration_is_listed_and_the_purge_knows_the_table():
    from services.data_purge_registry import DEPENDENCIES

    manifest = (ROOT / "migrations" / "manifest.txt").read_text()
    assert "0440\ta_speaker_may_change_a_judgement.sql" in manifest
    sql = (ROOT / "migrations" / "a_speaker_may_change_a_judgement.sql").read_text()
    code = re.sub(r"--.*", "", sql).upper()
    assert "CREATE TABLE IF NOT EXISTS PUBLIC.TAKE_FEEDBACK_SELF_REPORT_REVISION" in code
    assert "ENABLE ROW LEVEL SECURITY" in code
    for destructive in ("DROP TABLE", "DROP COLUMN", "DELETE FROM", "TRUNCATE",
                        "UPDATE PUBLIC.TAKE_FEEDBACK_SELF_REPORT "):
        assert destructive not in code
    dependency = {d.relation: d for d in DEPENDENCIES}["take_feedback_self_report_revision"]
    assert (dependency.selector_column, dependency.locator_kind,
            dependency.disposition) == ("take_session_id", "take", "delete")


def test_the_moment_read_gives_the_fe_the_latest_answer():
    """What the FE presses when ‹ reopens the judgement (D-FW-9 FE half)."""
    from services.owner_feedback_answers import owner_answers

    class _Db:
        def v2_get_session_by_id(self, _sid):
            return {"id": TAKE, "user_id": OWNER}

        def list_take_feedback_self_reports(self, _take, _owner):
            return [{**FIRST, "response": "yes", "first_response": "no",
                     "created_at": "t0", "revised_at": "t2"}]

    assert owner_answers(_Db(), TAKE, OWNER) == [{
        "feedback_id": "f-1", "feedback_family": "confident_voice",
        "response": "yes", "at": "t2"}]
