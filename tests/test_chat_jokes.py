"""The Lounge's dad jokes hold the thread (founder 2026-10-15: "I told it to
tell me a dad joke, then I said next, and it understood it as a separate
message"). Pure: no model, no database."""
from services.chat_intents import detect_chat_intent
from services.dad_jokes import DAD_JOKES


def test_next_after_a_joke_tells_another_one():
    first = detect_chat_intent("tell me a dad joke")
    assert first["intent"] == "dad_joke"
    history = [{"role": "user", "content": "tell me a dad joke"},
               {"role": "assistant", "content": first["answer"]}]
    for follow_up in ("next", "Another one!", "haha, more please"):
        again = detect_chat_intent(follow_up, history)
        assert again["intent"] == "dad_joke"
        assert again["answer"] in DAD_JOKES and again["answer"] != first["answer"]


def test_next_without_a_joke_before_is_left_to_will():
    history = [{"role": "user", "content": "what is this?"},
               {"role": "assistant", "content": "A voice coach."}]
    assert detect_chat_intent("next", history) is None
    assert detect_chat_intent("next") is None


def test_answering_wills_question_is_not_deflected():
    """"the story of my talk" after Will asked what the talk is about is an
    answer, not an off-mission request for a story."""
    asked = [{"role": "assistant", "content": "What is your talk about?"}]
    assert detect_chat_intent("tell the story of my startup", asked) is None
    assert detect_chat_intent("tell me a story")["intent"] == "generative"
