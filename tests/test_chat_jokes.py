"""
STORY    As a speaker chatting with Will, I want "next" after a dad joke to
         get another joke, and my answers to Will's questions not treated as
         requests, so that the chat follows the thread.
OUTCOME
  O1  "next", "another" or "more" after a joke gives a different joke.
  O2  "next" with no joke before it is left to Will.
  O3  Telling the story of my startup after Will asks about my talk is an
      answer, not deflected; "tell me a story" on its own is still a
      request.
PROVES   O1 -> test_next_after_a_joke_tells_another_one
         O2 -> test_next_without_a_joke_before_is_left_to_will
         O3 -> test_answering_wills_question_is_not_deflected
WHY      Founder 2026-10-15: "next" after a dad joke was read as a new
         message.
"""
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
