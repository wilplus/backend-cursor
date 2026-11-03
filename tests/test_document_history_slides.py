"""
STORY    As a speaker, I want an older Take's Ideal Text shown slide by slide
         on the deck I said it on, with the helper words I had then, so that
         I read what I said then as the page showed it.
OUTCOME
  O1  Each version in the History carries each Paragraph's Slide and the
      deck of its own Take, not the latest Take's.
  O2  A Slide map that cannot be proved, or a Take that cannot be found, is
      not guessed: no slides, no deck, the words as they are.
  O3  Each version keeps the helper words its Slides had while it was the
      latest: the last set picked before the next version, not today's.
PROVES   O1 -> test_each_version_carries_its_slides_and_its_own_takes_deck
         O2 -> test_an_unproved_slide_map_or_unknown_take_is_not_guessed
         O3 -> test_each_version_keeps_the_helper_words_of_its_time
WHY      Founder 2026-11-03, N375, N376, N380; a Take's deck is its own (N257).
"""
from services.paragraph_history import document_history

SESSIONS = [
    {"id": "take-1", "intake_context": {"presentation_ref": "decks/first.pdf"}},
    {"id": "take-2", "intake_context": {"presentation_ref": "decks/second.pdf"}},
]


def _version(version, text, paragraphs, take, at=None):
    return {"version": version, "text": text, "created_at": at,
            "document": {"paragraphs": paragraphs, "take_index": version,
                         "take_session_id": take}}


def test_each_version_carries_its_slides_and_its_own_takes_deck():
    rows = document_history([
        _version(1, "One.\n\nTwo.\n\nThree.",
                 [{"slide_index": 0}, {"slide_index": 0}, {"slide_index": 1}],
                 "take-1"),
        _version(2, "New one.\n\nNew two.",
                 [{"slide_index": 0}, {"slide_index": None}], "take-2"),
    ], SESSIONS)
    head, older = rows
    assert older["slides"] == [0, 0, 1]
    assert older["presentation_ref"] == "decks/first.pdf"
    assert head["is_head"] and head["slides"] == [0, None]
    assert head["presentation_ref"] == "decks/second.pdf"


def test_an_unproved_slide_map_or_unknown_take_is_not_guessed():
    rows = document_history([
        # Two paragraphs in the text, one in the map: no slides.
        _version(1, "One.\n\nTwo.", [{"slide_index": 0}], "take-gone"),
    ], SESSIONS)
    assert rows[0]["slides"] is None
    assert rows[0]["presentation_ref"] is None
    assert rows[0]["text"] == "One.\n\nTwo."


def test_each_version_keeps_the_helper_words_of_its_time():
    versions = [
        _version(1, "One.\n\nTwo.", [{"slide_index": 0}, {"slide_index": 1}],
                 "take-1", at="2026-11-01T10:00:00Z"),
        _version(2, "New one.\n\nNew two.",
                 [{"slide_index": 0}, {"slide_index": 1}], "take-2",
                 at="2026-11-02T10:00:00Z"),
    ]
    logs = {
        0: [{"phrases": ["first pick"], "created_at": "2026-11-01T11:00:00Z"},
            {"phrases": ["kept for Take 2"], "created_at": "2026-11-01T12:00:00Z"},
            {"phrases": ["picked later"], "created_at": "2026-11-02T11:00:00Z"}],
        1: [{"phrases": [], "created_at": "2026-11-01T11:00:00Z"}],
    }
    head, older = document_history(versions, SESSIONS, logs)
    assert older["helper_words"] == [
        {"slide_index": 0, "phrases": ["kept for Take 2"]}]
    assert head["helper_words"] == [
        {"slide_index": 0, "phrases": ["picked later"]}]
    # No read of the log: the words without helper words.
    assert document_history(versions, SESSIONS)[1]["helper_words"] == []
