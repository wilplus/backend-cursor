"""BE-1 (founder 2026-07-27): a wire marker may never straddle a newline.

The screenshot that opened this: a bare `{{orange:` on its own line in the
middle of the student's ideal text, and the closing `}}` two paragraphs later.
The FE's rich-marker parser is flat and single-line, and the marker contract
promises markers "degrade readably anywhere" — a dangling opener does neither.
"""
import re

from services.ideal_decision_ledger import bake_piece
from services.ideal_text_block import (accent_span, sanitize_markers,
                                       strip_moment_markers, wrap_accent)

# an opener whose line has nothing after it — exactly the founder's screenshot
DANGLING = re.compile(r"\{\{orange:[ \t]*\n")


def _balanced(text):
    return text.count("{{orange:") == text.count("}}")


# ── accent_span / wrap_accent ────────────────────────────────────────────

def test_single_line_span_wraps_once():
    assert accent_span("these words") == "{{orange:these words}}"


def test_multi_line_span_wraps_per_line():
    out = accent_span("first line\nsecond line")
    assert out == "{{orange:first line}}\n{{orange:second line}}"
    assert not DANGLING.search(out)


def test_paragraph_break_survives_and_stays_unwrapped():
    out = accent_span("opening para\n\nclosing para")
    assert out == "{{orange:opening para}}\n\n{{orange:closing para}}"
    assert "{{orange:}}" not in out          # never an empty accent


def test_edge_whitespace_stays_outside_the_braces():
    out = accent_span("  padded  ")
    assert out == "  {{orange:padded}}  "


def test_words_are_never_altered():
    src = "How little important it is,\nfrom the perspective of integrity."
    out = accent_span(src)
    assert out.replace("{{orange:", "").replace("}}", "") == src


def test_wrap_accent_places_the_span_in_context():
    text = "before EMPHASIS after"
    out = wrap_accent(text, 7, 15)
    assert out == "before {{orange:EMPHASIS}} after"


def test_wrap_accent_is_a_noop_on_an_already_accented_span():
    text = "before {{orange:EMPHASIS}} after"
    assert wrap_accent(text, 7, 26) == text


def test_wrap_accent_is_a_noop_out_of_bounds_or_on_junk():
    assert wrap_accent("short", 2, 99) == "short"
    assert wrap_accent("short", 4, 2) == "short"
    assert wrap_accent("short", None, 2) == "short"
    assert wrap_accent(None, 0, 1) == ""


# ── bake_piece (the ledger path that produced the defect) ────────────────

def test_bake_piece_multi_paragraph_emphasis_never_dangles():
    text = ("realizing how it is important.\n\n"
            "How little important it is, what he has just achieved\n\n"
            "And being, in general, human,")
    phrase = ("How little important it is, what he has just achieved\n\n"
              "And being, in general, human,")
    out = bake_piece(text, [{
        "decision": "approved", "kind": "emphasize",
        "display_phrase": phrase, "target_phrase": phrase,
    }])
    assert not DANGLING.search(out)
    assert _balanced(out)
    # every word still there, in order
    assert out.replace("{{orange:", "").replace("}}", "") == text


def test_bake_piece_single_line_emphasis_unchanged():
    text = "a plain sentence here"
    out = bake_piece(text, [{
        "decision": "approved", "kind": "emphasize",
        "display_phrase": "plain sentence", "target_phrase": "plain sentence",
    }])
    assert out == "a {{orange:plain sentence}} here"


def test_bake_piece_does_not_double_wrap():
    text = "a {{orange:plain sentence}} here"
    out = bake_piece(text, [{
        "decision": "approved", "kind": "emphasize",
        "display_phrase": "plain sentence", "target_phrase": "plain sentence",
    }])
    assert out == text


# ── sanitize_markers ─────────────────────────────────────────────────────

def test_unmatched_opener_loses_the_token_keeps_the_words():
    out = sanitize_markers("before {{orange:dangling words to the end")
    assert "{{orange:" not in out
    assert out == "before dangling words to the end"


def test_stray_closer_is_dropped():
    assert sanitize_markers("orphan }} brace") == "orphan  brace"


def test_two_openers_one_closer_keeps_the_closable_one():
    out = sanitize_markers("{{orange:first {{orange:second}} tail")
    assert out == "first {{orange:second}} tail"


def test_legacy_multi_paragraph_accent_is_rewrapped_not_dropped():
    out = sanitize_markers("{{orange:first para\n\nsecond para}} tail")
    assert out == "{{orange:first para}}\n\n{{orange:second para}} tail"
    assert not DANGLING.search(out)


def test_odd_bold_marker_is_dropped():
    assert sanitize_markers("an **odd bold") == "an odd bold"
    assert sanitize_markers("an **even bold** here") == "an **even bold** here"


def test_url_slashes_are_never_touched():
    src = "book it at https://cal.com/artur/lesson?duration=60"
    assert sanitize_markers(src) == src


def test_moment_markers_survive_byte_identical():
    src = ("[[moment:abc12345-0000|def67890-1111]]the moment"
           "[[/moment]] and more")
    assert sanitize_markers(src) == src
    assert strip_moment_markers(sanitize_markers(src)) == "the moment and more"


def test_sanitize_is_idempotent():
    src = "{{orange:a\n\nb}} and {{orange:dangling and an **odd"
    once = sanitize_markers(src)
    assert sanitize_markers(once) == once


def test_sanitize_handles_empty_and_junk():
    assert sanitize_markers("") == ""
    assert sanitize_markers(None) == ""
    assert sanitize_markers("plain text") == "plain text"


def test_no_marker_ever_precedes_a_newline_after_sanitize():
    src = ("para one\n\n{{orange:\npara two is emphasized\n}} para three "
           "with an **odd marker and a }} stray")
    out = sanitize_markers(src)
    assert not DANGLING.search(out)
    assert _balanced(out)
    assert out.count("**") % 2 == 0
