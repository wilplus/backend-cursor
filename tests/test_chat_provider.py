"""
STORY    As the founder, I can compare and activate Mistral one text surface
         at a time without moving Whisper, strong reasoning, or an unapproved
         production path away from OpenAI.
OUTCOME
  O1  OpenAI remains the default and strong-model calls remain on OpenAI.
  O2  Only an explicitly allowed cheap-model surface selects Mistral.
  O3  Missing Mistral configuration never silently falls back to OpenAI.
  O4  The speaker's provider permit and usage record name Mistral before the
      provider client is built.
  O5  A real provider timeout, or a response that arrives after the shared
      request budget, returns the normal fallback signal with only a stable
      timeout category, never provider exception text.
PROVES
  O1 -> test_openai_is_the_default_even_when_mistral_is_configured,
        test_only_an_allowlisted_cheap_surface_moves_to_mistral
  O2 -> test_only_an_allowlisted_cheap_surface_moves_to_mistral,
        test_mistral_uses_the_compatible_endpoint_without_hiding_its_identity
  O3 -> test_missing_mistral_credentials_never_fall_back_to_openai
  O4 -> test_chat_complete_names_mistral_before_building_the_client
  O5 -> test_chat_complete_marks_real_timeout_in_failure_out,
        test_chat_complete_caps_each_call_to_the_request_deadline,
        test_chat_complete_discards_a_response_after_the_request_deadline
WHY      Provider portability is useful only when it preserves the live loop,
         processing authorization, and a one-variable rollback path.
"""
from __future__ import annotations

from types import SimpleNamespace

from services.authorized_provider import (
    ProviderCoordinates,
    protected_provider_scope,
)
from services.chat_provider import (
    build_chat_client,
    resolve_chat_target,
)
from services.llm_config import CHEAP_MODEL, LLMSpec, STRONG_MODEL


def _config(**overrides):
    values = {
        "MISTRAL_TEXT_SURFACES": frozenset(),
        "MISTRAL_MODEL": None,
        "MISTRAL_BASE_URL": "https://api.mistral.ai/v1",
        "MISTRAL_API_KEY": "",
        "OPENAI_API_KEY": "openai-key",
        "OPENAI_TIMEOUT_SECONDS": 12.0,
        "OPENAI_MAX_RETRIES": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_openai_is_the_default_even_when_mistral_is_configured():
    config = _config(MISTRAL_MODEL="mistral-small", MISTRAL_API_KEY="secret")

    target = resolve_chat_target("chat_reply", CHEAP_MODEL, config=config)

    assert (target.provider, target.model, target.base_url) == (
        "openai", CHEAP_MODEL, None,
    )


def test_only_an_allowlisted_cheap_surface_moves_to_mistral():
    config = _config(
        MISTRAL_TEXT_SURFACES=frozenset({"chat_reply"}),
        MISTRAL_MODEL="mistral-small",
    )

    cheap = resolve_chat_target("chat_reply", CHEAP_MODEL, config=config)
    strong = resolve_chat_target("chat_reply", STRONG_MODEL, config=config)

    assert (cheap.provider, cheap.model) == ("mistral", "mistral-small")
    assert (strong.provider, strong.model) == ("openai", STRONG_MODEL)


def test_mistral_uses_the_compatible_endpoint_without_hiding_its_identity(
        monkeypatch):
    seen = {}

    def build(key, **kwargs):
        seen.update(key=key, **kwargs)
        return "client"

    monkeypatch.setattr("services.llm_client.build_openai_client", build)
    config = _config(
        MISTRAL_API_KEY="mistral-key",
        MISTRAL_MODEL="mistral-small",
    )
    target = resolve_chat_target("chat_reply", CHEAP_MODEL, config=_config(
        MISTRAL_TEXT_SURFACES=frozenset({"chat_reply"}),
        MISTRAL_MODEL="mistral-small",
    ))

    assert build_chat_client(target, config=config) == "client"
    assert seen == {
        "key": "mistral-key",
        "timeout": 12.0,
        "max_retries": 1,
        "base_url": "https://api.mistral.ai/v1",
    }


def test_missing_mistral_credentials_never_fall_back_to_openai(monkeypatch):
    monkeypatch.setattr(
        "services.llm_client.build_openai_client",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("no provider client should be built")
        ),
    )
    target = resolve_chat_target("chat_reply", CHEAP_MODEL, config=_config(
        MISTRAL_TEXT_SURFACES=frozenset({"chat_reply"}),
        MISTRAL_MODEL="mistral-small",
    ))

    assert build_chat_client(target, config=_config()) is None


class _PermitAdapter:
    def __init__(self, order):
        self.authorization = self
        self.coordinates = ProviderCoordinates("speaker", "take", "recording")
        self.order = order
        self.events = []

    def authorize_operation(
        self, kind, *, manifest, idempotency_key, provider=None,
    ):
        self.order.append("permit")
        self.permit = {
            "kind": kind,
            "provider": provider,
            "surface": manifest["surface"],
            "key": idempotency_key,
        }
        return {"permit_id": "permit-1"}

    def record_provider_event(self, *args, **kwargs):
        self.events.append((args, kwargs))


def test_chat_complete_names_mistral_before_building_the_client(
        monkeypatch):
    from config import Config
    from services.llm import chat_complete

    monkeypatch.setattr(Config, "MISTRAL_TEXT_SURFACES", frozenset({"chat_reply"}))
    monkeypatch.setattr(Config, "MISTRAL_MODEL", "mistral-small")
    monkeypatch.setattr(Config, "MISTRAL_API_KEY", "mistral-key")
    order = []

    response = SimpleNamespace(
        id="mistral-operation",
        usage=SimpleNamespace(
            prompt_tokens=10, completion_tokens=4, total_tokens=14,
        ),
        choices=[SimpleNamespace(
            message=SimpleNamespace(content="A short answer."),
        )],
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **_kwargs: response,
    )))

    def build(target):
        order.append("client")
        assert (target.provider, target.model) == ("mistral", "mistral-small")
        return client

    monkeypatch.setattr("services.chat_provider.build_chat_client", build)
    usage = []
    monkeypatch.setattr(
        "services.llm_usage.record_chat_usage", lambda **kwargs: usage.append(kwargs),
    )
    adapter = _PermitAdapter(order)
    spec = LLMSpec(model=CHEAP_MODEL, temperature=0.0, max_tokens=40)

    with protected_provider_scope(adapter, idempotency_prefix="take-attempt"):
        result = chat_complete(
            spec=spec,
            system="Answer briefly.",
            user="Hello",
            surface="chat_reply",
        )

    assert order == ["permit", "client"]
    assert adapter.permit["provider"] == "mistral"
    assert ":generation:mistral:chat_reply:" in adapter.permit["key"]
    assert result is not None
    assert (result.provider, result.model, result.text) == (
        "mistral", "mistral-small", "A short answer.",
    )
    assert usage[0]["provider"] == "mistral"


def test_chat_complete_marks_real_timeout_in_failure_out(monkeypatch):
    from services.llm import chat_complete

    monkeypatch.setattr("services.chat_provider.build_chat_client", lambda _target: object())
    monkeypatch.setattr(
        "services.llm.operational_chat_complete",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("not exposed")),
    )
    state = {}
    adapter = _PermitAdapter([])
    spec = LLMSpec(model=CHEAP_MODEL, temperature=0.0, max_tokens=40,
                   timeout_seconds=4.0)

    with protected_provider_scope(adapter, idempotency_prefix="timeout-test"):
        result = chat_complete(
            spec=spec, system="Answer briefly.", user="Hello",
            surface="chat_reply", failure_out=state,
        )

    assert result is None
    assert state == {"last_code": "provider_timeout", "timed_out": True}


def test_chat_complete_caps_each_call_to_the_request_deadline(monkeypatch):
    from services.llm import chat_complete

    response = SimpleNamespace(
        id="deadline-operation", usage=None,
        choices=[SimpleNamespace(message=SimpleNamespace(content="A short answer."))],
    )
    seen = {}
    monkeypatch.setattr("services.chat_provider.build_chat_client", lambda _target: object())
    monkeypatch.setattr(
        "services.llm.operational_chat_complete",
        lambda *_args, **kwargs: seen.update(timeout=kwargs["timeout"]) or response,
    )
    monkeypatch.setattr("services.llm.time.monotonic", lambda: 100.0)
    adapter = _PermitAdapter([])
    spec = LLMSpec(model=CHEAP_MODEL, temperature=0.0, max_tokens=40,
                   timeout_seconds=4.0)

    with protected_provider_scope(adapter, idempotency_prefix="deadline-test"):
        result = chat_complete(
            spec=spec, system="Answer briefly.", user="Hello",
            surface="chat_reply", deadline_monotonic=101.25,
        )

    assert result is not None
    assert seen["timeout"] == 1.25


def test_chat_complete_discards_a_response_after_the_request_deadline(monkeypatch):
    from services.llm import chat_complete

    response = SimpleNamespace(
        id="late-operation", usage=None,
        choices=[SimpleNamespace(message=SimpleNamespace(content="Too late."))],
    )
    clock = iter((100.0, 101.5))
    monkeypatch.setattr("services.chat_provider.build_chat_client", lambda _target: object())
    monkeypatch.setattr("services.llm.operational_chat_complete",
                        lambda *_args, **_kwargs: response)
    monkeypatch.setattr("services.llm.time.monotonic", lambda: next(clock))
    adapter = _PermitAdapter([])
    state = {}
    spec = LLMSpec(model=CHEAP_MODEL, temperature=0.0, max_tokens=40,
                   timeout_seconds=4.0)

    with protected_provider_scope(adapter, idempotency_prefix="late-deadline-test"):
        result = chat_complete(
            spec=spec, system="Answer briefly.", user="Hello",
            surface="chat_reply", failure_out=state,
            deadline_monotonic=101.25,
        )

    assert result is None
    assert state == {"last_code": "request_deadline", "timed_out": True}
    assert any(event[0][1] == "completed" for event in adapter.events)
