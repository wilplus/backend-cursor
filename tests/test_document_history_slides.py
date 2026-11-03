"""An older Take's Ideal Text, slide by slide on its own deck (N375, N376).

The History under ⋯ serves each version with each Paragraph's Slide and
the deck that version's Take was said on, so the speaker reads an older
Take's words as the page shows them. A Slide map that cannot be proved is
not guessed.
"""
from services.paragraph_history import document_history

SESSIONS = [
    {"id": "take-1", "intake_context": {"presentation_ref": "decks/first.pdf"}},
    {"id": "take-2", "intake_context": {"presentation_ref": "decks/second.pdf"}},
]


def _version(version, text, paragraphs, take):
    return {"version": version, "text": text, "created_at": None,
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
