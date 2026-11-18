"""STORY    As a speaker, I want Will to answer my latest question in my
         language, remember the visible conversation and project, and keep
         the structured response fields stable, so that a useful answer does
         not collapse into a generic acknowledgement.
OUTCOME
  O1  English and Polish golden turns mirror the typed content language,
      including unaccented Polish through the production default router.
  O2  Earlier turns and bounded project context reach the writer together,
      without crowding out the latest typed message, including the live
      default router classifier.
  O3  Model and timeout fallback responses retain the structured chat
      contract and an explicit stable failure category.
PROVES   O1 -> test_language_golden_turns_follow_the_typed_message
         O2 -> test_writer_receives_conversation_and_project_context,
               test_default_router_bounds_classifier_context_and_keeps_latest_message
         O3 -> test_model_and_fallback_payloads_are_shape_complete,
               test_router_timeout_returns_a_safe_terminal_fallback_without_mega_prompt,
               test_real_provider_timeout_reaches_the_terminal_chat_contract
WHY      Will conversational behavior: content language, context retention,
         useful framing and structured response/card compatibility.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services.master_doc_rag import answer_question


GOLDEN_TURNS = (
    (
        "What did I say about the opening of my talk?",
        "I found the opening you described: you wanted to make the point "
        "clear before moving to the next slide.",
        "en",
    ),
    (
        "Czy możesz wyjaśnić, co powiedziałem o początku prezentacji?",
        "Widzę, że chodzi o początek prezentacji: chciałeś jasno powiedzieć "
        "najważniejszą rzecz przed kolejnym slajdem.",
        "pl",
    ),
    (
        "czy mozesz wyjasnic jak to dziala?",
        "System pomaga zrozumieć, jak Twoje wystąpienie brzmi, a człowiek "
        "pomaga wybrać, nad czym pracować dalej.",
        "pl",
    ),
)


def _response(answer: str, *, app_action=None):
    return SimpleNamespace(text=json.dumps({
        "answer": answer,
        "show_record_ui": False,
        "suggested_action": None,
        "app_action": app_action,
    }, ensure_ascii=False))


@pytest.mark.parametrize("question,answer,target", GOLDEN_TURNS)
def test_language_golden_turns_follow_the_typed_message(question, answer, target):
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        return _response(answer)

    with patch.dict("os.environ", {"LOUNGE_ROUTER_ENABLED": "0"}), \
            patch("services.llm.chat_complete", complete):
        payload, debug = answer_question(question)

    assert payload["answer"] == answer
    assert payload["answer"] != "Got it, thanks."
    assert debug["history_used"] == 0
    assert calls[-1]["messages_override"][-1]["content"] == question
    assert target in calls[-1]["system"]


def test_writer_receives_conversation_and_project_context():
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        return _response(
            "For your Q3 board pitch, the opening is the part you want to "
            "make clearer before the next slide."
        )

    history = [
        {"role": "user", "content": "My talk is for the Q3 board pitch."},
        {"role": "assistant", "content": "What should we look at?"},
    ]
    with patch.dict("os.environ", {"LOUNGE_ROUTER_ENABLED": "0"}), \
            patch("services.llm.chat_complete", complete):
        payload, _debug = answer_question(
            "What about the opening?",
            history=history,
            app_context={
                "context": (
                    "─── CURRENT PROJECT CONTEXT ───\n"
                    "  • title: Q3 board pitch\n"
                    "  • current_slide: Opening\n"
                )
            },
        )

    messages = calls[-1]["messages_override"]
    assert messages[-3]["content"] == history[0]["content"]
    assert messages[-2]["content"] == history[1]["content"]
    assert "Q3 board pitch" in messages[0]["content"]
    assert "Opening" in messages[0]["content"]
    assert "Q3 board pitch" in payload["answer"]


def test_typed_language_overrides_an_older_target_and_context_stays_bounded():
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        return _response("To jest odpowiedź na Twoje najnowsze pytanie.")

    history = [
        {"role": "user", "content": f"old-{i}-" + "x" * 3000}
        for i in range(24)
    ]
    with patch.dict("os.environ", {"LOUNGE_ROUTER_ENABLED": "0"}), \
            patch("services.llm.chat_complete", complete):
        payload, _debug = answer_question(
            "nie wiem co robisz z moim otwarciem",
            history=history,
            target_language="en",
        )

    assert payload["answer"].startswith("To jest")
    system = calls[-1]["system"]
    messages = calls[-1]["messages_override"]
    assert "Polish (pl)" in system
    assert messages[-1]["content"] == "nie wiem co robisz z moim otwarciem"
    prior = messages[1:-1]
    assert len(prior) <= 20
    assert sum(len(m["content"]) for m in prior) <= 8000
    assert all(len(m["content"]) <= 1200 for m in prior if m["role"] == "user")


@pytest.mark.parametrize(("latest", "lane_answer", "language"), (
    (
        "What should I make clearer in the opening?",
        "Make the main point clear before you move on.",
        "English (en)",
    ),
    (
        "czy mozesz wyjasnic jak to dziala?",
        "Tak, system pomaga zrozumieć, jak działa analiza wystąpienia.",
        "Polish (pl)",
    ),
))
def test_default_router_bounds_classifier_context_and_keeps_latest_message(
        monkeypatch, latest, lane_answer, language):
    calls = []
    history = []
    for index in range(24):
        history.extend([
            {"role": "user", "content": f"user-{index}-" + "u" * 3000},
            {"role": "assistant", "content": f"assistant-{index}-" + "a" * 3000},
        ])

    def complete(**kwargs):
        calls.append(kwargs)
        if kwargs["surface"] == "master_doc_rag_router":
            return SimpleNamespace(text=json.dumps({
                "intent": "product_faq", "confidence": 0.95,
            }))
        assert kwargs["surface"] == "master_doc_rag_lane"
        return _response(lane_answer)

    monkeypatch.delenv("LOUNGE_ROUTER_ENABLED", raising=False)
    with patch("services.llm.chat_complete", complete):
        payload, debug = answer_question(latest, history=history)

    classifier, lane = calls
    classifier_messages = classifier["messages_override"]
    classifier_prior = classifier_messages[1:-1]
    assert classifier_messages[-1]["content"] == latest
    assert len(classifier_prior) <= 10
    assert sum(len(message["content"]) for message in classifier_prior) <= 8000
    assert all(len(message["content"]) <= 1200
               for message in classifier_prior if message["role"] == "user")
    assert all(len(message["content"]) <= 300
               for message in classifier_prior if message["role"] == "assistant")
    assert classifier["deadline_monotonic"] is not None
    assert lane["messages_override"][-1]["content"] == latest
    assert language in lane["system"]
    assert payload["answer"] == lane_answer
    assert debug["router_intent"] == "product_faq"


@pytest.mark.parametrize(("latest", "lane_answer", "language"), (
    ("hej", "Hej! W czym mogę Ci dziś pomóc?", "Polish (pl)"),
    ("nice", "Thanks — what would you like to explore next?", "English (en)"),
))
def test_short_social_turn_answers_itself_instead_of_replaying_old_context(
        monkeypatch, latest, lane_answer, language):
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        assert kwargs["surface"] == "master_doc_rag_lane"
        return _response(lane_answer)

    history = [
        {"role": "user", "content": "It was just for me."},
        {"role": "assistant", "content": "How did speaking to yourself feel?"},
    ]
    monkeypatch.delenv("LOUNGE_ROUTER_ENABLED", raising=False)
    with patch("services.llm.chat_complete", complete):
        payload, debug = answer_question(latest, history=history)

    assert len(calls) == 1
    assert calls[0]["messages_override"][-1]["content"] == latest
    assert language in calls[0]["system"]
    assert payload["answer"] == lane_answer
    assert debug["router_intent"] == "conversation"


def test_my_project_lane_combines_private_evidence_with_speaking_science(monkeypatch):
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        if kwargs["surface"] == "master_doc_rag_router":
            return SimpleNamespace(text=json.dumps({
                "intent": "my_project", "confidence": 0.98,
            }))
        return _response(
            "Your repeated pauses are directly observed; treating pressure as a challenge "
            "is only a possibility until you tell me how it felt."
        )

    app_context = {"context": (
        "─── FROM THIS SPEAKER'S OWN HISTORY ───\n"
        "  • Take 2 transcript: \"I paused before the recommendation.\"\n"
    )}
    monkeypatch.delenv("LOUNGE_ROUTER_ENABLED", raising=False)
    with patch("services.llm.chat_complete", complete):
        payload, debug = answer_question(
            "Give me an overall view of my speaking skills and approach to pressure",
            app_context=app_context,
        )

    lane = calls[-1]
    assert "FROM THIS SPEAKER'S OWN HISTORY" in lane["system"]
    assert "MASTER DOCUMENT" in lane["system"]
    assert "never infer a stable personality trait" in lane["system"].lower()
    assert payload["answer"].startswith("Your repeated pauses")
    assert debug["router_intent"] == "my_project"


@pytest.mark.parametrize(("question", "fallback_fragment"), (
    ("What is the Readout?", "I'm having trouble"),
    ("czy mozesz wyjasnic jak to dziala?", "Mam teraz trudność"),
))
def test_router_timeout_returns_a_safe_terminal_fallback_without_mega_prompt(
        monkeypatch, question, fallback_fragment):
    calls = []

    def timed_out(**kwargs):
        calls.append(kwargs["surface"])
        kwargs["failure_out"].update(
            last_code="provider_timeout", timed_out=True,
        )
        return None

    monkeypatch.delenv("LOUNGE_ROUTER_ENABLED", raising=False)
    with patch("services.llm.chat_complete", timed_out):
        payload, debug = answer_question(question)

    assert payload["answer"]
    assert fallback_fragment in payload["answer"]
    assert debug == {"error": "llm_timeout"}
    assert calls == ["master_doc_rag_router"]


def test_real_provider_timeout_reaches_the_terminal_chat_contract(monkeypatch):
    """TimeoutError -> llm -> RAG fallback -> terminal fields, with no leak."""
    from services.authorized_provider import (
        ProviderCoordinates,
        protected_provider_scope,
    )
    from services.chat_query import _failure_from_debug, terminal_response

    class TimeoutPermit:
        def __init__(self):
            self.authorization = self
            self.coordinates = ProviderCoordinates("speaker", "take", "recording")
            self.events = []

        def authorize_operation(self, *_args, **_kwargs):
            return {"permit_id": "timeout-permit"}

        def record_provider_event(self, *args, **kwargs):
            self.events.append((args, kwargs))

    monkeypatch.delenv("LOUNGE_ROUTER_ENABLED", raising=False)
    monkeypatch.setattr("services.chat_provider.build_chat_client", lambda _target: object())
    monkeypatch.setattr(
        "services.llm.operational_chat_complete",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            TimeoutError("provider detail must not reach the chat"),
        ),
    )
    adapter = TimeoutPermit()

    with protected_provider_scope(adapter, idempotency_prefix="chat-timeout-golden"):
        payload, debug = answer_question("What is the Readout?")

    terminal = terminal_response({
        **payload,
        "failure": _failure_from_debug(debug),
    }, "11111111-1111-4111-8111-111111111111")
    assert terminal["terminal"] is True
    assert terminal["outcome"] == "recoverable_error"
    assert terminal["retryable"] is True
    assert terminal["timeout"] is True
    assert terminal["failure"] == {
        "code": "CHAT_MODEL_TIMEOUT", "retryable": True, "timeout": True,
    }
    assert "provider detail must not reach the chat" not in json.dumps(terminal)
    assert adapter.events


def test_model_and_fallback_payloads_are_shape_complete():
    required = {"answer", "show_record_ui", "suggested_action", "app_action"}

    with patch.dict("os.environ", {"LOUNGE_ROUTER_ENABLED": "0"}), \
            patch("services.llm.chat_complete",
                  lambda **_kwargs: _response("The Readout is what a human "
                                               "coach reads from your delivery.")):
        model_payload, _debug = answer_question("What is the Readout?")
    assert required <= model_payload.keys()
    assert model_payload["app_action"] is None

    with patch.dict("os.environ", {"LOUNGE_ROUTER_ENABLED": "0"}), \
            patch("services.llm.chat_complete", lambda **_kwargs: None):
        fallback_payload, debug = answer_question("What is the Readout?")
    assert required <= fallback_payload.keys()
    assert fallback_payload["app_action"] is None
    assert debug["error"] == "llm_unavailable"

    with patch.dict("os.environ", {"LOUNGE_ROUTER_ENABLED": "0"}), \
            patch("services.llm.chat_complete", lambda **_kwargs: None):
        polish_fallback, polish_debug = answer_question("nie wiem co robisz",
                                                         target_language="en")
    assert "trudność" in polish_fallback["answer"]
    assert polish_debug["error"] == "llm_unavailable"
