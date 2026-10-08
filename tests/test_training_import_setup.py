"""Set-up of a training import: complete means topic and language, the save
keeps analysis keys, and an unfinished import serves no moments."""
from __future__ import annotations

from unittest.mock import patch

from flask import Flask, request

import routes.v2.coach as route
from config import Config
from services.corpus_coach_queue import corpus_queue_open, queued_corpus_clip
from services.corpus_split import speaker_key_for
from services.training_import_setup import apply_setup, parse_setup, setup_complete

SID = "11111111-1111-1111-1111-111111111111"
SNIPPET_ID = "22222222-2222-2222-2222-222222222222"


class FakeTakes:
    def __init__(self, sessions: dict, ok: bool = True) -> None:
        self.sessions = sessions
        self.ok = ok
        self.writes: list = []

    def set_session_intake_context(self, sid: str, ctx: dict) -> bool:
        self.writes.append((sid, dict(ctx)))
        if not self.ok:
            return False
        self.sessions[sid]["intake_context"] = dict(ctx)
        return True


class FakeDb:
    def __init__(self, ok: bool = True) -> None:
        self.sessions: dict = {}
        self.takes = FakeTakes(self.sessions, ok=ok)

    def v2_get_session_by_id(self, session_id: str):
        row = self.sessions.get(str(session_id))
        return dict(row) if row else None


def _import_row(ctx: dict | None = None, source: str = "training_import") -> dict:
    return {
        "id": SID,
        "source": source,
        "intake_context": {
            "label_queue_selection": [{"snippet_id": SNIPPET_ID}],
            "duration_sec": 90,
            "archived_at": "2026-10-01T00:00:00Z",
            **(ctx or {}),
        },
    }


def test_setup_complete_requires_topic_and_language():
    assert setup_complete({"topic": "Focus", "language": "pl"}) is True
    assert setup_complete({"language": "pl"}) is False
    assert setup_complete({"topic": "   ", "language": "pl"}) is False
    assert setup_complete({"topic": "Focus"}) is False
    assert setup_complete(["topic", "pl"]) is False
    assert setup_complete(None) is False


def test_parse_setup_accepts_a_valid_body_and_normalises_language():
    fields, err = parse_setup({
        "topic": " Focus ",
        "language": "PL",
        "speaker_label": " Ada ",
        "source": " desk ",
    })
    assert err is None
    assert fields == {
        "topic": "Focus",
        "language": "pl",
        "speaker_label": "Ada",
        "source_note": "desk",
    }


def test_parse_setup_rejects_bad_language_topic_speaker_and_body():
    assert parse_setup({"topic": "Focus", "language": "pol"})[1] == (
        "LANGUAGE_REQUIRED")
    assert parse_setup({"topic": "Focus", "language": ""})[1] == (
        "LANGUAGE_REQUIRED")
    assert parse_setup({"language": "pl"})[1] == "TOPIC_REQUIRED"
    assert parse_setup({"topic": "x" * 201, "language": "pl"})[1] == (
        "TOPIC_REQUIRED")
    assert parse_setup({
        "topic": "Focus", "language": "pl", "speaker_label": 5,
    })[1] == "INVALID_INPUT"
    assert parse_setup(["topic", "pl"])[1] == "INVALID_INPUT"


def test_apply_setup_saves_fields_and_keeps_analysis_keys():
    db = FakeDb()
    db.sessions[SID] = _import_row()
    body = {
        "topic": "Focus",
        "language": "pl",
        "speaker_label": "Ada",
        "source": "desk mic",
    }
    with patch("services.corpus_split.assign_speaker_split") as assign:
        status, payload = apply_setup(db, SID, body)
    assert status == 200
    assert payload == {
        "session_id": SID,
        "topic": "Focus",
        "language": "pl",
        "speaker_label": "Ada",
        "source": "desk mic",
        "setup_complete": True,
    }
    written = db.takes.writes[0][1]
    assert written["label_queue_selection"] == [{"snippet_id": SNIPPET_ID}]
    assert written["duration_sec"] == 90
    assert written["archived_at"] == "2026-10-01T00:00:00Z"
    assert written["source_note"] == "desk mic"
    assert len(db.takes.writes) == 1
    assign.assert_called_once_with(db, speaker_key_for("Ada", SID))


def test_apply_setup_clearing_speaker_removes_the_key():
    db = FakeDb()
    db.sessions[SID] = _import_row({"speaker_label": "Ada", "source_note": "x"})
    with patch("services.corpus_split.assign_speaker_split"):
        status, payload = apply_setup(db, SID, {
            "topic": "Focus",
            "language": "pl",
            "speaker_label": "",
            "source": "",
        })
    assert status == 200
    assert payload["speaker_label"] is None
    assert payload["source"] is None
    written = db.takes.writes[0][1]
    assert "speaker_label" not in written
    assert "source_note" not in written
    assert len(db.takes.writes) == 1


def test_apply_setup_does_not_assign_when_the_speaker_key_is_unchanged():
    db = FakeDb()
    db.sessions[SID] = _import_row({"speaker_label": "Ada", "topic": "Old"})
    with patch("services.corpus_split.assign_speaker_split") as assign:
        status, _payload = apply_setup(db, SID, {
            "topic": "Focus",
            "language": "pl",
            "speaker_label": "Ada",
        })
    assert status == 200
    assign.assert_not_called()
    assert len(db.takes.writes) == 1


def test_apply_setup_not_found_not_an_import_and_failed_write():
    missing, not_import, failed = FakeDb(), FakeDb(), FakeDb(ok=False)
    not_import.sessions[SID] = _import_row(source="audit_upload")
    failed.sessions[SID] = _import_row()
    assert apply_setup(missing, SID, {"topic": "Focus", "language": "pl"})[0] == 404
    status, payload = apply_setup(
        not_import, SID, {"topic": "Focus", "language": "pl"})
    assert status == 409
    assert payload == {"code": "NOT_AN_IMPORT"}
    assert apply_setup(
        failed, SID, {"topic": "Focus", "language": "pl"}) == (
            500, {"code": "SERVER_ERROR"})
    assert failed.takes.writes  # the write was attempted once and refused


def test_unfinished_import_serves_no_queue_and_no_clip():
    bare = {"id": SID, "source": "training_import",
            "intake_context": {"topic": "Focus"}}
    done = {"id": SID, "source": "training_import",
            "intake_context": {"topic": "Focus", "language": "pl"}}
    with patch("config.Config.TRAINING_IMPORT_ENABLED", True):
        assert corpus_queue_open(bare) is False
        assert corpus_queue_open(done) is True
    snippet = {"id": SNIPPET_ID, "session_id": SID}
    session = {
        "id": SID,
        "source": "training_import",
        "intake_context": {
            "label_queue_selection": [{
                "snippet_id": SNIPPET_ID,
                "policy_version": "p",
                "reason": "random",
                "sampling_probability": 0.5,
            }],
        },
    }

    class ClipDb:
        def get_snippet_by_id(self, snippet_id: str):
            return snippet if str(snippet_id) == SNIPPET_ID else None

        def v2_get_session_by_id(self, session_id: str):
            return session if str(session_id) == SID else None

    assert queued_corpus_clip(ClipDb(), SNIPPET_ID) == (None, None)


def test_put_setup_route_saves_and_rejects_a_bad_uuid():
    app = Flask(__name__)
    fake = FakeDb()
    fake.sessions[SID] = _import_row()
    body = {"topic": "Focus", "language": "pl", "speaker_label": "Ada",
            "source": "desk"}
    with app.test_request_context(
            f"/v2/coach/training-imports/{SID}", method="PUT", json=body):
        request.user_id = "coach-1"
        with patch.object(route, "db", fake), patch(
                "services.corpus_split.assign_speaker_split"):
            response, status = route.v2_coach_training_import_setup.__wrapped__(
                SID)
    assert status == 200
    assert response.get_json()["setup_complete"] is True
    assert response.get_json()["source"] == "desk"
    with app.test_request_context(
            "/v2/coach/training-imports/not-a-uuid", method="PUT", json=body):
        request.user_id = "coach-1"
        with patch.object(route, "db", fake):
            response, status = route.v2_coach_training_import_setup.__wrapped__(
                "not-a-uuid")
    assert status == 400
    assert response.get_json()["code"] == "INVALID_INPUT"


def test_post_import_stays_disabled_and_the_default_is_off():
    assert Config.TRAINING_IMPORT_ENABLED is False
    app = Flask(__name__)
    with patch("config.Config.TRAINING_IMPORT_ENABLED", False):
        with app.test_request_context(
                "/v2/coach/training-imports", method="POST"):
            result = route.v2_coach_training_import()
    response, status = result[0], result[1]
    assert status == 410
    assert response.get_json()["code"] == "PHASE2_DISABLED"
