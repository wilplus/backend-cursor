"""BE-1 (founder 2026-07-27): a wire marker may never straddle a newline.

The screenshot that opened this: a bare `{{orange:` on its own line in the
middle of the student's ideal text, and the closing `}}` two paragraphs later.
The FE's rich-marker parser is flat and single-line, and the marker contract
promises markers "degrade readably anywhere" — a dangling opener does neither.
"""

from services.ideal_text_block import sanitize_markers, wrap_accent

# ── accent_span / wrap_accent ────────────────────────────────────────────


def test_wrap_accent_is_a_noop_out_of_bounds_or_on_junk():
    assert wrap_accent("short", 2, 99) == "short"
    assert wrap_accent("short", 4, 2) == "short"
    assert wrap_accent("short", None, 2) == "short"
    assert wrap_accent(None, 0, 1) == ""


# ── bake_piece (the ledger path that produced the defect) ────────────────


# ── sanitize_markers ─────────────────────────────────────────────────────


def test_sanitize_is_idempotent():
    src = "{{orange:a\n\nb}} and {{orange:dangling and an **odd"
    once = sanitize_markers(src)
    assert sanitize_markers(once) == once
