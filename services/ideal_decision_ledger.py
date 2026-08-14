"""The ideal-text decision ledger (founder 2026-07-20) — gradual
refinement, step 2.

The five rules this module carries (founder sign-off):
  1. APPROVED = BAKED, forever forward — a change accepted in version N is
     part of the text in version N+1: applied at assemble time wherever the
     phrase still occurs, plain text, no star, never reversed.
  2. DISMISSED = REMEMBERED — never re-offered for the same phrase.
  3. Each version's stars are that version's DELTA only (falls out of 1+2:
     generation filters through the ledger).
  4. (PR-3) the student's recurring wording is protected.
  5. Quote-level display (shipped in the quote-narrowing pass).

Keys are NORMALIZED PHRASES, never snippet ids — decisions survive the
ranker re-picking a different take's piece across versions. A phrase that
no longer occurs in the new selection simply doesn't match: an approved
change applies only "if it applies" (founder's words), it is never grafted
onto different words.

L1: baking applies only what the student explicitly approved; the
verbatim-first canonical selection is untouched. AC-9: internal — nothing
here rides a user payload. Pure helpers + best-effort db calls.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from services.ideal_text_block import within_accent_window, wrap_accent

logger = logging.getLogger(__name__)

_WS = re.compile(r"\s+")


def normalize_phrase(text: Any) -> str:
    """The ledger matching key: lowercased, whitespace collapsed. Kept
    deliberately dumb — no stemming, no punctuation stripping — so a match
    means the student said (or approved) THESE words."""
    if not isinstance(text, str):
        return ""
    return _WS.sub(" ", text).strip().lower()


def _find_phrase(text: str, phrase: str) -> Optional[tuple]:
    """(start, end) of `phrase` in `text`, exact first then
    case-insensitive. None when absent."""
    if not text or not phrase:
        return None
    i = text.find(phrase)
    if i >= 0:
        return (i, i + len(phrase))
    low_t, low_p = text.lower(), phrase.lower()
    i = low_t.find(low_p)
    if i >= 0:
        return (i, i + len(phrase))
    return None


def ledger_keys(rows: Any) -> set:
    """{(kind, target_phrase)} over ANY decision — approved (baked) and
    dismissed (remembered) both mean: do not offer this again."""
    out = set()
    for r in (rows or []):
        k, p = r.get("kind"), r.get("target_phrase")
        if k and p:
            out.add((k, p))
    return out


def lane_class(kind: Any, *, source: Any = None, why: Any = None) -> str:
    """The deterministic suggestion CLASS a decision belongs to — §12.3's
    lane-class, the BE half of the deck's Clarity/Flow/Style/Delivery
    mapping (FE: displayKind in displayKind.ts; the contract test pins the
    two against each other). Internal vocabulary only — never surfaced.

    Same precedence as the FE: source before kind (an acoustic swap is
    kind='replace' but IS the delivery lane), kind before why."""
    if source == "acoustic_swap":
        return "delivery"
    if kind in ("emphasize", "bold"):
        return "style"
    if kind == "advice":
        return "flow"
    if why in ("energy", "steadiness", "coverage", "overall"):
        return "flow"
    return "clarity"


def intent_keys(rows: Any) -> set:
    """{(slide_index, lane_class)} over ANY decision that knows where it
    was made — §12.3's INTENT key. A declined Clarity on slide 2 blocks
    every future Clarity on slide 2, however the phrasing drifts (the
    phrase key catches nothing once the LLM rewords — field report #4).
    Rows from before the intent columns (NULL location/class) contribute
    nothing here and keep their phrase-key behavior exactly."""
    out = set()
    for r in (rows or []):
        si, lc = r.get("slide_index"), r.get("lane_class")
        if isinstance(si, int) and not isinstance(si, bool) and lc:
            out.add((si, lc))
    return out


def bake_piece(text: str, approved_rows: Any) -> str:
    """Apply the APPROVED decisions to one piece of assembled text —
    rule 1. Replaces/polishes swap the phrase for its replacement;
    emphasizes wrap {{orange:…}} (the same wire format the serve fold
    uses, so the FE renders baked and folded bolds identically). Longest
    phrase first (an overlapping shorter row must not pre-empt); one
    application per row (first occurrence); a phrase that doesn't occur is
    skipped — never grafted. Pure."""
    if not isinstance(text, str) or not text:
        return text
    rows = [r for r in (approved_rows or [])
            if r.get("decision") == "approved"]
    rows.sort(key=lambda r: -len(r.get("display_phrase")
                                 or r.get("target_phrase") or ""))
    for r in rows:
        phrase = (r.get("display_phrase") or "").strip()
        if not phrase:
            continue
        span = _find_phrase(text, phrase)
        if span is None:
            continue
        lo, hi = span
        found = text[lo:hi]
        if r.get("kind") in ("polish", "replace"):
            repl = (r.get("replacement_text") or "").strip()
            if repl == found:
                continue
            if not repl:
                # An empty replacement is a DELETION — honored only for
                # the student's own edit (source='user_edit', PR-3);
                # a generated suggestion may never wipe text.
                if r.get("source") != "user_edit":
                    continue
                text = re.sub(
                    r"[ \t]{2,}", " ", text[:lo] + text[hi:]).strip()
                continue
            text = text[:lo] + repl + text[hi:]
        elif r.get("kind") == "emphasize":
            if not within_accent_window(phrase):
                # §F.4 — emphasis is a UNIT-window intervention (founder
                # 2026-08-10). A moment accept's target is the WHOLE snippet
                # transcript, and painting it wrapped sentences in orange.
                # The row stays approved (the decision is the student's);
                # only the paint is refused. Words untouched.
                continue
            if "{{orange:" in found or text[max(0, lo - 9):lo].endswith(
                    "{{orange:"):
                continue   # already wrapped (baked earlier / coach copy)
            # wrap_accent, never a bare concatenation: an approved phrase
            # may itself contain a newline (_find_phrase is a literal find),
            # and a marker that straddles a paragraph break printed its own
            # syntax to the student (founder screenshot 2026-07-27).
            text = wrap_accent(text, lo, hi)
    return text


def record_star_decision(database, arc_id: Any, *, suggestion: Any,
                         target: str, action: str, target_text: Any,
                         snippet_id: Any = None,
                         version: Any = None,
                         slide_index: Any = None) -> bool:
    """Feedback-time write — maps one star tap onto the ledger:
      applied   → approved (bakes from the next assembly on)
      dismissed → dismissed (never offered again)
      reverted  → row deleted (clean slate — suggestible again)
    kind: moment_emphasize/document_bold → 'emphasize';
    moment_replace/document_replace → 'polish' when the suggestion row's
    trigger is polish, else 'replace'. Best-effort — a ledger miss must
    never break the feedback POST."""
    try:
        _replace_targets = ("moment_replace", "document_replace")
        _bold_targets = ("moment_emphasize", "document_bold")
        if not arc_id or target not in _replace_targets + _bold_targets:
            return False
        if action not in ("applied", "dismissed", "reverted"):
            return False
        phrase_raw = (target_text or "").strip()
        norm = normalize_phrase(phrase_raw)
        if not norm:
            return False
        sug = suggestion or {}
        if target in _bold_targets:
            kind = "emphasize"
        else:
            kind = "polish" if sug.get("trigger") == "polish" else "replace"
        if action == "reverted":
            return bool(database.delete_ideal_decision(
                str(arc_id), kind, norm))
        decision = "approved" if action == "applied" else "dismissed"
        # §12.3 — the INTENT key rides every new decision: WHERE it was
        # made (the snippet's slide — the only cross-take location) and
        # WHICH class was decided. The phrase key above stays for the bake
        # and history; these two are what the generation gate blocks on.
        _si = slide_index if isinstance(slide_index, int) \
            and not isinstance(slide_index, bool) else None
        return bool(database.upsert_ideal_decision(
            arc_id=str(arc_id), kind=kind, target_phrase=norm,
            display_phrase=phrase_raw,
            replacement_text=(sug.get("replacement_text")
                              if kind != "emphasize" else None),
            decision=decision, source="user_star",
            snippet_id=(str(snippet_id) if snippet_id else None),
            version=(version if isinstance(version, int) else None),
            slide_index=_si,
            lane_class=lane_class(kind, source=sug.get("trigger"),
                                  why=sug.get("why"))))
    except Exception as e:
        logger.warning("ideal_ledger: record failed arc=%s: %s", arc_id, e)
        return False


def load_ledger(database, arc_id: Any) -> list:
    """All ledger rows for an arc. Best-effort: [] pre-migration / on
    hiccup — assembly and generation degrade to today's behavior."""
    if not arc_id:
        return []
    try:
        return database.list_ideal_decisions(str(arc_id)) or []
    except Exception:
        return []
