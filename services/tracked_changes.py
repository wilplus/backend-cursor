"""Tracked changes on the Living Transcript (founder decision 2026-07-20
#3: "like in Google Docs — crossed text and next to it the new text; I
approve and the crossed text disappears").

Every intervention on the document is ONE span-anchored change:

    {id, snippet_id, kind: replace|bold|advice, span:{start,end},
     quote, proposed_text?, why?, device?, source}

  * kind='replace' — the quote is struck through, `proposed_text` shown
    beside it; approving swaps the words (and bakes forward via the
    decision ledger);
  * kind='bold'    — the quote gets the accent; approving keeps it bold.
    The span can be HALF A SENTENCE (founder: "bolden only the second
    part of it") — it is whatever the narrowing resolved, never
    automatically the whole piece;
  * kind='advice'  — delivery/structural coaching: no text change at
    all, the span only points at what the advice is about.

ANCHORING (the #219 lesson, applied twice): a change is served ONLY when
its quote is found as an exact substring of the served document. The
piece's own text locates the search window, so the same wording appearing
elsewhere in the talk can never steal the anchor; if the piece text is
gone (baked, coach-corrected, student-edited) the change is DROPPED
rather than pointed at the wrong words.

AC-9/CONSTRUCT: `source`/`device` are the closed vocabularies already in
use; the internal trigger vocabulary (threat/charisma/…) never rides a
user payload — 'polish' is the one trigger the FE may distinguish.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# What the FE may receive in `source` (copy keys, never internals).
SOURCES = ("polish", "profanity", "wording", "prior_take",
           "delivery", "structural")


def _find_window(text: str, needle: str) -> Optional[tuple]:
    """(start, end) of the piece inside the document — exact first, then
    whitespace-tolerant. None when the piece no longer occurs."""
    if not text or not needle:
        return None
    i = text.find(needle)
    if i >= 0:
        return (i, i + len(needle))
    # Whitespace may have been normalised on one side only.
    squashed = " ".join(needle.split())
    i = text.find(squashed)
    if i >= 0:
        return (i, i + len(squashed))
    return None


# An emphasis sub-span longer than this isn't a "phrase" — bolding it is
# the whole-fragment problem T3 exists to kill.
_MAX_EMPHASIS_SPAN = 60


def key_phrases_from_say_it_stronger(sis: Any) -> list:
    """The say-it-stronger UPGRADE wordings for a snippet — the founder's
    chosen emphasis-narrowing signal (T3, 2026-07-23). Verbatim strings,
    capped; the same source _key_phrases reads. Pure."""
    if not isinstance(sis, dict):
        return []
    out, seen = [], set()
    for u in (sis.get("upgrades") or []):
        if not isinstance(u, dict):
            continue
        phrase = (u.get("upgrade") or "").strip()
        if not phrase or len(phrase) > _MAX_EMPHASIS_SPAN:
            continue
        k = phrase.lower()
        if k not in seen:
            seen.add(k)
            out.append(phrase)
    return out


def _narrow(window_text: str, sug: dict,
            key_phrases: Any = None) -> Optional[str]:
    """The narrow quote inside a piece — the phrase the change is really
    about (~20–50 chars), or None to mean 'the whole piece'. Reuses the
    shipped narrowing so polish/profanity behave identically to the star
    lane; EMPHASIS narrows to a key-phrase sub-span (T3)."""
    try:
        from services.suggestion_quotes import diff_quote, profanity_sentence
        from services.text_flags import has_profanity
        if sug.get("trigger") == "polish":
            return diff_quote(window_text, sug.get("replacement_text"))
        if sug.get("kind") == "replace" and has_profanity(window_text):
            return profanity_sentence(window_text)
        if sug.get("kind") == "emphasize":
            # Bold only the strongest phrase, not the whole fragment
            # (founder T3): the first say-it-stronger upgrade wording that
            # occurs in this window AND is genuinely narrower than it.
            # Return the window's OWN slice (case-exact), so the caller's
            # substring anchor lands.
            low = window_text.lower()
            for phrase in (key_phrases or []):
                if not phrase or len(phrase) >= len(window_text):
                    continue
                i = low.find(phrase.lower())
                if i >= 0:
                    return window_text[i:i + len(phrase)]
    except Exception:
        return None
    return None


def _kind_and_source(sug: dict) -> tuple:
    """(kind, source) for the FE — the closed vocabularies."""
    k = sug.get("kind")
    if k == "delivery":
        return ("advice", "delivery")
    if k == "structure":
        return ("advice", "structural")
    if k == "emphasize":
        return ("bold", "wording")
    if k == "replace":
        if sug.get("trigger") == "polish":
            return ("replace", "polish")
        if sug.get("trigger") == "profanity":
            return ("replace", "profanity")
        return ("replace", "wording")
    return (None, None)


def build_tracked_changes(text: Any, pieces: Any, suggestions: Any,
                          *, applied: Any = None,
                          key_phrases_by_snippet: Any = None) -> list:
    """The change list for one served document.

    `pieces`   — [{snippet_id, text}] of the take the document came from
                 (the anchor windows);
    `suggestions` — {snippet_id: moment_suggestions row};
    `applied`  — snippet ids the student already approved (consumed: no
                 change is offered for them).

    Ordered by span start — the FE renders top to bottom. Pure."""
    doc = text if isinstance(text, str) else ""
    if not doc:
        return []
    _applied = {str(x) for x in (applied or [])}
    out: list = []
    for p in (pieces or []):
        if not isinstance(p, dict):
            continue
        sid = str(p.get("snippet_id") or "")
        sug = (suggestions or {}).get(sid)
        if not sid or not isinstance(sug, dict) or sid in _applied:
            continue
        kind, source = _kind_and_source(sug)
        if not kind:
            continue
        # The piece carries its span (relocated monotonically onto the
        # served text by the caller) — never a bare text search, which
        # would anchor a repeated phrase on the wrong occurrence.
        try:
            w_start, w_end = int(p["start"]), int(p["end"])
        except (KeyError, TypeError, ValueError):
            continue
        window_text = doc[w_start:w_end]
        if window_text != (p.get("text") or "").strip():
            continue   # the piece's words moved/vanished — never guess

        _kp = (key_phrases_by_snippet or {}).get(sid) if kind == "bold" \
            else None
        quote = _narrow(window_text, sug, key_phrases=_kp)
        if quote:
            rel = window_text.find(quote)
            if rel < 0:
                quote = None
        if quote:
            start, end = w_start + rel, w_start + rel + len(quote)
        else:
            quote, start, end = window_text, w_start, w_end

        entry = {
            "id": sid,
            "snippet_id": sid,
            # The take this piece came from — the FE fills the
            # suggestion-feedback POST's required `session_id` from it
            # (FE contract ask 2026-07-21: a replace/bold with no
            # snippet+session pair is not actionable and the FE drops it,
            # so without this every text change renders as a dead
            # button). Carried from the piece; always present on a
            # transcript-document piece.
            "take_session_id": p.get("take_session_id"),
            "kind": kind,
            "source": source,
            "span": {"start": start, "end": end},
            "quote": quote,
        }
        # THE REASON LINE. `why` is the model's FREE TEXT and the FE has
        # always dropped it: it validates `why_key ?? why` against a closed
        # vocabulary, so un-signed-off LLM prose can never reach a student
        # (LIVE LOOP). That gate is right and stays. The field is kept because
        # a row that ever carries a real key works unchanged.
        #
        # `why_key` is what actually renders, and it is a KEY not a string —
        # the FE holds the copy, exactly as it does for the cross-take lanes.
        # The four existing keys are all COMPARISON copy ("This take carried
        # more energy…"), so reusing one here would have written a sentence
        # about a second take that does not exist in this lane. Founder
        # supplied the non-comparison copy 2026-08-07 and it splits in two.
        #
        # THE SPLIT IS THE LAYER BOUNDARY, not a lane list. A change either
        # alters the words or styles the words that are already there — the
        # same composition/accentuation line SPEC-parts-locking-and-layers §2
        # draws, and the copy only makes sense on the right side of it: you
        # cannot say "helps your main point stand out" about a word swap, and
        # "sounds smoother and easier to follow" says nothing about a bold.
        #
        # `profanity` gets NEITHER. Its lead line already carries the whole
        # message ("This might land differently than you meant"), and neither
        # set is about that; a clarity claim on top would be a second reason
        # nobody offered.
        if kind == "replace" and source in ("polish", "wording"):
            entry["why_key"] = "clarity"      # composition — changes words
        elif kind == "bold":
            entry["why_key"] = "emphasis"     # accentuation — styles words
        if kind == "replace":
            _repl = (sug.get("replacement_text") or "").strip()
            if not _repl:
                continue   # a replace with nothing to propose is dead
            entry["proposed_text"] = _repl
            entry["why"] = sug.get("why")
        elif kind == "bold":
            entry["why"] = sug.get("why")
        else:   # advice — the FE renders copy from the device
            entry["device"] = sug.get("trigger")
            entry["why"] = None
        out.append(entry)
    out.sort(key=lambda c: (c["span"]["start"], c["span"]["end"]))
    return out


def drop_overlaps(changes: Any) -> list:
    """One span may carry only ONE change. Two lanes can legitimately
    fire on the same words (a polish star and a cross-take offer) — the
    FE would render overlapping strikes. Earliest start wins; on a tie
    the NARROWER span wins (the more specific advice). Pure."""
    ordered = sorted(
        [c for c in (changes or []) if isinstance(c, dict) and c.get("span")],
        key=lambda c: (c["span"]["start"],
                       c["span"]["end"] - c["span"]["start"]))
    out: list = []
    last_end = -1
    for c in ordered:
        if c["span"]["start"] < last_end:
            continue
        out.append(c)
        last_end = c["span"]["end"]
    return out


def verify_changes(text: Any, changes: Any) -> bool:
    """Every change's span must slice back to its own quote — the
    invariant the FE renders on. Pure; used in tests and as a cheap
    runtime assert."""
    doc = text if isinstance(text, str) else ""
    for c in (changes or []):
        try:
            if doc[c["span"]["start"]:c["span"]["end"]] != c["quote"]:
                return False
        except Exception:
            return False
    return True
