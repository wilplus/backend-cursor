"""STORY As a speaker correcting a recorded passage, I want the Sniper in
         the reply and the mic to check my retry before the next example.
OUTCOME O1 The published passage opens the Sniper with its exact words.
        O2 A comparable improved retry advances to an opening-emphasis example.
        O3 An off-cue or unmeasurable retry keeps the same actionable exercise.
PROVES O1, O2, O3 -> test_retry_advances_only_after_the_same_passage_lands
WHY Coach chat instruction, 24 November 2026.
"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from services import chat_practice

ARC = "44915a4a-202f-4da6-ae58-bfd4cd3af906"
TAKE = "8f981025-b5fc-4301-9152-21018ba5d7ac"
SNIPPET = "b2f4611c-4dcc-4d8f-83b1-d62d450ac5c8"
REPLY = "82eb645b-ad8c-489d-a7af-b987ae206b67"
TURN = "6f8111cc-d382-4a61-bf27-67ba06c5ce28"
MESSAGE = "8798cfa3-c057-42a7-a1cf-97bcf01da342"
WORDS = "Otóż nie, nie znam."


def _say_at(rate):
    period = 60 / rate
    return [{"word": word, "start": index * period + 1.5, "end": (index + 1) * period + 1.5}
            for index, word in enumerate(WORDS.split())]


@pytest.mark.parametrize(("retry_wpm", "expected_tool"), [(141, "ai_audio"), (210, "sniper"), (79, "sniper")])
def test_retry_advances_only_after_the_same_passage_lands(monkeypatch, retry_wpm, expected_tool):
    original = {"id": SNIPPET, "transcript": WORDS, "words": _say_at(219)}
    database = SimpleNamespace(
        get_ideal_text_document_core=lambda *_: {"id": "snapshot", "source_take_session_id": TAKE},
        read_ideal_text_feedback_bake=lambda *_: {"changes": [{"one_fix": "tempo"}]},
        get_snippets_by_session=lambda *_: [original],
    )
    monkeypatch.setattr("services.ideal_text_feedback_bake._bake_enabled", lambda: True)
    monkeypatch.setattr("services.tempo_stretch.pick_for_take", lambda *_: {"index": 0, "reading": "rushed"})
    text, metadata = chat_practice.published_pace(database, "user", ARC, TAKE, "pl")
    assert "utrzymać piłeczkę na środku paska" in text
    assert metadata["chat_practice"] == {"tool": "sniper", "words": WORDS, "reading": "rushed"}
    monkeypatch.setattr(chat_practice.Config, "SUPABASE_JWT_SECRET", "unit-test-secret")
    metadata["arc_id"] = ARC
    chat_practice.sign_bot_metadata("user", REPLY, metadata)
    offer_row = {"client_id": REPLY, "role": "bot", "kind": "text", "metadata": metadata}
    database.get_lounge_message_by_client_id = lambda user, key: {
        **offer_row,
    } if (user, key) == ("user", REPLY) else None
    monkeypatch.setattr("services.lounge_clips.owned_chat_moment", Mock(return_value=({"arc_id": ARC}, original)))
    heard = {"transcript": WORDS, "metrics": {"wpm": 157}, "verbal_cues": {"words": _say_at(retry_wpm)},
             chat_practice.REPLY_ID: REPLY}
    source = {"id": MESSAGE, "client_id": TURN, "metadata": {
        "arc_id": ARC, "take_session_id": TAKE, "review_focus": {"step": "practise", "snippet_id": SNIPPET},
    }}
    monkeypatch.setattr("services.lounge_voice_reply.read_attempt", Mock(return_value=(source, heard)))
    opening = Mock(return_value=WORDS)
    monkeypatch.setattr(chat_practice, "opening_example", opening)

    result, next_meta = chat_practice.retry_reply(database, "user", TURN, ARC, "pl")
    plan = next_meta["chat_practice"]
    assert plan["tool"] == expected_tool
    assert plan["words"] == WORDS
    assert next_meta["coach_moment"]["snippet_id"] == SNIPPET
    if expected_tool == "ai_audio":
        assert result.startswith("Świetnie, tempo jest w porządku.")
        assert plan["retry_message_id"] == MESSAGE
        assert "dodać nieco energii" in plan["guidance"]
        opening.assert_called_once()
    else:
        assert "piłeczkę" in result
        opening.assert_not_called()
    assert chat_practice.retry_reply(database, "someone-else", TURN, ARC, "pl") is None
    assert chat_practice.repeat_offer([offer_row], "user", "pl")[1]["chat_practice"]["words"] == WORDS
    metadata["chat_practice"]["words"] = "An altered offer"
    assert chat_practice.repeat_offer([offer_row], "user", "pl") is None
    assert chat_practice.retry_reply(database, "user", TURN, ARC, "pl") is None
