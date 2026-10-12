"""The helper words are their own text (contract 14, founder 2026-09-25).

A Take rewrites the Paragraph from what was said; the locked helper words
persist through that rewrite until the user picks new ones. The position of
the words inside the Paragraph is only a render hint.
"""
from __future__ import annotations

import pytest

from services.ideal_text_parts import root_span_in


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
