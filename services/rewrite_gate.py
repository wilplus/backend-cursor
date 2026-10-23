"""When the practise moment opens on the Clearer version (founder
2026-10-18, "words first, then voice"; prototype
https://claude.ai/artifact/Ut2SqvHCoJ1hvH8dp17yQe, "ok, push to prod").

The practise moment is still the Take's second best (moment_pick). What it
opens on is decided here, in two gates, and the voice Exercise is what
every failed check falls back to:

  1. THE WORDS NEED HELP, read on the words the speaker sees, the Ideal
     Text's after the silent smoothing (founder 2026-10-23, N121: the
     hesitations it removed never count). At least one of: fillers at 3 or more per 100
     words, hedges at 3 or more per 100 words, the clip misses its slide
     (slide fit below 0.5), a broken sentence, words said again straight
     away, two or more and ``REPEATS_PER_100`` or more per 100 words
     (founder 2026-10-19, WIL-26: often, not one slip), or words that
     undermine the speaker: an apology or an ask for permission, the idea
     played down, self-doubt (founder 2026-10-20, N85, ``undermining``; one
     is enough), an ask for approval or a playing-down "just", or a phrase
     begun again inside a sentence (founder 2026-10-23, N124; one is
     enough). Weak openers ("So,", "Well,") count with the fillers (N124).
     None of them: the wording is good and the moment goes to the voice
     Exercise with the AI clip.
  2. THE NEW WORDS ARE GOOD ENOUGH. A rewrite row that is all of:
       - inside this moment's own clip (its span inside the clip's span);
       - backed by evidence: never the tentative fallback;
       - a real fix: fillers and hedges, read on the new words, at least
         ``MIN_LIFT`` better than on the words on screen they replace
         (founder 2026-10-23, N121: until then the clip's own transcript,
         hesitations included, when worse, so almost any rewrite passed),
         or the broken sentence mended, or a repeat said once, or fewer
         undermining words, restarts or weak openers (N124);
       - still the speaker's: at least ``MIN_KEPT`` of its words are theirs,
         and no number or name they did not say;
       - sayable in one go: not longer than what they said, ``MIN_WORDS``
         words or more.
     Turned down before on the same Paragraph words, and every lineage
     check, stay where they are (the V3 inventory's exclusions).

Starting values, to calibrate on the golden evaluation set. Internal only
(AC-9): no signal or verdict here reaches a payload. Pure.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from services import undermining, verbal_markers, willfidence

GATE_VERSION = "rewrite-gate-v1"
#: Gate 1: a filler or hedge signal below this is "too many" (willfidence's
#: scale: 3 per 100 words gives 0.7).
WORD_SIGNAL_FLOOR = 0.7
#: Gate 1: a slide fit below this misses the slide (0.5 is "partly").
SLIDE_FIT_FLOOR = 0.5
#: Gate 1: repeats are "often" at this many per 100 words AND at least
#: ``MIN_REPEATS`` of them, so one slip in a short clip is never enough.
REPEATS_PER_100 = 2.0
MIN_REPEATS = 2
#: Gate 2.
MIN_LIFT = 0.1
MIN_KEPT = 0.6
MIN_WORDS = 5

_WORD = re.compile(r"[^\W_]+(?:[’'-][^\W_]+)*", re.UNICODE)
_SENTENCE_START = re.compile(r"(?:^|[.!?]\s+)([^\W\d_][\w’'-]*)", re.UNICODE)


def _below(value: Optional[float], floor: float) -> bool:
    return isinstance(value, (int, float)) and float(value) < floor


def words_need_help(text: Any, slide_fit: Optional[float]) -> Optional[str]:
    """The first reason the moment's words need help, or None when the
    wording is good. ``slide_fit`` is the clip's own (None: not checked)."""
    from services.take_feedback_manager import has_broken_boundary, restart_count
    if undermining.found(str(text or "")):
        return "undermining"
    if restart_count(text):
        return "restart"
    if _below(_fillers(text), WORD_SIGNAL_FLOOR):
        return "fillers"
    if _below(willfidence.hedging(text), WORD_SIGNAL_FLOOR):
        return "hedges"
    if _below(slide_fit, SLIDE_FIT_FLOOR):
        return "off_slide"
    if has_broken_boundary(text):
        return "broken_sentence"
    if _repeats_often(text):
        return "repeats"
    return None


def _repeats_often(text: Any) -> bool:
    from services.take_feedback_manager import repeat_count
    words, repeats = len(_words(text)), repeat_count(text)
    return (words > 0 and repeats >= MIN_REPEATS
            and repeats * 100 / words >= REPEATS_PER_100)


def _words(text: Any) -> list[str]:
    return _WORD.findall(str(text or ""))


def _fillers(text: Any) -> Optional[float]:
    """The filler signal with weak openers counted as fillers (N124)."""
    from services.take_feedback_manager import weak_opener_count
    counted = verbal_markers.count(text)
    return willfidence.scale(counted[verbal_markers.TIC]["strict"] + weak_opener_count(text),
                             counted["n_words"])


def _word_signal(text: Any) -> Optional[float]:
    return willfidence.partial_w(_fillers(text), willfidence.hedging(text))


def _sentence_starts(text: str) -> set[str]:
    return {m.group(1).lower() for m in _SENTENCE_START.finditer(text)}


def _invents(quote: str, proposed: str) -> bool:
    """A number, or a capitalised word inside a sentence (a name), that the
    speaker did not say."""
    said = {w.lower() for w in _words(quote)}
    starts = _sentence_starts(proposed)
    for word in _words(proposed):
        low = word.lower()
        if low in said:
            continue
        if any(ch.isdigit() for ch in word):
            return True
        if word[0].isupper() and low not in starts and low != "i":
            return True
    return False


def _kept_share(quote: str, proposed: str) -> float:
    said: dict[str, int] = {}
    for word in _words(quote):
        said[word.lower()] = said.get(word.lower(), 0) + 1
    new = _words(proposed)
    kept = 0
    for word in new:
        low = word.lower()
        if said.get(low):
            said[low] -= 1
            kept += 1
    return kept / len(new) if new else 0.0


def _in_clip(span: Any, clip_span: Any) -> bool:
    return (isinstance(clip_span, dict) and isinstance(span, dict)
            and isinstance(span.get("start"), int) and isinstance(span.get("end"), int)
            and clip_span.get("start", 0) <= span["start"]
            and span["end"] <= clip_span.get("end", -1))


def _words_refusal(quote: str, proposed: str) -> Optional[str]:
    """The checks on the words alone: a real fix, still theirs, sayable.
    ``quote`` is the words on screen it replaces (N121)."""
    from services.take_feedback_manager import (
        has_broken_boundary, repeat_count, restart_count, weak_opener_count)
    before, after = _word_signal(quote), _word_signal(proposed)
    lifted = before is not None and after is not None and after - before >= MIN_LIFT
    mended = ((has_broken_boundary(quote) and not has_broken_boundary(proposed))
              or repeat_count(proposed) < repeat_count(quote)
              or undermining.count(proposed) < undermining.count(quote)
              or restart_count(proposed) < restart_count(quote)
              or weak_opener_count(proposed) < weak_opener_count(quote))
    if not (lifted or mended):
        return "no_real_fix"
    if _kept_share(quote, proposed) < MIN_KEPT or _invents(quote, proposed):
        return "not_their_words"
    count = len(_words(proposed))
    if count < MIN_WORDS or count > len(_words(quote)):
        return "hard_to_say"
    return None


def rewrite_refusal(row: Any, item: Any, clip_span: Optional[dict]) -> Optional[str]:
    """Why this rewrite cannot open the moment, or None when it can.

    ``row`` is the rewrite candidate as the Manager made it (quote, the
    words on screen it replaces; proposed_text; tentative); ``item`` its V3
    inventory row (document_span, evidence); ``clip_span`` the moment's own
    clip in the same document."""
    row = row if isinstance(row, dict) else {}
    item = item if isinstance(item, dict) else {}
    if not _in_clip(item.get("document_span"), clip_span):
        return "outside_the_clip"
    if row.get("tentative") or item.get("tentative") \
            or (item.get("evidence") or {}).get("fallback"):
        return "fallback"
    return _words_refusal(str(row.get("quote") or ""),
                          str(row.get("proposed_text") or ""))
