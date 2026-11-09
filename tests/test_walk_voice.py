"""
STORY    As a speaker, I want Will's words in my walk written for my Take,
         plain and kind, so that they talk about what I said and how it
         sounded, never about me being broken, and the walk never waits on
         them.
OUTCOME
  O1  Words that may reach me are plain: no number, no word that says I am
      broken or names a measurement, no coaching idiom, at most two
      sentences, 220 characters and one question, and a quote is only ever
      my own words; anything else is refused (N557, N565, Never 1).
  O2  Will writes only for a speaker the writer is on for, on their own
      Take, at a step the walk has; otherwise the walk says its signed line.
  O5  My private note is never repeated back to me: a draft that quotes it,
      or carries a run of its words without quote marks, is refused; my own
      spoken words may still be quoted (N565 item 2, SPEAKER-MEMORY.md).
  O4  After a try, Will hears how it went (it landed, one try left, or the
      last) and is told what to offer for each; introducing the moment to
      try, what it will be walked with (a clearer way to say it, or the AI
      clip). A try the walk does not name gets no written reply.
  O3  A draft that fails the check gets another try, told what was refused
      and why, up to three in all; then, or after a failed call, the walk
      says its signed line.
PROVES   O1 -> test_only_plain_kind_words_reach_me
         O2 -> test_will_writes_only_for_me_on_my_take_when_it_is_on
         O3 -> test_a_refused_draft_gets_one_more_try_then_the_signed_line
         O4 -> test_will_hears_how_the_try_went_and_what_the_moment_is_walked_with
         O5 -> test_my_private_note_is_never_repeated_back_to_me
WHY      Founder 2026-11-09 (N565: "make the answers smart. So not locked
         in, but smart... we can set the rules for those messages"; N557:
         "It assumes that you're broken and we need to fix you"; the
         founder's ratings: "to complex", "drawing in... this sounds
         wierd"). The style itself is graded by the golden set,
         tests/evals/golden/walk_voice.jsonl.
"""
from types import SimpleNamespace

import pytest

from services import walk_voice
from services.walk_voice import check

_CONTEXT = {"moment": {"words": "Second thing is that maybe there are people alike, "
                                "so that you can learn together."}}


def test_only_plain_kind_words_reach_me():
    assert check('Listen for the pause before "learn together". Want to try it slower?',
                 _CONTEXT) is None
    refused = {
        "a digit": "You paused 3 times.",
        "fix the speaker": "Let's fix that sentence.",
        "measurement": "Your loudness range was wider this time.",
        "idiom": "The pause made it resonate.",
        "metaphor": "Try it as if you're inviting a friend.",
        "three sentences": "Good. Listen. Try it.",
        "two questions": "Want to hear it? Want to try?",
        "too long": "Listen " * 40,
        "not my words": 'Make "Matching" stand out.',
    }
    for why, text in refused.items():
        assert check(text, _CONTEXT) is not None, why
    # A quote of my words, with a full stop inside it, is one sentence.
    assert check('"So that you can learn together." came out slower. Want to try it once more?',
                 _CONTEXT) is None



def test_my_private_note_is_never_repeated_back_to_me():
    note = "Gets nervous when her boss is in the room; wants to sound calm before the price."
    context = {**_CONTEXT, "speaker_note": note}
    # Quoted, or its words carried over without quote marks: refused.
    assert check('You said "nervous when her boss" before.', context) is not None
    assert check("Your boss is in the room, so slow the opening.", context) is not None
    assert check("Want to sound calm before the price? Try the pause.", context) is not None
    # Kind words that do not repeat the note, and my own spoken words: fine.
    assert check('Listen for the pause before "learn together". Want to try it slower?',
                 context) is None
    assert check("The opening was calm. Want to try the next slide?", context) is None
    # A run the note shares with what I said in the Take may be quoted.
    spoken_too = {**context, "speaker_note": "Wants people alike to learn together."}
    assert check('"So that you can learn together." came out slower.', spoken_too) is None


class _Db:
    def __init__(self, owner="me"):
        self.owner = owner

    def v2_get_session_by_id(self, take_id):
        return {"id": take_id, "user_id": self.owner, "take_index": 3, "arc_id": "arc"}

    def get_snippets_by_session(self, take_id):
        return [{"id": "s1", "transcript": _CONTEXT["moment"]["words"], "metrics": {}}]


@pytest.fixture
def writer(monkeypatch):
    """The writer on for me, the provider's answers in turn, nothing else read."""
    answers: list = []
    asked: list = []
    monkeypatch.setattr("services.rings.feature_is_on_for_user",
                        lambda feature, user, database=None: user == "me")
    monkeypatch.setattr(walk_voice, "_under_authority", lambda db, take, write: write())
    for part in ("_note", "_level", "_last"):
        monkeypatch.setattr(walk_voice, part, lambda *a: None)

    def chat_complete(**kwargs):
        asked.append(kwargs["user"])
        answer = answers.pop(0) if answers else None
        return SimpleNamespace(text=answer) if answer is not None else None
    monkeypatch.setattr("services.llm.chat_complete", chat_complete)
    return answers, asked


def test_will_writes_only_for_me_on_my_take_when_it_is_on(writer):
    answers, asked = writer
    said = 'Listen for the pause before "learn together". Want to try it?'
    answers.append(said)
    assert walk_voice.write(_Db(), "me", "t1", "try", "s1") == said
    # It read my moment's own words.
    assert "learn together" in asked[0]
    # Off for this speaker, not their Take, or not a step of the walk: nothing.
    assert walk_voice.write(_Db(), "someone-else", "t1", "try", "s1") is None
    assert walk_voice.write(_Db(owner="other"), "me", "t1", "try", "s1") is None
    assert walk_voice.write(_Db(), "me", "t1", "lecture", "s1") is None
    assert len(asked) == 1


def test_will_hears_how_the_try_went_and_what_the_moment_is_walked_with(writer):
    answers, asked = writer
    answers.extend(["The pace slowed in your try.", "Want to hear it slower?"])
    assert walk_voice.write(_Db(), "me", "t1", "after_try", "s1",
                            their_try={"outcome": "landed", "moved": "pace"}) == "The pace slowed in your try."
    assert "sounded the way the example did" in asked[0] and "offer no more tries" in asked[0]
    assert walk_voice.write(_Db(), "me", "t1", "try", "s1", tool="voice") == "Want to hear it slower?"
    assert "AI clip" in asked[1]
    # After a try with no outcome the walk sends, nothing is asked.
    assert walk_voice.write(_Db(), "me", "t1", "after_try", "s1", their_try={"outcome": "great"}) is None
    assert len(asked) == 2


def test_a_refused_draft_gets_one_more_try_then_the_signed_line(writer):
    answers, asked = writer
    answers.extend(["Let's fix it. Listen. Try.", "Want to try it slower?"])
    assert walk_voice.write(_Db(), "me", "t1", "try", "s1") == "Want to try it slower?"
    assert "was refused" in asked[1]
    # Refused every time, or no answer at all: the walk says its signed line.
    answers.extend(["You paused 3 times.", "You paused 4 times.", "You paused 5 times."])
    assert walk_voice.write(_Db(), "me", "t1", "try", "s1") is None
    assert walk_voice.write(_Db(), "me", "t1", "try", "s1") is None
