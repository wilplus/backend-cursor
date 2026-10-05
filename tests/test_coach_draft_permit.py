"""A coach's AI draft takes the speaker's permit (second plan, Phase 1,
founder "go" 2026-10-05).

The coach's three drafts (a request answer, the Take word, a moment line)
send the speaker's transcript to the provider. They live under /v2/coach/,
outside the core gate, so the call went out with no permit even in enforce
mode. ``speaker_provider_route`` binds each one to the SPEAKER's current
authority: it resolves the Take's owner, requires current authorization and
opens the protected scope every provider call inside reads its permit from.
"""
from __future__ import annotations

import pathlib

import pytest

from routes.v2 import processing_authorization as gate_module
from services import authorized_provider
from services.processing_authorization import (
    ProcessingAuthorizationError,
    ProcessingAuthorizationService,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Sessions:
    client = None

    def __init__(self, row):
        self.row = row

    def v2_get_session_by_id(self, session_id):
        return self.row if self.row and self.row.get("id") == session_id else None


@pytest.fixture
def authority(monkeypatch):
    seen: dict = {}

    def resolve(self, principal_id, *, user_id=None, recording_id=None):
        seen["resolved"] = (principal_id, user_id)
        return principal_id or None

    def require(self, principal_id, *, operation):
        seen["required"] = (principal_id, operation)
        if seen.get("refuse"):
            raise ProcessingAuthorizationError(
                "PROCESSING_AUTHORIZATION_REQUIRED", "Not authorized.", 403)
        return None

    monkeypatch.setattr(ProcessingAuthorizationService,
                        "resolve_acquisition_principal", resolve)
    monkeypatch.setattr(ProcessingAuthorizationService, "require_current", require)
    return seen


def _view(calls):
    @gate_module.speaker_provider_route
    def view(session_id):
        scope = authorized_provider._protected_call_scope.get()
        calls.append(scope)
        return {"ok": True}, 200
    return view


def _call(app_client, view, session_id="take-1"):
    with app_client.application.test_request_context("/"):
        result = view(session_id=session_id)
        if isinstance(result, tuple) and hasattr(result[0], "get_json"):
            return result[0].get_json(), result[1]
        return result


def test_inert_while_the_gate_is_off(app_client, monkeypatch, authority):
    monkeypatch.delenv("PLF1_PROCESSING_AUTHORIZATION_MODE", raising=False)
    calls: list = []
    assert _call(app_client, _view(calls)) == ({"ok": True}, 200)
    assert calls == [None]
    assert "required" not in authority


def test_enforced_the_draft_runs_inside_the_speakers_scope(
        app_client, monkeypatch, authority):
    monkeypatch.setenv("PLF1_PROCESSING_AUTHORIZATION_MODE", "enforce")
    monkeypatch.setattr(gate_module, "db", _Sessions(
        {"id": "take-1", "owner_principal_id": "speaker-p", "user_id": "speaker-u"}))
    calls: list = []
    assert _call(app_client, _view(calls)) == ({"ok": True}, 200)
    assert authority["resolved"] == ("speaker-p", "speaker-u")
    assert authority["required"] == ("speaker-p", "coach_draft")
    scope = calls[0]
    assert scope is not None
    assert scope.adapter.coordinates.acquisition_principal_id == "speaker-p"
    assert scope.adapter.coordinates.take_id == "take-1"
    assert scope.idempotency_prefix.startswith("coach-draft:take-1:")
    # The scope closes with the view.
    assert authorized_provider._protected_call_scope.get() is None


def test_a_speaker_without_authority_gets_no_draft(app_client, monkeypatch, authority):
    monkeypatch.setenv("PLF1_PROCESSING_AUTHORIZATION_MODE", "enforce")
    monkeypatch.setattr(gate_module, "db", _Sessions(
        {"id": "take-1", "owner_principal_id": "speaker-p", "user_id": None}))
    authority["refuse"] = True
    calls: list = []
    body, status = _call(app_client, _view(calls))
    assert status == 403
    assert body["code"] == "PROCESSING_AUTHORIZATION_REQUIRED"
    assert calls == []


def test_an_unknown_take_is_refused_not_sent(app_client, monkeypatch, authority):
    monkeypatch.setenv("PLF1_PROCESSING_AUTHORIZATION_MODE", "enforce")
    monkeypatch.setattr(gate_module, "db", _Sessions(None))
    calls: list = []
    body, status = _call(app_client, _view(calls), session_id="missing")
    assert status == 403
    assert body["code"] == "PROCESSING_PRINCIPAL_UNRESOLVED"
    assert calls == []


def test_a_permit_refused_mid_call_is_answered_with_its_code(
        app_client, monkeypatch, authority):
    monkeypatch.setenv("PLF1_PROCESSING_AUTHORIZATION_MODE", "enforce")
    monkeypatch.setattr(gate_module, "db", _Sessions(
        {"id": "take-1", "owner_principal_id": "speaker-p", "user_id": None}))

    @gate_module.speaker_provider_route
    def view(session_id):
        raise ProcessingAuthorizationError("PROVIDER_PERMIT_INVALID", "No permit.", 403)

    body, status = _call(app_client, view)
    assert (status, body["code"]) == (403, "PROVIDER_PERMIT_INVALID")


@pytest.mark.parametrize("path, view", [
    ("routes/v2/coach.py", "def v2_coach_exercise_request_draft("),
    ("routes/v2/coach_words.py", "def v2_coach_take_word_draft("),
    ("routes/v2/coach_words.py", "def v2_coach_moment_line_draft("),
])
def test_every_coach_draft_route_takes_the_permit(path, view):
    source = (ROOT / path).read_text()
    head = source[:source.index(view)].rsplit("@v2_bp.route", 1)[1]
    assert "@speaker_provider_route" in head, f"{view} sends words without a permit"


def test_the_words_route_does_not_swallow_a_refusal():
    source = (ROOT / "routes/v2/coach_words.py").read_text()
    run = source[source.index("def _run("):source.index("@v2_bp.route")]
    assert run.index("except ProcessingAuthorizationError") < run.index(
        "except Exception")
