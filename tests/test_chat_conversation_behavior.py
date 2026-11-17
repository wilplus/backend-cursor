"""STORY    As a speaker, I want Will to answer my latest question in my
         language, remember the visible conversation and project, and keep
         the structured response fields stable, so that a useful answer does
         not collapse into a generic acknowledgement.
OUTCOME
  O1  English and Polish golden turns mirror the typed content language.
  O2  Earlier turns and bounded project context reach the writer together.
  O3  Model and fallback responses retain the structured chat contract.
PROVES   O1 -> test_language_golden_turns_follow_the_typed_message
         O2 -> test_writer_receives_conversation_and_project_context
         O3 -> test_model_and_fallback_payloads_are_shape_complete
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
