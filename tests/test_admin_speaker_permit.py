"""An admin's AI call about a speaker takes the SPEAKER's permit (founder
2026-10-05, N48.1 step 6: "every AI call carries its permission slip").

Two admin tools sent a speaker's own words to the provider with no permit,
no snapshot and no provider record even in enforce mode: the directive
suggestions (``POST /v2/admin/users/<id>/directives-queue/suggest``) and the
next-session icebreaker regenerate (``POST /v2/admin/sessions/<id>/
next-session-icebreaker/regenerate``). ``services.speaker_authority``
resolves the speaker, requires their current authority and runs the call in
the protected scope ``services.llm.chat_complete`` reads its permit from.
Refused → no model call, the house refusal, a warning with exc_info.
"""
from __future__ import annotations

import inspect
import logging
import sys
import types
from types import SimpleNamespace

import pytest

from routes.v2 import admin as admin_routes
from services import authorized_provider
from services import speaker_authority
from services.processing_authorization import (
    ProcessingAuthorizationError,
    ProcessingAuthorizationService,
)
from services.speaker_authority import Speaker, call_as_speaker

USER = "11111111-1111-4111-8111-111111111111"
TAKE = "22222222-2222-4222-8222-222222222222"


class _FakeDB:
    """Only the reads the speaker resolution makes. No create method: an
    admin tool must never mint a principal for the speaker."""
    client = None

    def __init__(self, session=None, owner=None):
        self.session = session
        self.owner = owner
        self.takes = SimpleNamespace(
            get_next_session_icebreaker_row=lambda sid: {"session_id": sid})

    def v2_get_session_by_id(self, session_id):
        if self.session and self.session.get("id") == session_id:
            return dict(self.session)
        return None

    def get_owner_principal_for_user(self, user_id):
        return {"id": self.owner} if self.owner and user_id == USER else None


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


@pytest.fixture
def enforce(monkeypatch):
    monkeypatch.setenv("PLF1_PROCESSING_AUTHORIZATION_MODE", "enforce")


def _scope_now():
    return authorized_provider._protected_call_scope.get()


# ── call_as_speaker ─────────────────────────────────────────────────────

def test_gate_off_calls_through_without_reading_the_speaker(monkeypatch, authority):
    monkeypatch.delenv("PLF1_PROCESSING_AUTHORIZATION_MODE", raising=False)

    def resolve():
        raise AssertionError("the gate-off path must not read the speaker")

    result, refused = call_as_speaker(_FakeDB(), resolve, lambda: _scope_now(),
                                      surface="directive_suggestions")
    assert (result, refused) == (None, None)  # ran, with no scope
    assert "required" not in authority


def test_permitted_call_runs_inside_the_speakers_scope(enforce, authority):
    result, refused = call_as_speaker(
        _FakeDB(), lambda: Speaker("speaker-p", "speaker-u", TAKE),
        _scope_now, surface="next_session_icebreaker")
    assert refused is None
    assert authority["resolved"] == ("speaker-p", "speaker-u")
    assert authority["required"] == ("speaker-p", "admin_draft")
    assert result.adapter.coordinates.acquisition_principal_id == "speaker-p"
    assert result.adapter.coordinates.take_id == TAKE
    assert result.idempotency_prefix.startswith(f"next_session_icebreaker:{TAKE}:")
    assert _scope_now() is None  # the scope closes with the call


def test_refused_speaker_gets_no_model_call_and_a_logged_refusal(
        enforce, authority, caplog):
    authority["refuse"] = True
    calls: list = []
    with caplog.at_level(logging.WARNING, logger="services.speaker_authority"):
        result, refused = call_as_speaker(
            _FakeDB(), lambda: Speaker("speaker-p", None, None),
            lambda: calls.append(1), surface="directive_suggestions")
    assert calls == []
    assert result is None
    assert (refused.code, refused.status) == ("PROCESSING_AUTHORIZATION_REQUIRED", 403)
    record = next(r for r in caplog.records if "refused before the model" in r.message)
    assert record.exc_info is not None


@pytest.mark.parametrize("resolve", [
    lambda: Speaker("", None, None),
    lambda: (_ for _ in ()).throw(RuntimeError("read failed")),
])
def test_an_unresolved_speaker_is_refused_not_sent(enforce, authority, resolve):
    calls: list = []
    result, refused = call_as_speaker(_FakeDB(), resolve, lambda: calls.append(1),
                                      surface="directive_suggestions")
    assert calls == []
    assert refused.code == "PROCESSING_PRINCIPAL_UNRESOLVED"
    assert "required" not in authority


def test_a_permit_refused_mid_call_comes_back_as_the_refusal(
        enforce, authority, caplog):
    def call():
        raise ProcessingAuthorizationError("PROVIDER_PERMIT_INVALID", "No permit.", 403)

    with caplog.at_level(logging.WARNING, logger="services.speaker_authority"):
        result, refused = call_as_speaker(
            _FakeDB(), lambda: Speaker("speaker-p", None, None), call,
            surface="directive_suggestions")
    assert result is None
    assert refused.code == "PROVIDER_PERMIT_INVALID"
    assert any(r.exc_info for r in caplog.records if "mid-call" in r.message)
    assert _scope_now() is None


def test_speaker_of_session_falls_back_to_the_users_principal():
    db = _FakeDB(session={"id": TAKE, "user_id": USER, "owner_principal_id": None},
                 owner="account-p")
    assert speaker_authority.speaker_of_session(db, TAKE) == Speaker(
        "account-p", USER, TAKE)
    db.session["owner_principal_id"] = "take-owner-p"
    assert speaker_authority.speaker_of_session(db, TAKE).owner_principal_id == (
        "take-owner-p")
    assert speaker_authority.speaker_of_session(db, "missing") == Speaker(
        "", None, None)


def test_speaker_of_user_reads_and_never_creates():
    assert speaker_authority.speaker_of_user(_FakeDB(owner="account-p"), USER) == (
        Speaker("account-p", USER, None))
    assert speaker_authority.speaker_of_user(_FakeDB(), USER).owner_principal_id == ""


# ── The two admin routes ────────────────────────────────────────────────

def _call_view(app_client, view, *, body=None, **kwargs):
    raw = inspect.unwrap(view)
    with app_client.application.test_request_context("/", method="POST", json=body or {}):
        from flask import request
        request.user_id = "admin-1"
        out = raw(**kwargs)
    resp, status = out if isinstance(out, tuple) else (out, 200)
    return resp.get_json(), status


@pytest.fixture
def directives(monkeypatch):
    calls: list = []

    def suggest(*, user_id, snippet_id_context=None):
        calls.append(_scope_now())
        return [{"intent_tag": "warm-up", "question": "How did it go?"}]

    monkeypatch.setattr("services.directive_suggestions.suggest_directive_arc", suggest)
    monkeypatch.setattr(admin_routes, "db", _FakeDB(owner="account-p"))
    return calls


def test_directives_gate_off_suggests_as_before(app_client, monkeypatch, directives):
    monkeypatch.delenv("PLF1_PROCESSING_AUTHORIZATION_MODE", raising=False)
    body, status = _call_view(app_client, admin_routes.v2_admin_suggest_directives_queue,
                              user_id=USER)
    assert status == 200 and len(body["rows"]) == 1
    assert directives == [None]


def test_directives_run_under_the_speakers_permit(
        app_client, enforce, authority, directives):
    body, status = _call_view(app_client, admin_routes.v2_admin_suggest_directives_queue,
                              user_id=USER)
    assert status == 200 and len(body["rows"]) == 1
    assert authority["required"] == ("account-p", "admin_draft")
    assert directives[0].adapter.coordinates.acquisition_principal_id == "account-p"


def test_directives_refused_send_nothing(app_client, enforce, authority, directives):
    authority["refuse"] = True
    body, status = _call_view(app_client, admin_routes.v2_admin_suggest_directives_queue,
                              user_id=USER)
    assert status == 403
    assert body == {"code": "PROCESSING_AUTHORIZATION_REQUIRED",
                    "error": "Not authorized."}
    assert directives == []


def test_directives_reach_the_permit_through_the_real_llm_wrapper(
        app_client, enforce, authority, monkeypatch):
    """End to end through services.llm.chat_complete: the permit is asked for
    before any provider client exists, and its refusal is the answer."""
    monkeypatch.setattr(admin_routes, "db", _FakeDB(owner="account-p"))
    monkeypatch.setattr("services.directive_suggestions._build_context_payload",
                        lambda **_: "ctx")
    asked: list = []

    def refuse_permit(self, operation_kind, *, manifest, idempotency_key):
        asked.append((self.coordinates.acquisition_principal_id, manifest["surface"]))
        raise ProcessingAuthorizationError("PROVIDER_PERMIT_INVALID", "No permit.", 403)

    monkeypatch.setattr(authorized_provider.AuthorizedProviderAdapter,
                        "authorize_operation", refuse_permit)

    def no_client(*_a, **_k):
        raise AssertionError("a provider client was built without a permit")

    monkeypatch.setattr("services.openai_service.OpenAIService", no_client)
    body, status = _call_view(app_client, admin_routes.v2_admin_suggest_directives_queue,
                              user_id=USER)
    assert (status, body["code"]) == (403, "PROVIDER_PERMIT_INVALID")
    assert asked == [("account-p", "directive_suggestions")]


@pytest.fixture
def icebreaker(monkeypatch):
    calls: list = []

    def generate(session_id, *, overwrite=False):
        calls.append((_scope_now(), overwrite))
        return "How did the launch land?"

    # A stand-in module, not a patched attribute: importing the real one here
    # would bind it to the real services.db before test_next_session_
    # icebreaker stubs that module (its setUpModule), polluting its run.
    fake = types.ModuleType("services.next_session_icebreaker")
    fake.generate_next_session_icebreaker = generate
    monkeypatch.setitem(sys.modules, "services.next_session_icebreaker", fake)
    monkeypatch.setattr(admin_routes, "db", _FakeDB(
        session={"id": TAKE, "user_id": USER, "owner_principal_id": "speaker-p"}))
    monkeypatch.setattr(admin_routes, "_build_icebreaker_response",
                        lambda sid, row: {"session_id": sid})
    return calls


def test_icebreaker_gate_off_regenerates_as_before(app_client, monkeypatch, icebreaker):
    monkeypatch.delenv("PLF1_PROCESSING_AUTHORIZATION_MODE", raising=False)
    body, status = _call_view(
        app_client, admin_routes.v2_admin_regenerate_next_session_icebreaker,
        session_id=TAKE)
    assert (status, body) == (200, {"session_id": TAKE})
    assert icebreaker == [(None, True)]


def test_icebreaker_runs_under_the_takes_speaker(app_client, enforce, authority, icebreaker):
    body, status = _call_view(
        app_client, admin_routes.v2_admin_regenerate_next_session_icebreaker,
        session_id=TAKE)
    assert status == 200
    assert authority["resolved"] == ("speaker-p", USER)
    scope, overwrite = icebreaker[0]
    assert overwrite is True
    assert scope.adapter.coordinates.take_id == TAKE
    assert scope.adapter.coordinates.acquisition_principal_id == "speaker-p"


def test_icebreaker_refused_sends_nothing(app_client, enforce, authority, icebreaker):
    authority["refuse"] = True
    body, status = _call_view(
        app_client, admin_routes.v2_admin_regenerate_next_session_icebreaker,
        session_id=TAKE)
    assert status == 403
    assert body["code"] == "PROCESSING_AUTHORIZATION_REQUIRED"
    assert icebreaker == []
