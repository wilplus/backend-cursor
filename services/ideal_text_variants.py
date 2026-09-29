"""The VARIANT POOL + COMPOSITIONS (founder 2026-08-03) — blocks all the
way down, selection is a pointer.

The three usability fears this dissolves (founder: any one of them
"kills the app"):
  1. "after I correct my take and record the next one the previous one
     is lost" — every take's per-block segment lands in an APPEND-ONLY
     pool, winners and losers alike; nothing is overwritten when a newer
     offer arrives (the old single challenger slot did exactly that);
  2. "the next text is worse than the previous one" — "my text" is a
     COMPOSITION: an ordered list of {block_key, variant_id} pointers,
     append-only revisions + one head pointer; going back is repointing,
     never reconstruction;
  3. "some things from the previous and some from the new" — the picker
     lists every block's variants (block-level granularity, founder
     decision 2026-08-03) and select_block_variant mixes freely.

DUAL-WRITE, FLAG-GATED READ (the live-loop rollout): the blocks table
stays the assembly source of truth — every write here is best-effort
beside it and NEVER raises into the recording pipeline; the picker read
surfaces gate on BLOCK_VARIANTS_ENABLED (default OFF). Flag off, the
product is byte-for-byte today's.

The user's edit becomes a VARIANT, not a superseded blob: the whole-
document edit is word-diffed against the served master, changed regions
are attributed to blocks by span projection, and each touched block gets
a source='user_edit' variant — sitting beside the take variants in the
same picker with the same lifecycle. The correction-vs-restructuring
split stays upstream (transcript corrections ride the existing
correction lanes and REBUILD variants' source pieces; only restructuring
lands here as new variants).

L1: take variants are verbatim recorded pieces; user_edit variants are
the STUDENT's own words — never an AI rewrite. L2: offer judging stays
the blended ranking on the blocks lane, untouched. AC-9: variants carry
provenance (source, take_index) and text — never a score; a user-edited
incumbent has no acoustic measurements, so the auto-duel simply never
fires against it (both-sides-measured rule; their wording is never
force-challenged, rule 4).

Since audit C2 retired the master document, the picker, select, restore
and user-edit capture had no caller; they were deleted 2026-09-29. Take
capture and the composition snapshot remain.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"\S+")
_MAX_VARIANT_CHARS = 20000
_SNAPSHOT_RETRIES = 3


def variants_enabled() -> bool:
    """The READ gate (picker payload, select, revisions, restore) —
    default OFF; writes dual-run best-effort so history exists the day
    the flag flips."""
    return (os.getenv("BLOCK_VARIANTS_ENABLED") or "0").strip().lower() \
        in ("1", "true", "yes")


def _join_pieces(pieces: Any) -> str:
    """A block's display text from its pieces — the same single-space
    join the offer lane uses (upgrade_changes), so texts compare."""
    return " ".join((p.get("text") or "").strip()
                    for p in (pieces or [])
                    if (p.get("text") or "").strip()).strip()


def _norm(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    return " ".join(w.lower() for w in _WORD_RE.findall(text))


# ── pool capture ───────────────────────────────────────────────────────

def record_take_variant(database, arc_id: Any, block_key: Any,
                        session_id: Any, take_index: Any,
                        pieces: Any) -> Optional[dict]:
    """One take-sourced variant into the pool — idempotent per
    (arc, block, take): the partial unique index absorbs re-runs. None
    on duplicate/failure; never raises."""
    try:
        text = _join_pieces(pieces)
        if not text or not arc_id or not session_id:
            return None
        return database.insert_ideal_text_block_variant(
            str(arc_id), int(block_key), {
                "source_kind": "take",
                "take_session_id": str(session_id),
                "take_index": (int(take_index)
                               if isinstance(take_index, int) else None),
                "pieces": [{"snippet_id": p.get("snippet_id"),
                            "text": p.get("text")} for p in (pieces or [])],
                "text": text[:_MAX_VARIANT_CHARS],
            })
    except Exception as e:
        logger.warning("variants: take capture failed arc=%s key=%s: %s",
                       arc_id, block_key, e)
        return None


def capture_take_variants(database, arc_id: Any, session_id: Any,
                          take_index: Any, mapping: Any) -> int:
    """Every mapped segment of a new take → the pool, WINNERS AND LOSERS
    ALIKE — the fear-#1 fix: losing a duel (or being displaced by a
    newer offer) no longer loses the text. Best-effort, never raises."""
    written = 0
    try:
        for key, seg in (mapping or {}).items():
            if not seg:
                continue
            if record_take_variant(database, arc_id, key, session_id,
                                   take_index, seg):
                written += 1
    except Exception as e:
        logger.warning("variants: take sweep failed arc=%s: %s", arc_id, e)
    return written


def _variant_for_incumbent(database, arc_id: str, row: dict,
                           pool: list) -> Optional[str]:
    """The pool variant id a block's CURRENT incumbent corresponds to —
    matched by (block, take session) for recorded incumbents, by
    normalized text for user-edited ones; CREATED when the pool predates
    the row (self-healing on pre-pool arcs). None when unresolvable."""
    key = row.get("block_key")
    inc_sid = row.get("incumbent_take_session_id")
    inc_pieces = row.get("incumbent_pieces") or []
    if inc_sid:
        for v in pool:
            if v.get("block_key") == key \
                    and v.get("source_kind") == "take" \
                    and str(v.get("take_session_id")) == str(inc_sid):
                return str(v.get("id"))
        made = record_take_variant(database, arc_id, key, inc_sid,
                                   row.get("incumbent_take_index"),
                                   inc_pieces)
        return str(made.get("id")) if made else None
    # No origin take → a user-edited incumbent: match by text.
    inc_norm = _norm(_join_pieces(inc_pieces))
    if not inc_norm:
        return None
    for v in pool:
        if v.get("block_key") == key \
                and v.get("source_kind") == "user_edit" \
                and _norm(v.get("text")) == inc_norm:
            return str(v.get("id"))
    return None


def snapshot_composition(database, arc_id: Any, *, reason: str,
                         created_by: Any = None) -> Optional[int]:
    """Append the CURRENT selection state as the next composition
    revision + repoint head. Selections are derived from the live blocks
    (the assembly source of truth), so the composition lane can never
    drift from what the student actually sees. Missing pool rows are
    find-or-created (pre-pool arcs heal); a block that cannot resolve is
    skipped rather than blocking the snapshot. Returns the revision, or
    None (pre-migration / nothing to snapshot) — never raises."""
    try:
        rows = database.ideal_text.list_ideal_text_blocks(str(arc_id))
        if not rows:
            return None
        pool = database.list_ideal_text_block_variants(str(arc_id)) or []
        selections = []
        for row in sorted((r for r in rows if r.get("active", True)
                           and r.get("status") != "candidate"),
                          key=lambda r: r.get("block_key") or 0):
            vid = _variant_for_incumbent(database, str(arc_id), row, pool)
            if vid:
                selections.append({"block_key": row.get("block_key"),
                                   "variant_id": vid})
        if not selections:
            return None
        latest = database.list_ideal_text_compositions(str(arc_id), limit=1)
        next_rev = ((latest[0].get("revision") or 0) + 1) if latest else 1
        for attempt in range(_SNAPSHOT_RETRIES):
            if database.insert_ideal_text_composition(
                    str(arc_id), next_rev + attempt, selections, reason,
                    created_by):
                rev = next_rev + attempt
                database.set_ideal_text_composition_head(str(arc_id), rev)
                return rev
        return None
    except Exception as e:
        logger.warning("variants: snapshot failed arc=%s: %s", arc_id, e)
        return None
