"""
STORY    As a speaker, I want the coloured highlight marks in my Ideal Text
         never to break across a line, so that I never see a stray
         `{{orange:` in the middle of my text.
OUTCOME
  O1  Sanitised Ideal Text has no marker that opens on one line and closes
      on another; an accent across a paragraph break is re-wrapped per line
      and every word stays.
  O2  A dangling `{{orange:` or a stray `}}` loses only the token, never the
      words, and sanitising twice changes nothing.
  O3  The ledger bake of an approved highlight whose phrase spans a newline
      writes one closed mark per line; baking again or with stale offsets
      leaves the text as it was.
PROVES   O1 -> test_an_accent_across_a_paragraph_break_closes_on_every_line
         O2 -> test_a_dangling_mark_loses_the_token_and_keeps_the_words
         O3 -> test_a_baked_highlight_never_straddles_a_line
WHY      BE-1, founder screenshot 2026-07-27: a bare `{{orange:` on its own line.
"""

from services.ideal_decision_ledger import bake_piece
from services.ideal_text_block import sanitize_markers, wrap_accent

OPEN, CLOSE = "{{orange:", "}}"


def _assert_every_line_is_closed(text):
    """No line holds an opener without its own closer, or a closer without
    its own opener — what the FE's flat, single-line parser needs."""
    for line in text.split("\n"):
        depth = 0
        i = 0
        while i < len(line):
            if line.startswith(OPEN, i):
                assert depth == 0, f"nested opener on line {line!r}"
                depth, i = 1, i + len(OPEN)
            elif line.startswith(CLOSE, i):
                assert depth == 1, f"stray closer on line {line!r}"
                depth, i = 0, i + len(CLOSE)
            else:
                i += 1
        assert depth == 0, f"marker left open at end of line {line!r}"


def _words(text):
    return text.replace(OPEN, " ").replace(CLOSE, " ").split()


def test_an_accent_across_a_paragraph_break_closes_on_every_line():
    src = "Intro {{orange:a\n\nb}} outro"
    out = sanitize_markers(src)
    _assert_every_line_is_closed(out)
    assert out == "Intro {{orange:a}}\n\n{{orange:b}} outro"
    assert _words(out) == _words(src)


def test_a_dangling_mark_loses_the_token_and_keeps_the_words():
    src = "one }} two {{orange:three\nfour {{orange:five}} and **six"
    out = sanitize_markers(src)
    _assert_every_line_is_closed(out)
    assert out == "one  two three\nfour {{orange:five}} and six"
    assert sanitize_markers(out) == out


def test_a_baked_highlight_never_straddles_a_line():
    text = "We grew fast.\nThen we stopped."
    row = {"decision": "approved", "kind": "emphasize",
           "display_phrase": "fast.\nThen"}
    out = bake_piece(text, [row])
    _assert_every_line_is_closed(out)
    assert out == "We grew {{orange:fast.}}\n{{orange:Then}} we stopped."
    # Baking again never double-wraps; offsets computed on an older text,
    # or no text at all, never corrupt what the speaker sees.
    assert bake_piece(out, [row]) == out
    lo = out.index(OPEN)
    assert wrap_accent(out, lo, lo + len(OPEN) + 5) == out
    for lo, hi in ((2, 99), (4, 2), (None, 2)):
        assert wrap_accent(text, lo, hi) == text
    assert wrap_accent(None, 0, 1) == ""
