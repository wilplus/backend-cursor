"""Minimum smoothing of a literal transcript (founder decision 2026-07-20).

THE FENCE THIS MODULE ENFORCES (locked by the founder, decision #2 of the
Living Transcript re-shape): the ideal text is what the speaker ACTUALLY
said, and the ONLY things that may change silently are

  1. HESITATIONS  — a closed, LANGUAGE-AWARE list of standalone
                    hesitation tokens, removed with their whitespace;
  2. IMMEDIATE WORD REPEATS — the same word twice in a row with NOTHING
                    between them ("the the" → "the"). A repeat separated
                    by punctuation is EXPRESSIVE ("no, no, no") and is
                    never touched;
  3. PUNCTUATION + CASING — sentence-initial capitalisation and ONE
                    terminal mark, applied to the FINISHED DOCUMENT only.

Everything else — false starts, rephrasings, the compose LLM's
smoothing, a coach's wording change — is a VISIBLE, approvable change.

TWO ARCHITECTURAL RULES, both from confirmed review findings:

  * PER-PIECE vs DOCUMENT. Pieces are cut on slide advances and hard
    character caps, so a piece is very often MID-SENTENCE. Casing and
    terminal marks therefore run ONCE over the assembled document
    (finalize_document), never per piece — otherwise every seam invents
    a full stop the speaker never made and re-capitalises a mid-sentence
    word.
  * LANGUAGE. "um" is a real word in German and Portuguese ("es geht um
    Geld", "um problema"). Deleting it there removes the speaker's
    words. Hesitations are per language, and when the language is
    UNKNOWN only the tokens that are disfluencies in every language we
    support are removed.

finalize_document is LENGTH-PRESERVING except for a single terminal mark
appended at the very end — so character spans computed before it stay
valid (the anchor contract).
"""
from __future__ import annotations

import re
from typing import Any, Optional

# Pure hesitation tokens ONLY, per language. A token that can be a real
# word in that language is not here (English "like"/"so"/"right",
# German/Portuguese "um", Polish "no"): removing those is editing the
# speaker, not smoothing.
HESITATIONS = {
    "en": ("um", "umm", "ummm", "uh", "uhh", "uhhh", "uhm", "erm", "ehm",
           "hmm", "mmm"),
    "de": ("äh", "ähm", "ähhh", "öh", "öhm", "hmm", "mmm"),
    "pl": ("yyy", "yyyy", "eee", "eeee", "hmm", "mmm"),
    "pt": ("hum", "ahn", "hmm", "mmm"),
    # Spanish "eh"/"este" and Italian "mah" are real words — excluded.
    "es": ("ehh", "hmm", "mmm"),
    "fr": ("euh", "euhh", "hmm", "mmm"),
    "it": ("ehm", "hmm", "mmm"),
}

# Used when the language is unknown: the intersection-safe set — tokens
# that are a disfluency (and never a real word) in every language above.
_UNKNOWN_SAFE = ("uh", "uhh", "uhhh", "uhm", "erm", "ehm", "hmm", "mmm",
                 "yyy", "eee", "äh", "ähm", "euh")

# Abbreviations after which a following capital would be WRONG (the
# period does not end a sentence).
_ABBREV = {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs",
           "etc", "e.g", "i.e", "eg", "ie", "approx", "fig",
           "inc", "ltd", "co", "u.s", "u.k", "a.m", "p.m", "am", "pm"}

_SPACE_RE = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?])")
# The same word twice with ONLY whitespace between — a disfluency.
_REPEAT_RE = re.compile(r"(?<![\w'-])([\w']+)(\s+)(\1)(?![\w'-])",
                        re.IGNORECASE)
# A sentence boundary candidate: terminal punctuation (optionally with a
# closing quote/bracket) + whitespace + a lowercase letter.
_BOUNDARY_RE = re.compile(r"([.!?][\"'’”\)\]]?)(\s+)([a-zà-ÿ])")


def hesitations_for(language: Optional[str]) -> tuple:
    """The removable tokens for a language; the intersection-safe set
    when it is unknown/unsupported. Pure."""
    if not language:
        return _UNKNOWN_SAFE
    code = str(language).strip().lower()[:2]
    return HESITATIONS.get(code, _UNKNOWN_SAFE)


def _filler_re(tokens: tuple):
    return re.compile(
        r"(?<![\w'-])(?:" + "|".join(re.escape(t) for t in tokens)
        + r")(?![\w'-])", re.IGNORECASE)


def strip_fillers(text: Any, language: Optional[str] = None) -> str:
    """Hesitations + immediate repeats out; nothing else. Language-aware
    (see the module fence). Pure."""
    if not isinstance(text, str) or not text:
        return ""
    out = _filler_re(hesitations_for(language)).sub(" ", text)
    for _ in range(3):          # "the the the" — bounded
        new = _REPEAT_RE.sub(r"\1", out)
        if new == out:
            break
        out = new
    return out


def tidy_piece(text: Any) -> str:
    """PER-PIECE tidy: whitespace and punctuation left orphaned by a
    removal. NEVER casing, NEVER a terminal mark — a piece is frequently
    mid-sentence and must flow into the next one. Pure."""
    if not isinstance(text, str) or not text:
        return ""
    out = _SPACE_RE.sub(" ", text.replace("\t", " "))
    out = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", out)
    out = re.sub(r",\s*,+", ",", out)
    out = re.sub(r"^\s*[,;:]\s*", "", out)
    return out.strip()


def _ends_with_abbrev(text: str, dot_index: int) -> bool:
    """True when the '.' at dot_index closes a known abbreviation or a
    single initial ("J. Smith") — not a sentence."""
    head = text[:dot_index]
    m = re.search(r"([\w.]+)$", head)
    if not m:
        return False
    token = m.group(1).lower().strip(".")
    if not token:
        return False
    if token in _ABBREV:
        return True
    return len(token) == 1        # an initial


def finalize_document(text: Any) -> str:
    """DOCUMENT-level finish: sentence-initial capitalisation (skipping
    abbreviations) and ONE terminal mark at the very end.

    Length-preserving apart from that final mark, so spans computed on
    the joined text remain valid. Pure."""
    if not isinstance(text, str) or not text:
        return ""
    out = text.strip()
    if not out:
        return ""

    chars = list(out)
    if chars[0].isalpha():
        chars[0] = chars[0].upper()
    for m in _BOUNDARY_RE.finditer(out):
        dot_index = m.start(1)
        if out[dot_index] == "." and _ends_with_abbrev(out, dot_index):
            continue
        idx = m.start(3)
        chars[idx] = chars[idx].upper()
    out = "".join(chars)

    if out[-1] not in ".!?":
        # A dangling separator is not sentence punctuation — drop it
        # before closing the document.
        out = out.rstrip(",;: ")
        if out and out[-1] not in ".!?\"'’”)]":
            out += "."
        elif out and out[-1] in "\"'’”)]" and (
                len(out) < 2 or out[-2] not in ".!?"):
            out += "."
    return out


def smooth_piece(text: Any, language: Optional[str] = None) -> str:
    """The per-piece entry point: hesitations + repeats + tidy. No
    casing, no terminal mark (finalize_document owns those)."""
    return tidy_piece(strip_fillers(text, language))
