"""
STORY    As a speaker, I want any AI call an admin makes about me to run under
         my own processing permit, and be refused when I have none, so that
         my words never reach a provider without my authority (processing
         authorization on the critical path).
OUTCOME
  O1  Directive suggestions: with my authority the model call runs inside
      the protected scope bound to MY principal; a refused permit answers
      403 before any provider client exists.
  O2  Icebreaker regenerate: with my authority it runs inside my scope;
      without it the route answers 403 and the model is never called.
  O3  No principal is minted for me: the fake database has no create method.
PROVES   O1 -> test_directives_run_under_the_speakers_scope
               test_directives_reach_the_permit_through_the_real_llm_wrapper
         O2 -> test_the_icebreaker_runs_under_the_speakers_scope
               test_the_icebreaker_is_refused_without_the_speakers_authority
         O3 -> every test (_FakeDB)
WHY      Founder 2026-10-05, N48.1 step 6: "every AI call carries its
         permission slip"; the two admin tools called the provider with none.
"""
from __future__ import annotations

import inspect
import sys
import types
from types import SimpleNamespace

import pytest

from routes.v2 import admin as admin_routes
from services import authorized_provider
from services.processing_authorization import (
    ProcessingAuthorizationError,
    ProcessingAuthorizationService,
)

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


def test_directives_run_under_the_speakers_scope(app_client, enforce, authority,
                                                 directives):
    body, status = _call_view(app_client, admin_routes.v2_admin_suggest_directives_queue,
                              user_id=USER)
    assert status == 200
    assert body["rows"] == [{"intent_tag": "warm-up", "question": "How did it go?"}]
    assert authority["required"] == ("account-p", "admin_draft")
    assert len(directives) == 1 and directives[0] is not None
    assert directives[0].adapter.coordinates.acquisition_principal_id == "account-p"


def test_the_icebreaker_runs_under_the_speakers_scope(app_client, enforce, authority,
                                                      icebreaker):
    body, status = _call_view(
        app_client, admin_routes.v2_admin_regenerate_next_session_icebreaker,
        session_id=TAKE)
    assert (status, body) == (200, {"session_id": TAKE})
    assert authority["required"] == ("speaker-p", "admin_draft")
    assert len(icebreaker) == 1
    scope, overwrite = icebreaker[0]
    assert overwrite is True and scope is not None
    assert scope.adapter.coordinates.acquisition_principal_id == "speaker-p"
    assert scope.adapter.coordinates.take_id == TAKE


def test_the_icebreaker_is_refused_without_the_speakers_authority(
        app_client, enforce, authority, icebreaker, caplog):
    authority["refuse"] = True
    with caplog.at_level("WARNING", logger="services.speaker_authority"):
        body, status = _call_view(
            app_client, admin_routes.v2_admin_regenerate_next_session_icebreaker,
            session_id=TAKE)
    assert (status, body["code"]) == (403, "PROCESSING_AUTHORIZATION_REQUIRED")
    assert authority["required"] == ("speaker-p", "admin_draft")
    assert icebreaker == []
    assert any("refused before the model" in r.getMessage() and r.exc_info
               for r in caplog.records)
