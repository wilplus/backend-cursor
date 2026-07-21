"""Minimum smoothing of a literal transcript (founder decision 2026-07-20).

THE FENCE THIS MODULE ENFORCES (locked by the founder, decision 2 of the
Living Transcript re-shape): the ideal text is what the speaker ACTUALLY
said, and the ONLY things that may change silently are

  1. FILLERS      — a closed list of standalone hesitation tokens
                    (um / uh / uhm / erm / …), removed with their
                    surrounding whitespace;
  2. IMMEDIATE WORD REPEATS — the same word twice in a row with NOTHING
                    between them ("the the" → "the"). A repeat separated
                    by punctuation is EXPRESSIVE ("no, no, no") and is
                    never touched;
  3. PUNCTUATION + CASING — sentence-initial capitalisation and a
                    terminal mark; whitespace normalisation.

Everything else — false starts, rephrasings, the compose LLM's
smoothing, a coach's wording change — is a VISIBLE, approvable
suggestion. Never silent. That is the whole point of the re-shape: the
founder must be able to trust that unmarked text is verbatim.

Nothing here uses an LLM; everything is deterministic and reversible in
review (the raw transcript stays on the snippet row).
"""
from __future__ import annotations

import re
from typing import Any

# Standalone hesitation tokens only. Deliberately CONSERVATIVE — a token
# that can be a real word in normal speech ("ah", "so", "well", "like",
# "you know") is NOT here: removing those would be editing the speaker.
FILLERS = ("um", "umm", "ummm", "uh", "uhh", "uhhh", "uhm", "erm", "ehm",
           "mmm", "hmm")

_FILLER_RE = re.compile(
    r"(?<![\w'-])(?:" + "|".join(FILLERS) + r")(?![\w'-])",
    re.IGNORECASE,
)

# The same word twice with ONLY whitespace between (no comma, no dash) —
# a disfluency. Apostrophes/hyphens count as word characters so "I'm I'm"
# collapses too.
_REPEAT_RE = re.compile(
    r"(?<![\w'-])([\w']+)(\s+)(\1)(?![\w'-])",
    re.IGNORECASE,
)

_SPACE_RE = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?])")
_SENTENCE_START_RE = re.compile(r"(^|[.!?]\s+)([a-z])")


def strip_fillers(text: Any) -> str:
    """Fillers + immediate repeats out; nothing else. Pure."""
    if not isinstance(text, str) or not text:
        return ""
    out = _FILLER_RE.sub(" ", text)
    # Repeats can chain ("the the the") — collapse until stable, bounded.
    for _ in range(3):
        new = _REPEAT_RE.sub(r"\1", out)
        if new == out:
            break
        out = new
    return out


def tidy_punctuation(text: Any) -> str:
    """Whitespace, orphaned punctuation, sentence casing, terminal mark.
    Never changes a word. Pure."""
    if not isinstance(text, str) or not text:
        return ""
    out = _SPACE_RE.sub(" ", text)
    out = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", out)
    # A filler removal can leave a doubled comma or a leading one.
    out = re.sub(r",\s*,+", ",", out)
    out = re.sub(r"^\s*[,;:]\s*", "", out)
    out = out.strip()
    if not out:
        return ""
    out = _SENTENCE_START_RE.sub(lambda m: m.group(1) + m.group(2).upper(),
                                 out)
    if out[-1] not in ".!?":
        out += "."
    return out


def smooth_verbatim(text: Any) -> str:
    """The ONE entry point: fillers + repeats + punctuation/casing.
    Word-preserving by construction (see the module fence). Pure."""
    return tidy_punctuation(strip_fillers(text))
