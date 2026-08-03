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
"""
from __future__ import annotations

import difflib
import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"\S+")
# Below this whole-document similarity the edit is a wholesale rewrite —
# block attribution would be dishonest grafting (same philosophy and
# threshold as protected_phrases.decompose_user_edit).
_MIN_EDIT_RATIO = 0.5
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
        rows = database.list_ideal_text_blocks(str(arc_id))
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


# ── the user's edit as variants ────────────────────────────────────────

def _project(opcodes: list, w: int) -> int:
    """A word-BOUNDARY index in the base → the matching boundary in the
    edited text (monotone). Inside an equal run the offset carries over;
    inside a replace the boundary maps proportionally (a rewrite
    spanning two blocks splits its words between them instead of
    emptying one — the honest deterministic choice); a boundary at an
    opcode edge snaps to it. Pure."""
    for tag, i1, i2, j1, j2 in opcodes:
        if w <= i1:
            return j1
        if w < i2:
            if tag == "equal":
                return j1 + (w - i1)
            if i2 == i1:
                return j1
            return j1 + round((w - i1) * (j2 - j1) / (i2 - i1))
    return opcodes[-1][4] if opcodes else 0


def capture_user_edit_variants(database, arc_id: Any, user_id: Any,
                               base_text: Any, base_pieces: Any,
                               edited_text: Any) -> int:
    """The student's whole-document edit, attributed to BLOCKS: word-
    diff base→edited, project each block's span through the diff, and
    write a source='user_edit' variant for every block whose words
    changed. This is what makes the edit a first-class citizen of the
    picker instead of a blob a new take supersedes (fear #1).

    Boundary-crossing edits attach by proportional projection; a pure
    per-block deletion (empty projection) writes no variant in v1 (the
    deletion still rides the ledger lane); a wholesale rewrite (whole-
    document similarity < 0.5) writes nothing — grafting a rewrite
    piecewise would be dishonest (same rule as decompose_user_edit).
    Identical re-saves dedup against the pool. Returns variants written;
    best-effort, never raises."""
    try:
        if not isinstance(base_text, str) or not isinstance(edited_text, str):
            return 0
        if _norm(base_text) == _norm(edited_text):
            return 0
        a_tok = [(m.group(0), m.start(), m.end())
                 for m in _WORD_RE.finditer(base_text)]
        b_tok = [(m.group(0), m.start(), m.end())
                 for m in _WORD_RE.finditer(edited_text)]
        if not a_tok or not b_tok:
            return 0
        sm = difflib.SequenceMatcher(
            None, [t[0].lower() for t in a_tok],
            [t[0].lower() for t in b_tok], autojunk=False)
        if sm.ratio() < _MIN_EDIT_RATIO:
            return 0
        opcodes = sm.get_opcodes()

        # Each block's word range on the base: its pieces' char spans →
        # token indices (tokens never straddle piece joins — \S+ runs).
        by_block: dict = {}
        for p in (base_pieces or []):
            key = p.get("block_key")
            if key is None:
                continue
            s, e = p.get("start"), p.get("end")
            if not isinstance(s, int) or not isinstance(e, int):
                continue
            lo, hi = by_block.get(key, (None, None))
            by_block[key] = (s if lo is None else min(lo, s),
                             e if hi is None else max(hi, e))
        if not by_block:
            return 0

        pool = database.list_ideal_text_block_variants(str(arc_id))
        pool = pool or []
        written = 0
        for key in sorted(by_block):
            cs, ce = by_block[key]
            ws = next((i for i, t in enumerate(a_tok) if t[1] >= cs),
                      len(a_tok))
            we = next((i for i, t in enumerate(a_tok) if t[1] >= ce),
                      len(a_tok))
            if we <= ws:
                continue
            ps, pe = _project(opcodes, ws), _project(opcodes, we)
            if pe <= ps:
                continue        # projected empty — a deletion, no variant
            new_text = edited_text[b_tok[ps][1]:b_tok[pe - 1][2]].strip()
            base_block = base_text[cs:ce]
            if not new_text or _norm(new_text) == _norm(base_block):
                continue        # unchanged block
            if any(v.get("block_key") == key
                   and v.get("source_kind") == "user_edit"
                   and _norm(v.get("text")) == _norm(new_text)
                   for v in pool):
                continue        # identical re-save — already pooled
            made = database.insert_ideal_text_block_variant(
                str(arc_id), int(key), {
                    "source_kind": "user_edit",
                    "take_session_id": None,
                    "take_index": None,
                    "pieces": [],
                    "text": new_text[:_MAX_VARIANT_CHARS],
                    "created_by": (str(user_id) if user_id else None),
                })
            if made:
                pool.append(made)
                written += 1
        return written
    except Exception as e:
        logger.warning("variants: user-edit capture failed arc=%s: %s",
                       arc_id, e)
        return 0


# ── the picker ─────────────────────────────────────────────────────────

def block_variants_payload(database, arc_id: Any) -> Optional[dict]:
    """The picker read: per active block, every selectable variant —
    take variants in take order plus the LATEST user_edit variant
    (block-level granularity keeps the mobile picker clean; older edits
    stay in the pool for revision restore). The current incumbent is
    flagged, and always present even when the pool predates the arc
    (variant_id null — informational, nothing to select).

    AC-9: provenance and text only — no scores, no ranking numbers, no
    why vocabulary. None only when the BLOCK read fails (read-fail ≠
    empty)."""
    rows = database.list_ideal_text_blocks(str(arc_id))
    if rows is None:
        return None
    pool = database.list_ideal_text_block_variants(str(arc_id)) or []
    blocks = []
    for row in sorted((r for r in rows if r.get("active", True)
                       and r.get("status") != "candidate"),
                      key=lambda r: r.get("block_key") or 0):
        key = row.get("block_key")
        inc_sid = row.get("incumbent_take_session_id")
        inc_norm = _norm(_join_pieces(row.get("incumbent_pieces") or []))
        mine = [v for v in pool if v.get("block_key") == key]
        takes = sorted((v for v in mine if v.get("source_kind") == "take"),
                       key=lambda v: ((v.get("take_index")
                                       if isinstance(v.get("take_index"),
                                                     int) else 0),
                                      v.get("created_at") or ""))
        edits = [v for v in mine if v.get("source_kind") == "user_edit"]
        latest_edit = max(edits, key=lambda v: v.get("created_at") or "") \
            if edits else None

        def _entry(v):
            _is_take = v.get("source_kind") == "take"
            _current = (
                (inc_sid and _is_take
                 and str(v.get("take_session_id")) == str(inc_sid))
                or (not inc_sid and not _is_take
                    and _norm(v.get("text")) == inc_norm))
            return {
                "variant_id": str(v.get("id")),
                "source": v.get("source_kind"),
                "take_index": v.get("take_index"),
                "text": v.get("text"),
                "is_current": bool(_current),
            }

        entries = [_entry(v) for v in takes]
        if latest_edit is not None:
            entries.append(_entry(latest_edit))
        if not any(e["is_current"] for e in entries):
            _inc_text = _join_pieces(row.get("incumbent_pieces") or [])
            if _inc_text:
                # Pre-pool incumbent — shown, unselectable (IS current).
                entries.insert(0, {
                    "variant_id": None,
                    "source": ("take" if inc_sid else "user_edit"),
                    "take_index": row.get("incumbent_take_index"),
                    "text": _inc_text,
                    "is_current": True,
                })
        blocks.append({
            "block_key": key,
            "label": row.get("label"),
            "take_index": row.get("incumbent_take_index"),
            "variants": entries,
        })
    head = database.get_ideal_text_composition_head(str(arc_id)) or {}
    return {"blocks": blocks,
            "head_revision": head.get("head_revision")}


def select_block_variant(database, arc_id: Any, block_key: Any,
                         variant_id: Any, user_id: Any) -> tuple:
    """The mix-and-match decision (fear #3): point one block at any
    pooled variant. The incumbent flips to the variant's text/pieces,
    any pending offer clears (it was judged against the OLD incumbent),
    and a new composition revision records the selection. The displaced
    incumbent stays in the pool — selecting is never destructive.

    Returns (ok, error_code): NOT_FOUND / NOT_PENDING (candidate block)
    / WRITE_FAILED, mirroring decide_block for the route to map."""
    row = database.get_ideal_text_block(str(arc_id), int(block_key))
    if not row:
        return (False, "NOT_FOUND")
    if row.get("status") == "candidate":
        return (False, "NOT_PENDING")
    var = database.get_ideal_text_block_variant(str(arc_id), variant_id)
    if not var or var.get("block_key") != int(block_key):
        return (False, "NOT_FOUND")

    inc_sid = row.get("incumbent_take_session_id")
    if var.get("source_kind") == "take":
        if inc_sid and str(var.get("take_session_id")) == str(inc_sid):
            return (True, None)     # already the incumbent — idempotent
    else:
        if not inc_sid and _norm(_join_pieces(
                row.get("incumbent_pieces") or [])) == _norm(var.get("text")):
            return (True, None)

    # HEAL FIRST (fear #1's corner): on a pre-pool arc the displaced
    # incumbent may exist nowhere else — pool it BEFORE repointing so
    # selecting away from it can never lose its text.
    try:
        pool = database.list_ideal_text_block_variants(str(arc_id)) or []
        _variant_for_incumbent(database, str(arc_id), row, pool)
    except Exception:
        pass

    if var.get("source_kind") == "take":
        fields = {
            "incumbent_take_session_id": var.get("take_session_id"),
            "incumbent_take_index": var.get("take_index"),
            "incumbent_pieces": var.get("pieces") or [],
        }
    else:
        # A user_edit incumbent: the student's own words, unmeasured —
        # carried as one piece with no snippet (the auto-duel never
        # fires against it: both-sides-measured rule, and their wording
        # is never force-challenged).
        fields = {
            "incumbent_take_session_id": None,
            "incumbent_take_index": None,
            "incumbent_pieces": [{"snippet_id": None,
                                  "text": var.get("text")}],
        }
    fields.update({
        "status": "settled",
        "challenger_take_session_id": None,
        "challenger_take_index": None,
        "challenger_pieces": None,
        "challenger_why": None,
    })
    ok = database.upsert_ideal_text_block(str(arc_id), int(block_key),
                                          fields)
    if not ok:
        return (False, "WRITE_FAILED")
    snapshot_composition(database, arc_id, reason="select",
                         created_by=user_id)
    return (True, None)


# ── revisions (undo / restore) ─────────────────────────────────────────

def restore_revision(database, arc_id: Any, revision: Any,
                     user_id: Any) -> tuple:
    """Repoint the document at an earlier composition (fear #2): each of
    the revision's selections writes through to its block's incumbent.
    Blocks the revision never knew (added later) stay as they are —
    restore repoints what it recorded, it never deletes; a selection
    whose variant or block is gone is skipped. The restore itself lands
    as a NEW revision (reason='restore'), so restoring is undoable too.

    Returns (ok, error_code): NOT_FOUND / WRITE_FAILED."""
    comp = database.get_ideal_text_composition(str(arc_id), int(revision))
    if not comp:
        return (False, "NOT_FOUND")
    any_write = False
    all_ok = True
    for sel in (comp.get("selections") or []):
        key = sel.get("block_key")
        var = database.get_ideal_text_block_variant(
            str(arc_id), sel.get("variant_id"))
        row = database.get_ideal_text_block(str(arc_id), key) \
            if isinstance(key, int) else None
        if not var or not row or row.get("status") == "candidate" \
                or var.get("block_key") != key:
            continue
        # Heal the block's CURRENT incumbent into the pool before
        # overwriting it (same fear-#1 corner as select).
        try:
            pool = database.list_ideal_text_block_variants(
                str(arc_id)) or []
            _variant_for_incumbent(database, str(arc_id), row, pool)
        except Exception:
            pass
        if var.get("source_kind") == "take":
            fields = {
                "incumbent_take_session_id": var.get("take_session_id"),
                "incumbent_take_index": var.get("take_index"),
                "incumbent_pieces": var.get("pieces") or [],
            }
        else:
            fields = {
                "incumbent_take_session_id": None,
                "incumbent_take_index": None,
                "incumbent_pieces": [{"snippet_id": None,
                                      "text": var.get("text")}],
            }
        fields.update({
            "status": "settled",
            "challenger_take_session_id": None,
            "challenger_take_index": None,
            "challenger_pieces": None,
            "challenger_why": None,
        })
        ok = database.upsert_ideal_text_block(str(arc_id), int(key), fields)
        any_write = any_write or ok
        all_ok = all_ok and ok
    if not any_write:
        return (False, "WRITE_FAILED")
    snapshot_composition(database, arc_id, reason="restore",
                         created_by=user_id)
    return (all_ok, None if all_ok else "WRITE_FAILED")
