"""
STORY    As a speaker, I want my helper words to survive the next Take's
         rewrite until I pick new ones, so that my cues are not lost.
OUTCOME
  O1  Never-5 (helper words stay until the speaker picks new ones): after
      Take 2 rewrites the Paragraph in different words, the next read still
      returns the stored helper words on that Paragraph, with Take 2's text.
  O2  Their position is kept while it proves the words, re-found when they
      occur once in the new text, and otherwise left empty, never guessed.
PROVES   O1 -> test_helper_words_survive_a_take_said_differently
         O2 -> test_root_span_in
WHY      Contract 14, founder 2026-09-25: the helper words are their own text.
"""
from __future__ import annotations

import pytest

from services.db import db
from services.ideal_text_parts import root_span_in, serve
from tests.fakes import FakeSupabaseClient, swap_attr

PART = "60000000-0000-0000-0000-000000000001"
TAKE_1 = "We cut it from nine days to two."
TAKE_2 = "Onboarding used to take nine days; now two."
WORDS = "nine days to two"


def test_helper_words_survive_a_take_said_differently():
    stored = {"id": PART, "text": TAKE_1, "locked_at": "2026-10-01T10:00:00Z",
              "iteration": 1, "root_phrase": WORDS, "root_start": 15,
              "root_end": 31, "root_selected_at": "2026-10-01T10:00:00Z"}
    client = FakeSupabaseClient({"ideal_text_part": [stored]})
    with swap_attr(db, "client", client):
        # Take 2's rewrite of the Paragraph: same id, the words just said.
        assert db.replace_ideal_text_parts(
            "arc-1", "user-1",
            [{"id": PART, "ord": 0, "text": TAKE_2,
              "locked_at": stored["locked_at"]}]) is True
    [written] = client.tables["ideal_text_part"].payload
    [read] = serve([written])
    assert read["text"] == TAKE_2
    assert read["root_phrase"] == WORDS
    # Said differently: no position, rather than a guessed one.
    assert "root_start" not in read and "root_end" not in read


@pytest.mark.parametrize("text,phrase,start,end,expected", [
    # the stored span still proves the words
    ("We cut it from nine days to two.", "nine days to two", 15, 31, (15, 31)),
    # stale span, words occur once in the new text → re-found
    ("From nine days to two, and shipping.", "nine days to two", 16, 32,
     (5, 21)),
    # said differently → no position, never guessed
    ("Onboarding used to take nine days; now two.", "nine days to two",
     16, 32, None),
    # twice → ambiguous → no position
    ("two to two to two", "to two", None, None, None),
    # nothing stored
    ("Any text.", None, None, None, None),
])
def test_root_span_in(text, phrase, start, end, expected):
    assert root_span_in(text, phrase, start, end) == expected
