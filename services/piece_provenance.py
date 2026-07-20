"""The discernment system — per-piece provenance + approve-gated swaps
(founder 2026-07-20, "it is critical; crystal clear code").

The model, exactly as the founder stated it:
  * The master text is a per-piece MIX of takes; every piece carries a
    VERSION BADGE = the take it came from (provenance, not a score).
  * The ranking still judges every piece across all takes (F1 unchanged —
    the best actual take wins the comparison).
  * A new take that does NOT beat the incumbent piece changes nothing —
    the badge quietly holds ("my take 1 held its ground"), zero action.
  * A new take that DOES beat the incumbent NEVER swaps silently: the
    incumbent stays displayed, the piece goes 'pending_swap' with the
    challenger + a deterministic why-key; ACCEPT lands the swap (badge
    flips, version bumps), REJECT pins the incumbent (the challenger is
    remembered and never re-offered).
  * Decisions repeat per take → the 80/20 → 48/20/32 convergence. The
    percentages stay internal (AC-9); the badges tell the story.

Flag: DISCERNMENT_PROVENANCE_ENABLED (default OFF → assembly behaves
byte-for-byte as today: the ranking winner lands silently, no provenance).

Hardening (adversarial review 2026-07-20 — every point below closed a
confirmed finding):
  * FULL-ROW WRITES: every row write carries the complete incumbent block
    — a partial upsert would violate the table's NOT NULL on INSERT and
    fail silently against the real DB (the #221 bug class).
  * DISPLAY-TEXT FREEZE: incumbent_text freezes what the loop DISPLAYS
    (the light-edited/coach-corrected line), never the raw verbatim — a
    challenger's arrival must not rewrite the piece. Held-ground passes
    REFRESH it, so coach corrections keep flowing while uncontested.
  * IDENTITY REALIGNMENT: slots are positional (deckless especially) —
    an incumbent SNIPPET that reappears as the winner of a different slot
    carries its provenance (and rejected memory) to the new slot instead
    of producing duplicate pieces + bogus pending swaps.
  * CLEAN SUBSTITUTION: a substituted incumbent never inherits the
    winner's breakthrough badge, key phrases, or audio span.
  * READ-FAIL ≠ EMPTY: a provenance read failure (None) skips discernment
    for the pass — it must never re-pin winners over pending/rejected
    state.
  * An empty frozen text can't display → the slot honestly re-pins the
    winner rather than serving a hole.

Why-keys (deterministic, NO LLM, copy lives FE-side):
  'energy'     — pitch variation / loudness range clearly higher
  'steadiness' — pausing clearly closer to breathing room
  'coverage'   — clearly tighter to the slide's content
  'overall'    — the blend won without one dominant observable factor
CONSTRUCT/AC-9: the keys are the entire vocabulary — no numbers, no
internal terms, in storage or on the wire.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

WHY_KEYS = ("energy", "steadiness", "coverage", "overall")

# One factor must beat the incumbent by this relative margin to become THE
# stated reason; below it the honest answer is 'overall'.
_DOMINANCE = 0.15


def discernment_enabled() -> bool:
    return (os.getenv("DISCERNMENT_PROVENANCE_ENABLED") or "0")\
        .strip().lower() in ("1", "true", "yes")


def _stickiness(snip: Any) -> Optional[float]:
    if not isinstance(snip, dict):
        return None
    m = snip.get("metrics") if isinstance(snip.get("metrics"), dict) else {}
    s = m.get("slide_stickiness")
    if isinstance(s, dict):
        s = s.get("composite")
    if isinstance(s, bool) or not isinstance(s, (int, float)):
        return None
    return float(s)


def swap_why_key(incumbent_snip: Any, challenger_snip: Any) -> str:
    """The deterministic reason the challenger outranked the incumbent —
    the largest RELATIVE improvement among the observable factors, or
    'overall' when nothing clearly dominates. Pure; degrades to 'overall'
    on missing metrics (honest, never invented)."""
    try:
        from services.delivery_stars import normalize_features
        im = normalize_features((incumbent_snip or {}).get("metrics"))
        cm = normalize_features((challenger_snip or {}).get("metrics"))

        def _gain(*keys) -> float:
            best = 0.0
            for k in keys:
                a, b = im.get(k), cm.get(k)
                if a is None or b is None or a == 0:
                    continue
                best = max(best, (b - a) / abs(a))
            return best

        candidates = [
            (_gain("f0_sd", "dynamic_db"), "energy"),
            # Steadiness = pausing moved TOWARD breathing room: more
            # pause_ratio is the one direction we can call an improvement
            # without a personal baseline.
            (_gain("pause_ratio"), "steadiness"),
        ]
        i_st, c_st = _stickiness(incumbent_snip), _stickiness(challenger_snip)
        if i_st is not None and c_st is not None and i_st > 0:
            candidates.append(((c_st - i_st) / abs(i_st), "coverage"))
        candidates.sort(key=lambda t: -t[0])
        if candidates and candidates[0][0] >= _DOMINANCE:
            return candidates[0][1]
        return "overall"
    except Exception:
        return "overall"


def _display_text(slide: Any) -> str:
    """What the assembly loop actually SHOWS for a pick — the light-edited
    / coach-corrected line when one exists, the raw verbatim otherwise.
    This (never the bare verbatim) is what an incumbent freezes as."""
    return ((slide.get("text") or "").strip()
            or (slide.get("verbatim") or "").strip())


def _incumbent_block(*, snippet_id, session_id, take_index, text) -> dict:
    """The complete incumbent column set — EVERY row write includes it so
    the upsert's INSERT arm always satisfies the table's NOT NULL (the
    #221 bug class: a partial update-shaped write would fail silently
    against the real DB)."""
    return {
        "incumbent_snippet_id": str(snippet_id),
        "incumbent_session_id": session_id,
        "incumbent_take_index": take_index,
        "incumbent_text": text,
    }


_NO_CHALLENGER = {
    "challenger_snippet_id": None,
    "challenger_session_id": None,
    "challenger_take_index": None,
    "challenger_text": None,
    "challenger_why": None,
}


def resolve_discernment(bp_slides: Any, rows: Any, database,
                        arc_id: Any) -> tuple:
    """The assembly-time core. Takes the ranking's winners (bp slides) and
    the provenance rows; returns (slides_out, piece_meta):

      slides_out — the bp slides with the INCUMBENT substituted wherever a
        row holds one that differs from the winner (pinned or pending) —
        the loop downstream (bake/polish/anchors) runs on these unchanged;
      piece_meta — [{piece_key, snippet_id, take_session_id, take_index,
        status, challenger|None, _row_write}] in slot order; the caller
        fills each entry's final `text` post-bake and persists the writes.

    Slot resolution per slide (identity beats position):
      1. the winner snippet IS an existing incumbent (this slot or any
         other) → HELD GROUND here — provenance (incl. the rejected
         memory) follows the snippet to this slot, incumbent block
         refreshed from the live pick;
      2. this slot's incumbent moved to another slot (it wins elsewhere)
         → the slot has a new identity → FIRST SIGHT pins the winner;
      3. this slot's incumbent holds but the winner differs → REJECTED
         challenger re-pins quietly; otherwise PENDING (incumbent keeps
         displaying, challenger + why recorded);
      4. no row → FIRST SIGHT.

    Pure except snippet metric reads for the why-key (best-effort)."""
    rows_by_key: dict = {}
    rows_by_snip: dict = {}
    for r in (rows or []):
        try:
            k = int(r.get("piece_key"))
        except (TypeError, ValueError):
            continue
        rows_by_key[k] = r
        inc = str(r.get("incumbent_snippet_id") or "")
        if inc:
            rows_by_snip[inc] = r

    # Every snippet that wins SOME slot this pass — used to detect an
    # incumbent that moved slots (realignment, not a challenge).
    winner_snips = {
        str(s.get("snippet_id"))
        for s in (bp_slides or [])
        if isinstance(s, dict) and s.get("snippet_id")
    }

    slides_out, meta = [], []
    for s in (bp_slides or []):
        if not isinstance(s, dict):
            continue
        key = s.get("index")
        winner_snip = s.get("snippet_id")
        if not isinstance(key, int) or not winner_snip:
            slides_out.append(s)   # filler slot — no pick, no provenance
            continue
        winner_snip = str(winner_snip)
        row_here = rows_by_key.get(key)
        row_of_winner = rows_by_snip.get(winner_snip)

        if row_of_winner is not None:
            # (1) The winner already IS an incumbent — held ground, its
            # provenance follows it here (slot realignment). The incumbent
            # block refreshes from the LIVE pick so coach corrections keep
            # flowing while uncontested.
            slides_out.append(s)
            write = _incumbent_block(
                snippet_id=winner_snip,
                session_id=s.get("session_id"),
                take_index=s.get("take_index"),
                text=_display_text(s))
            write["status"] = "settled"
            write.update(_NO_CHALLENGER)
            _rej = [str(x) for x
                    in (row_of_winner.get("rejected_snippet_ids") or []) if x]
            if _rej:
                write["rejected_snippet_ids"] = _rej
            meta.append({
                "piece_key": key,
                "snippet_id": winner_snip,
                "take_session_id": s.get("session_id"),
                "take_index": s.get("take_index"),
                "status": "settled",
                "challenger": None,
                "_row_write": write,
            })
            continue

        inc_snip = str((row_here or {}).get("incumbent_snippet_id") or "")
        inc_text = ((row_here or {}).get("incumbent_text") or "").strip()

        if row_here is None or inc_snip in winner_snips or not inc_text:
            # (2)/(4) First sight — no row, the slot's old incumbent moved
            # to another slot (new identity here), or the frozen text is
            # unusable (an empty piece must never serve a hole).
            slides_out.append(s)
            write = _incumbent_block(
                snippet_id=winner_snip,
                session_id=s.get("session_id"),
                take_index=s.get("take_index"),
                text=_display_text(s))
            write["status"] = "settled"
            write.update(_NO_CHALLENGER)
            meta.append({
                "piece_key": key,
                "snippet_id": winner_snip,
                "take_session_id": s.get("session_id"),
                "take_index": s.get("take_index"),
                "status": "settled",
                "challenger": None,
                "_row_write": write,
            })
            continue

        # (3) A real contest: the slot's incumbent stands, the winner
        # differs. The displayed slide becomes the INCUMBENT — clean
        # substitution: no inherited breakthrough badge, key phrases, or
        # audio span (those belong to the winner, not the incumbent).
        rejected = {str(x) for x
                    in (row_here.get("rejected_snippet_ids") or []) if x}
        sub = dict(s)
        sub["text"] = inc_text
        sub["verbatim"] = inc_text
        sub["polished"] = False
        sub["snippet_id"] = inc_snip
        sub["session_id"] = row_here.get("incumbent_session_id")
        sub["take_index"] = row_here.get("incumbent_take_index")
        sub["breakthrough"] = False
        sub["breakthrough_note"] = None
        sub["key_phrases"] = []
        sub["audio_ref"] = None
        sub["start_offset_ms"] = None
        sub["duration_ms"] = None
        slides_out.append(sub)

        base = _incumbent_block(
            snippet_id=inc_snip,
            session_id=row_here.get("incumbent_session_id"),
            take_index=row_here.get("incumbent_take_index"),
            text=inc_text)

        if winner_snip in rejected:
            write = dict(base)
            write["status"] = "settled"
            write.update(_NO_CHALLENGER)
            meta.append({
                "piece_key": key,
                "snippet_id": inc_snip,
                "take_session_id": row_here.get("incumbent_session_id"),
                "take_index": row_here.get("incumbent_take_index"),
                "status": "settled",
                "challenger": None,
                "_row_write": write,
            })
            continue

        why = "overall"
        try:
            _get = getattr(database, "get_snippet_by_id", None)
            if callable(_get):
                why = swap_why_key(_get(inc_snip), _get(winner_snip))
        except Exception:
            why = "overall"
        challenger = {
            "snippet_id": winner_snip,
            "take_session_id": s.get("session_id"),
            "take_index": s.get("take_index"),
            "text": _display_text(s),
            "why": why,
        }
        write = dict(base)
        write.update({
            "status": "pending_swap",
            "challenger_snippet_id": winner_snip,
            "challenger_session_id": s.get("session_id"),
            "challenger_take_index": s.get("take_index"),
            "challenger_text": challenger["text"],
            "challenger_why": why,
        })
        meta.append({
            "piece_key": key,
            "snippet_id": inc_snip,
            "take_session_id": row_here.get("incumbent_session_id"),
            "take_index": row_here.get("incumbent_take_index"),
            "status": "pending_swap",
            "challenger": challenger,
            "_row_write": write,
        })
    return slides_out, meta


def _row_matches_write(row: Any, fields: dict) -> bool:
    """True when every written field already equals the stored row —
    the skip-if-unchanged guard (one flag-ON assembly must not rewrite
    every row on every pass)."""
    if not isinstance(row, dict):
        return False
    for k, v in fields.items():
        have = row.get(k)
        if k == "rejected_snippet_ids":
            have = sorted(str(x) for x in (have or []))
            v = sorted(str(x) for x in (v or []))
        if have != v:
            return False
    return True


def persist_piece_meta(database, arc_id: Any, meta: Any,
                       existing_rows: Any = None) -> int:
    """Write the per-slot row updates (incl. the final display_text the
    caller filled in), skipping rows that already match, and PRUNE rows
    for slots the current assembly no longer produces (no phantom pieces
    on the serve payload). Best-effort — a missing table degrades to no
    provenance, never breaks assembly."""
    by_key = {}
    for r in (existing_rows or []):
        try:
            by_key[int(r.get("piece_key"))] = r
        except (TypeError, ValueError):
            continue
    written = 0
    live_keys = set()
    for m in (meta or []):
        try:
            key = int(m["piece_key"])
            live_keys.add(key)
            fields = dict(m.get("_row_write") or {})
            if m.get("text") is not None:
                fields["display_text"] = m["text"]
            if _row_matches_write(by_key.get(key), fields):
                continue
            ok = database.upsert_ideal_piece_provenance(
                str(arc_id), key, fields)
            if ok:
                written += 1
        except Exception as e:
            logger.warning("piece_provenance: write failed arc=%s key=%s: %s",
                           arc_id, m.get("piece_key"), e)
    for key in set(by_key) - live_keys:
        try:
            database.delete_ideal_piece_provenance(str(arc_id), key)
        except Exception:
            pass
    return written
