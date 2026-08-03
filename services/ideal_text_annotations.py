"""Per-sentence ideal-text correction capture (founder 2026-07-27,
learning-pipeline item 3).

WHAT THIS IS. When the coach VERIFIES an arc's ideal text (POST
/coach/arc/<id>/verify — the coach's one finalize action under the single
deliverable), diff the machine's frozen auto draft (coach_arc_ideal_text.
auto_text) against the verified text SENTENCE BY SENTENCE and emit each
changed pair into admin_annotation_events. The sentence the coach actually
rewrote is the lesson; a whole-block diff is too noisy to train on — one
comma fix would mark 20,000 characters as "corrected".

WHY VERIFY (and not "coach_finalized"). The founder's spec said "at the
coach_finalized event", but `coach_finalized` is not an event — it is a
COMPUTED read over best-presentation edits (routes/v2_routes.py, mirroring
services/best_presentation.py) that never fires anywhere. The actual
finalize act on the ideal text is VERIFY: db.verify_ideal_text snapshots
verified_text/verified_version and — load-bearing here — returns 'already'
when the version is unchanged, so emission inherits exactly-once-per-version
without any bookkeeping of its own.

AMENDMENT (FE close-out 2026-07-28): the shipped FE's Verify button posts
/ideal-text/approve and nothing in the FE calls /verify — so the approve
route ALSO emits, guarded by db.has_ideal_text_annotations (first approve
captures, re-approves skip; approve has no version bookkeeping to key on).
The /verify hook stays, with its richer per-version exactly-once, for
whenever the FE moves to it.

WHAT A PAIR IS. Sentences are aligned with difflib over marker-stripped,
whitespace/case-normalized forms. Contiguous changed runs emit as ONE pair
(draft run → final run): when the coach merges two sentences into one or
splits one into two, the merge/split IS the lesson — forcing 1:1 index
pairing would misalign every sentence after it. Insertions emit with an
empty draft side, deletions with an empty final side (the SFT export skips
empty-final rows; the DPO export requires both sides — both behaviors are
correct for those consumers, and the corpus keeps the fact).

MARKERS. Both sides are stripped of the rich markers (**bold**, __underline__,
{{orange:…}}, [[moment:…]] wrappers) before comparison AND before emission —
marker placement is formatting, not wording, and identical stripping on both
sides means a marker-only edit correctly reads as "no text change". The //
italic marker is deliberately LEFT ALONE: sanitize_markers documents that //
collides with URLs, and mangling https:// to teach a model italics is a bad
trade. An italic-only edit therefore reads as a (harmless, rare) text pair.

FENCES. Coach->machine capture only — nothing here is surfaced to anyone
(AC-9), nothing mutates the text (L1), and nothing reads or writes the blind
labeling lane (BLIND COACH). Best-effort throughout: any failure logs and
returns 0; a verify NEVER breaks because capture hiccuped (LIVE LOOP).
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Any

logger = logging.getLogger(__name__)

# Sentence boundary: a run of terminal punctuation (incl. ellipsis), plus any
# closing quotes/brackets riding it, followed by whitespace or end-of-text.
# Scanning for the boundary (finditer) instead of a lookbehind split is what
# makes `he said "go." Next` split AFTER the closing quote — a fixed-width
# lookbehind sees the quote, not the period, and misses it. Abbreviation
# periods ("Dr. Smith") do split — the same limitation as the repo's existing
# `(?<=[.!?])\s+` splitters, and harmless here: an over-split cancels out of
# the diff as long as both sides split identically.
_SENT_BOUNDARY_RE = re.compile(r'[.!?…]+["\'”’)\]]*(?=\s|$)')

# Marker tokens stripped before diffing (see MARKERS above; // stays).
_BOLD_TOKEN = "**"
_UNDERLINE_TOKEN = "__"
_ACCENT_OPEN = "{{orange:"
_ACCENT_CLOSE = "}}"

# Emission bounds: a pathological rewrite (the coach replaced the whole block)
# must not fan out into hundreds of rows, and the unchanged-block endorsement
# must not ship 20k chars into one event.
_MAX_PAIRS = 120
_MAX_EVENT_CHARS = 4000

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def strip_for_diff(text: Any) -> str:
    """The block with moment wrappers and rich-marker tokens removed.

    Identical treatment of draft and final is the invariant that makes the
    diff honest: a marker-only edit cancels out, a wording edit survives.
    Pure; "" for non-strings."""
    if not isinstance(text, str) or not text:
        return ""
    try:
        from services.ideal_text_block import strip_moment_markers
        out = strip_moment_markers(text)
    except Exception:
        out = text
    # strip_moment_markers drops matched spans and bare OPENERS, but an
    # orphan closer (the coach deleted the opener mid-edit) survives it —
    # remove those too or they pollute emitted pair text (review finding).
    out = out.replace("[[/moment]]", "")
    out = out.replace(_BOLD_TOKEN, "").replace(_UNDERLINE_TOKEN, "")
    out = out.replace(_ACCENT_OPEN, "").replace(_ACCENT_CLOSE, "")
    return out


def draft_is_stale(auto_updated_at: Any, coach_updated_at: Any,
                   coach_owned: bool) -> bool:
    """True when the machine draft was refreshed AFTER the coach's last edit
    of a coach-owned row — i.e. the coach's text was written against an OLDER
    machine draft than the one we'd diff against.

    THE false-correction guard (review finding, HIGH): coach verifies v1, the
    user records another take (persist_auto_ideal_text refreshes auto_text →
    v2), coach re-verifies. Diffing the v2 draft against v1-era coach text
    would attribute every machine v1↔v2 difference to the coach. Staleness →
    the caller SKIPS pair emission (honest silence beats invented signal).

    Fail-closed: unparseable timestamps on a coach-owned row read as stale.
    A machine-owned row is never stale (its text IS the draft). Pure."""
    if not coach_owned:
        return False
    if not auto_updated_at:
        return False   # no machine refresh recorded → nothing newer to race
    if not coach_updated_at:
        return True    # coach-owned but no edit stamp → cannot vouch, skip
    try:
        from datetime import datetime
        auto = datetime.fromisoformat(str(auto_updated_at))
        coach = datetime.fromisoformat(str(coach_updated_at))
        return auto > coach
    except (TypeError, ValueError):
        return True


def split_sentences(text: Any) -> list:
    """Split a block into sentences, newline-aware.

    Paragraph breaks are hard boundaries first (the block is assembled as
    \\n\\n-joined paragraphs), then each paragraph splits on terminal
    punctuation. A fragment that starts with a closing quote/bracket is
    re-attached to its predecessor. Whole-paragraph fallback when a paragraph
    has no terminals at all. Pure."""
    if not isinstance(text, str) or not text.strip():
        return []
    out: list = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        pos = 0
        for m in _SENT_BOUNDARY_RE.finditer(para):
            seg = para[pos:m.end()].strip()
            if seg:
                out.append(seg)
            pos = m.end()
        tail = para[pos:].strip()
        if tail:
            out.append(tail)   # no-terminal fallback: the run is a sentence
    return out


def _norm(sentence: str) -> str:
    """The alignment key — case/whitespace-insensitive, so a re-spaced or
    re-capitalized sentence reads as unchanged (mirrors the publish emitter's
    approved_as_is comparison)."""
    return " ".join(sentence.split()).casefold()


def sentence_pairs(draft_text: Any, final_text: Any) -> list:
    """Align draft vs final sentences → the changed pairs.

    Returns [{"draft": str, "final": str, "op": "replace"|"insert"|"delete"},
    ...] where draft/final are the JOINED changed runs ("" on the absent
    side). Equal runs never emit. Pure, deterministic."""
    draft_sents = split_sentences(strip_for_diff(draft_text))
    final_sents = split_sentences(strip_for_diff(final_text))
    if not draft_sents and not final_sents:
        return []
    sm = SequenceMatcher(
        a=[_norm(s) for s in draft_sents],
        b=[_norm(s) for s in final_sents],
        autojunk=False,
    )
    pairs: list = []
    for op, a0, a1, b0, b1 in sm.get_opcodes():
        if op == "equal":
            continue
        d = " ".join(draft_sents[a0:a1]).strip()
        f = " ".join(final_sents[b0:b1]).strip()
        if not d and not f:
            continue
        # Reflow-only run (review finding): a paragraph-break move re-splits
        # the same words into different SENTENCE LISTS, so the matcher flags
        # the run — but the joined text is identical. Emitting it would file
        # an identical-text "correction" AND (by making pairs non-empty)
        # suppress the approved_as_is endorsement. Same-content runs drop.
        if _norm(d) == _norm(f):
            continue
        pairs.append({
            "draft": d,
            "final": f,
            "op": ("replace" if d and f else ("insert" if f else "delete")),
        })
    return pairs


def emit_ideal_text_annotations(
    database,
    *,
    arc_id: Any,
    owner_user_id: Any,
    coach_user_id: Any,
    draft_text: Any,
    final_text: Any,
    auto_updated_at: Any = None,
    coach_updated_at: Any = None,
    coach_owned: bool = False,
) -> int:
    """Emit the verify-time correction events. Returns rows written.

    Per changed pair: one row, section_type='ideal_text',
    field_name='ideal_text_sentence', ai_original_text=draft side (None on
    insert), coach_final_text=final side (None on delete), reason_chip=None.

    No changes at all: ONE block-level endorsement row,
    field_name='ideal_text_block', reason_chip='approved_as_is' — the coach
    verified the machine's text untouched, which is signal too (mirrors the
    prose lane's approved_as_is convention).

    No draft to compare (auto_text empty — legacy rows from before the
    auto-copy migration): emit NOTHING. An absent draft is an honest absence;
    diffing against "" would mark the whole block as coach-written, which is
    exactly the false signal this module exists to avoid.

    Best-effort: returns 0 on any failure, never raises."""
    try:
        if not owner_user_id:
            logger.warning("ideal_text_annotations: no owner — skipping "
                           "arc=%s", arc_id)
            return 0
        draft = draft_text if isinstance(draft_text, str) else ""
        final = final_text if isinstance(final_text, str) else ""
        if not draft.strip():
            logger.info("ideal_text_annotations: empty auto draft — nothing "
                        "to diff arc=%s", arc_id)
            return 0
        if not final.strip():
            return 0
        if draft_is_stale(auto_updated_at, coach_updated_at, coach_owned):
            # The machine refreshed the draft after the coach's last edit —
            # the coach's text answers an OLDER draft, so a diff would file
            # machine-vs-machine differences as coach corrections. Skip.
            logger.info("ideal_text_annotations: draft newer than the coach "
                        "text — skipping (stale diff) arc=%s", arc_id)
            return 0

        arc_uuid = str(arc_id) if isinstance(arc_id, str) \
            and _UUID_RE.match(str(arc_id)) else None
        pairs = sentence_pairs(draft, final)
        written = 0

        if not pairs:
            database.create_admin_annotation_event(
                user_id=str(owner_user_id),
                session_id=None,
                section_type="ideal_text",
                field_name="ideal_text_block",
                ai_original_text=strip_for_diff(draft)[:_MAX_EVENT_CHARS],
                coach_final_text=strip_for_diff(final)[:_MAX_EVENT_CHARS],
                reason_chip="approved_as_is",
                custom_reason=None,
                created_by=str(coach_user_id or ""),
                draft_id=arc_uuid,
            )
            return 1

        dropped = max(0, len(pairs) - _MAX_PAIRS)
        for p in pairs[:_MAX_PAIRS]:
            database.create_admin_annotation_event(
                user_id=str(owner_user_id),
                session_id=None,
                section_type="ideal_text",
                field_name="ideal_text_sentence",
                ai_original_text=(p["draft"][:_MAX_EVENT_CHARS] or None),
                coach_final_text=(p["final"][:_MAX_EVENT_CHARS] or None),
                reason_chip=None,
                custom_reason=None,
                created_by=str(coach_user_id or ""),
                draft_id=arc_uuid,
            )
            written += 1
        if dropped:
            logger.warning(
                "ideal_text_annotations: capped at %d pairs (%d dropped) "
                "arc=%s", _MAX_PAIRS, dropped, arc_id,
            )
        return written
    except Exception as e:
        logger.warning("ideal_text_annotations: emit failed arc=%s: %s "
                       "(non-fatal)", arc_id, e)
        return 0
