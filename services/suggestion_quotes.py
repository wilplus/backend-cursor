"""Quote narrowing for text-suggestion stars (founder 2026-07-20).

The gradual-refinement re-shape, step 1: a star should light up the PHRASE
it is about (~20–50 chars), never the whole ~300-char piece. The FE
contract: `suggestion.quote` non-null → underline exactly that substring;
null → star icon only, NO underline. (Structural stars already work this
way; this module brings polish + profanity-replace up to the same
standard. Emphasize / stickiness replacements stay icon-only until a
narrower deterministic signal exists — honest beats pretty.)

Everything here is pure and deterministic — no LLM, no DB.
"""
from __future__ import annotations

import re
from typing import Optional

# Soft sizing for a readable underline. The trimmed diff is served even
# when longer (honesty: the change IS that big) — MAX only guards against
# degenerate near-whole-piece spans, where an underline reads as noise.
_QUOTE_MAX_CHARS = 160

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def diff_quote(original: Optional[str],
               replacement: Optional[str]) -> Optional[str]:
    """The changed region of ``original`` vs ``replacement`` — common
    prefix/suffix trimmed, snapped OUT to word boundaries so the underline
    never starts mid-word. None when either side is empty, nothing
    changed, or the span degenerates to (almost) the whole piece."""
    a = (original or "").strip()
    b = (replacement or "").strip()
    if not a or not b or a == b:
        return None
    # Common prefix.
    lo = 0
    while lo < len(a) and lo < len(b) and a[lo] == b[lo]:
        lo += 1
    # Common suffix (never crossing the prefix).
    hi_a, hi_b = len(a), len(b)
    while hi_a > lo and hi_b > lo and a[hi_a - 1] == b[hi_b - 1]:
        hi_a -= 1
        hi_b -= 1
    if lo >= hi_a:
        # Pure insertion in the replacement — nothing of the original to
        # underline beyond a boundary; snap to the neighbouring word.
        lo = max(0, lo - 1)
        hi_a = min(len(a), hi_a + 1)
    # Snap out to word boundaries.
    while lo > 0 and not a[lo - 1].isspace():
        lo -= 1
    while hi_a < len(a) and not a[hi_a].isspace():
        hi_a += 1
    quote = a[lo:hi_a].strip()
    if not quote:
        return None
    if len(quote) > _QUOTE_MAX_CHARS:
        return None   # change spans (nearly) the piece → icon only
    return quote


def profanity_sentence(text: Optional[str]) -> Optional[str]:
    """The sentence carrying the FIRST profane word — the deterministic
    narrow target for a profanity-triggered replace. None when no hit."""
    from services.text_flags import find_profanity
    t = (text or "").strip()
    if not t:
        return None
    pos = find_profanity(t)
    if pos is None:
        return None
    start = 0
    for m in _SENTENCE_SPLIT.finditer(t):
        if m.end() > pos:
            break
        start = m.end()
    end = len(t)
    m_end = _SENTENCE_SPLIT.search(t, pos)
    if m_end:
        end = m_end.start() + 1   # keep the terminal punctuation
    quote = t[start:end].strip()
    return quote or None
