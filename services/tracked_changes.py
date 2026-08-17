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
    automatically the whole piece. Since 2026-08-15 that is enforced
    rather than merely intended: see THE ACCENT WIDTH RULE below;
  * kind='advice'  — delivery/structural coaching: no text change at
    all, the span only points at what the advice is about.

ANCHORING (the #219 lesson, applied twice): a change is served ONLY when
its quote is found as an exact substring of the served document. The
piece's own text locates the search window, so the same wording appearing
elsewhere in the talk can never steal the anchor; if the piece text is
gone (baked, coach-corrected, student-edited) the change is DROPPED
rather than pointed at the wrong words.

ANCHOR GRAIN (founder 2026-08-12). `relocate_pieces` may now hand back a
piece anchored to its PARAGRAPH rather than to its words, so a locked
chunk no longer takes the whole feedback engine dark. Such a piece is
tagged `anchor_grain='paragraph'` and this builder reads the tag: a
change that RE-WRITES or STYLES words (replace, bold) is served only if
narrowing found the exact phrase inside that paragraph — otherwise its
quote would be the entire paragraph, and "strike all of this" / "bold all
of this" is a claim about words nobody made. `advice` rides the paragraph
freely: it changes nothing, and its span is a pointer, not an assertion.

THE ACCENT WIDTH RULE (founder 2026-08-15): "try not to style the whole
paragraphs or chunks but key few words or a sentence — so effectively
delete that." A bold's quote is now capped at ONE SENTENCE by
`is_accent_width`, and a bold that cannot narrow to it is DROPPED rather
than widened to the whole piece. The old whole-window fallback was not a
rare edge: the Confident Voice card is generated with no LLM at all, so
its only narrowing signal was the say-it-stronger UPGRADE wordings — a
list that is empty by construction for a moment delivered well, since
say-it-stronger only proposes upgrades where the wording is WEAK. Every
confident bold therefore fell through to "bold the entire piece". The
generator now picks the phrase up front (services.moment_suggestions
.pick_emphasis_phrase, verbatim-pinned) and stores it on the row, so the
narrowing normally succeeds; the drop is the floor under it, not the
common path.

AC-9/CONSTRUCT: `source`/`device` are the closed vocabularies already in
use; the internal trigger vocabulary (threat/charisma/…) never rides a
user payload — 'polish' is the one trigger the FE may distinguish.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from services.transcript_document import WORD_GRAIN

logger = logging.getLogger(__name__)

# What the FE may receive in `source` (copy keys, never internals).
# ⚠️ KEEP COMPLETE. The audit found this missing new_take and acoustic_swap —
# two LIVE lanes — while claiming to be the contract; anyone hardening the
# serve against it would have killed both.
SOURCES = ("polish", "profanity", "wording", "confident_voice", "prior_take",
           "delivery", "structural", "new_take", "acoustic_swap",
           "coach_revision")

# Kinds that make a claim ABOUT SPECIFIC WORDS — the ones that must decline
# a coarse anchor. `advice` is deliberately absent: it is the one kind whose
# span points rather than asserts.
_WORD_PRECISE_KINDS = ("replace", "bold")

# The acoustic swap lane. The internal TRIGGER (persisted) and the SERVED
# source are separate strings on purpose — the trigger vocabulary never rides
# a user payload, and this is the one lane where the two would otherwise be
# confused for each other.
_SWAP_TRIGGER = "acoustic_swap"
_SWAP_SOURCE = "acoustic_swap"


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

# THE ACCENT WIDTH RULE (founder 2026-08-15). The widest thing that may
# carry an accent: "key few words or a SENTENCE", never a paragraph or a
# chunk. Two conditions, and both have to hold.
#
# The character cap is the backstop, not the rule. Spoken transcripts run
# long without punctuation — a breathless run-on is one "sentence" by the
# regex and a paragraph to a reader — so a hard ceiling catches what the
# sentence test cannot. 160 is generous for one long spoken sentence and
# far below any chunk.
_MAX_BOLD_SPAN = 160

# An INTERNAL sentence break: a terminator followed by whitespace (so a
# trailing full stop does not count as one), or a line break. Closing
# quotes/brackets may sit between the two. Deliberately naive about
# abbreviations — "Mr. Smith" reads as two sentences here and the accent is
# declined, which errs toward the founder's instruction rather than away
# from it, and speech transcripts carry very few of them.
_SENTENCE_BREAK_RE = re.compile(r"[.!?…。！？][\"'’”\)\]]?\s|\n")


def is_accent_width(s: Any) -> bool:
    """Is `s` narrow enough to be STYLED — at most one sentence, and no
    longer than the cap? The one definition of the founder's "key few words
    or a sentence", shared by the generator (which asks the model to pick a
    phrase this narrow) and the serve (which refuses to bold anything
    wider). Pure."""
    t = s.strip() if isinstance(s, str) else ""
    if not t or len(t) > _MAX_BOLD_SPAN:
        return False
    return _SENTENCE_BREAK_RE.search(t) is None


def key_phrases_from_say_it_stronger(sis: Any) -> list:
    """The say-it-stronger UPGRADE wordings for a snippet — the founder's
    chosen emphasis-narrowing signal (T3, 2026-07-23). Verbatim strings,
    capped; the same source _key_phrases reads. Pure."""
    if not isinstance(sis, dict):
        return []
    out: list[str] = []
    seen: set[str] = set()
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
            low = window_text.lower()
            # ① THE PHRASE THE MODEL PICKED (founder 2026-08-15). Chosen at
            # generation time from the moment's own words and pinned verbatim
            # there; re-checked here because the served document may have
            # moved on since. Must still be INSIDE this window, still narrower
            # than it, and still of accent width — a stored quote is evidence,
            # not authority.
            picked = sug.get("emphasis_quote")
            picked = picked.strip() if isinstance(picked, str) else ""
            if picked and len(picked) < len(window_text):
                i = low.find(picked.lower())
                if i >= 0:
                    cand = window_text[i:i + len(picked)]
                    if is_accent_width(cand):
                        return cand
            # ② Bold only the strongest phrase, not the whole fragment
            # (founder T3): the first say-it-stronger upgrade wording that
            # occurs in this window AND is genuinely narrower than it.
            # Return the window's OWN slice (case-exact), so the caller's
            # substring anchor lands.
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
        # THE CONFIDENT VOICE CARD (founder mini-brief 2026-08-14, §17
        # acoustic-confidence-v1): its OWN source, so the FE can title it
        # "Confident Voice" and key its signed body — the trigger never
        # rides the payload. Both vocabularies on purpose: historical rows
        # keep the words they were written with (charisma-era rows stay
        # interpretable; the construct is retired, the rows are corpus).
        if sug.get("trigger") in ("confident", "charisma"):
            return ("bold", "confident_voice")
        return ("bold", "wording")
    if k == "replace":
        if sug.get("trigger") == "polish":
            return ("replace", "polish")
        if sug.get("trigger") == "profanity":
            return ("replace", "profanity")
        # The acoustic swap lane (founder 2026-08-13) — its OWN source, not
        # 'wording'. The FE labels it "Delivery" and it is exempt from the
        # paragraph-grain decline below; both need to tell it apart from an
        # ordinary replace, and the trigger does not ride the payload.
        if sug.get("trigger") == _SWAP_TRIGGER:
            return ("replace", _SWAP_SOURCE)
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
            # Narrowing found the phrase INSIDE the window, so this anchor is
            # word-exact however the window itself was established — the words
            # are demonstrably on screen. Coarse-grained pieces are welcome
            # here; the check below is only for the whole-window fallback.
            start, end = w_start + rel, w_start + rel + len(quote)
        else:
            # THE WHOLE-WINDOW FALLBACK, and the paragraph-grain decline.
            #
            # Falling back means "the change is about the entire piece". At
            # word grain that is a sentence the student actually said, which
            # is what these lanes have always meant. At PARAGRAPH grain the
            # piece IS the paragraph, and the same fallback silently promotes
            # every change to whole-paragraph scope: a `replace` renders as
            # "strike this whole chunk, here is one sentence instead", and a
            # `bold` accents the entire chunk — the exact whole-fragment
            # problem T3 was built to kill, at maximum width.
            #
            # So composition and accentuation abstain, and only `advice`
            # survives — it alters nothing and its span merely points at the
            # region the coaching is about, which a paragraph honestly is.
            # THE SWAP LANE IS EXEMPT, and it is the one exemption that does
            # not weaken the rule (founder 2026-08-13). The decline exists
            # because a whole-paragraph quote OVERSTATES an ordinary replace:
            # the lane meant "these exact words" and the fallback silently
            # widened it to "this whole chunk". The acoustic swap means the
            # whole paragraph in the first place — it offers this take's
            # delivery of a LOCKED PART, and a part IS a paragraph. Its quote
            # is not a widened claim, it is the claim. Declining it at
            # paragraph grain would mute the lane exactly where it applies,
            # since a locked chunk is precisely what gets a coarse anchor.
            if p.get("anchor_grain", WORD_GRAIN) != WORD_GRAIN \
                    and kind in _WORD_PRECISE_KINDS \
                    and source != _SWAP_SOURCE:
                logger.info(
                    "tracked_changes: declining %s/%s on snippet=%s — piece is "
                    "anchored at PARAGRAPH grain and narrowing found no exact "
                    "phrase, so the quote would be the whole paragraph",
                    kind, source, sid)
                continue
            # THE ACCENT WIDTH RULE, at every grain (founder 2026-08-15).
            # The paragraph-grain decline above already refused the widest
            # case; this refuses the rest of it. A `bold` whose narrowing
            # failed would take the ENTIRE piece, and a piece is routinely
            # several sentences — "style the whole chunk", which is exactly
            # what the founder asked to delete. A single-sentence piece still
            # falls through and is bolded whole: that is "or a sentence",
            # which he allowed in the same breath.
            #
            # Only `bold` is held to this. `replace` states which words to
            # swap and `advice` only points; neither becomes a claim about
            # emphasis by being wide.
            if kind == "bold" and not is_accent_width(window_text):
                logger.info(
                    "tracked_changes: declining bold/%s on snippet=%s — "
                    "narrowing found no phrase and the piece is wider than an "
                    "accent (%d chars), so the quote would be the whole chunk",
                    source, sid, len(window_text))
                continue
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
        if source == "confident_voice":
            # The founder-signed body renders FE-side by KEY (the FE's
            # closed why vocabulary holds the copy — LIVE LOOP): "You
            # sounded incredibly confident and natural here."
            entry["why_key"] = "confident_voice"
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
            # THE PRAISE LANE'S EVIDENCE (founder 2026-08-15: "explain using
            # the vocal and verbal cues"). KEYS only, from the closed
            # delivery_cues vocabulary — the FE holds a sentence per key, so
            # this can carry no number and no unsigned-off wording (AC-9 +
            # LIVE LOOP). Filtered rather than trusted: a row written before
            # the vocabulary existed, or by a future writer, must not put an
            # unknown key on a user payload.
            _cues = sug.get("cue_keys")
            if isinstance(_cues, (list, tuple)):
                from services.delivery_cues import CUE_KEYS as _KNOWN
                _cues = [c for c in _cues
                         if isinstance(c, str) and c in _KNOWN]
                if _cues:
                    entry["cue_keys"] = _cues
        out.append(entry)
    out.sort(key=lambda c: (c["span"]["start"], c["span"]["end"]))
    return out


def build_coach_revision_changes(text: Any, pieces: Any, suggestions: Any,
                                  ledger: Any, verdicts: Any) -> list:
    """Emit a coach supersession as a fresh proposal against accepted words.

    The accepted replacement in the decision ledger is immutable input. A
    later coach correction or rejection never mutates the served document.
    """
    doc = text if isinstance(text, str) else ""
    if not doc:
        return []
    sugs = suggestions if isinstance(suggestions, dict) else {}
    judged = verdicts if isinstance(verdicts, dict) else {}
    rows = [r for r in (ledger or []) if isinstance(r, dict)]
    from services.ideal_decision_ledger import normalize_phrase
    decided_targets = {
        (r.get("kind"), r.get("target_phrase")) for r in rows
        if r.get("kind") and r.get("target_phrase")
    }
    piece_by_sid: dict[str, dict[str, Any]] = {
        str(p.get("snippet_id")): p for p in (pieces or [])
        if isinstance(p, dict) and p.get("snippet_id")
    }
    approved = [r for r in rows
                if r.get("decision") == "approved"
                and r.get("source") == "user_star"
                and r.get("kind") in ("replace", "polish")
                and r.get("snippet_id")]
    approved.sort(key=lambda r: (r.get("updated_at") or "",
                                 int(r.get("version") or 0)), reverse=True)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for accepted in approved:
        sid = str(accepted.get("snippet_id"))
        if sid in seen:
            continue
        seen.add(sid)
        current = (accepted.get("replacement_text") or "").strip()
        original = (accepted.get("display_phrase") or "").strip()
        if not current or doc.count(current) != 1:
            continue
        target_norm = normalize_phrase(current)
        if (("replace", target_norm) in decided_targets
                or ("polish", target_norm) in decided_targets):
            continue
        verdict_raw = judged.get(sid)
        verdict_row: dict[str, Any] = (
            verdict_raw if isinstance(verdict_raw, dict) else {})
        verdict = verdict_row.get("verdict")
        sug_raw = sugs.get(sid)
        sug: dict[str, Any] = sug_raw if isinstance(sug_raw, dict) else {}
        if verdict in ("wrong_kind", "should_not_fire"):
            proposed = original
            coach_note = verdict_row.get("note")
        elif verdict == "keep" and sug.get("replacement_text_final"):
            proposed = (sug.get("replacement_text_final") or "").strip()
            coach_note = sug.get("why_final") or sug.get("why")
        else:
            continue
        if not proposed or proposed == current:
            continue
        start = doc.find(current)
        piece = piece_by_sid.get(sid) or {}
        out.append({
            "id": f"coach-revision:{sid}",
            "snippet_id": sid,
            "take_session_id": piece.get("take_session_id"),
            "kind": "replace",
            "source": "coach_revision",
            "span": {"start": start, "end": start + len(current)},
            "quote": current,
            "proposed_text": proposed,
            "coach_note": coach_note,
        })
    out.sort(key=lambda c: (
        int((c.get("span") or {}).get("start") or 0),
        int((c.get("span") or {}).get("end") or 0),
    ))
    return out


def _lane_rank(change: Any) -> int:
    """Precedence when two lanes want the same words (founder 2026-08-13):
    CORRECTIONS > SWAP > STYLE. Lower sorts first = wins.

    Stated explicitly rather than left to emerge from span width, because
    width gets the middle case WRONG. The tie-break below prefers the
    narrower span as "more specific", which is right for advice but backwards
    for the swap: the swap's span is a whole paragraph BY CONSTRUCTION (it
    offers a locked part's replacement), so it is the widest change on the
    document and would lose every collision to any narrow style bold — a
    'make this word orange' suggestion silently outranking 'you delivered
    this whole paragraph better'. Content still wins, which is the rule that
    matters; style does not.
    """
    c = change if isinstance(change, dict) else {}
    if c.get("source") == _SWAP_SOURCE:
        return 1
    if c.get("style_lane") or c.get("kind") == "bold":
        return 2
    return 0        # corrections: replace/advice from every other lane


def drop_overlaps(changes: Any) -> list:
    """One span may carry only ONE change. Two lanes can legitimately
    fire on the same words (a polish star and a cross-take offer) — the
    FE would render overlapping strikes. Earliest start wins; on a tie the
    LANE PRECEDENCE decides, and only then the narrower span. Pure."""
    ordered = sorted(
        [c for c in (changes or []) if isinstance(c, dict) and c.get("span")],
        key=lambda c: (c["span"]["start"],
                       _lane_rank(c),
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
