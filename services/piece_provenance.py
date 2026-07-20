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

Why-keys (deterministic, NO LLM, copy lives FE-side):
  'energy'     — pitch variation / loudness range clearly higher
  'steadiness' — pace / pausing clearly closer to the speaker's flow
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


def _f(metrics: Any, key: str) -> Optional[float]:
    v = (metrics or {}).get(key) if isinstance(metrics, dict) else None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


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
            # Steadiness = pausing/pace moved TOWARD breathing room: more
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


def resolve_discernment(bp_slides: Any, rows: Any, database,
                        arc_id: Any) -> tuple:
    """The assembly-time core. Takes the ranking's winners (bp slides) and
    the provenance rows; returns (slides_out, piece_meta):

      slides_out — the bp slides with the INCUMBENT substituted wherever a
        row holds one that differs from the winner (pinned or pending) —
        the loop downstream (bake/polish/anchors) runs on these unchanged;
      piece_meta — [{piece_key, snippet_id, take_session_id, take_index,
        status, challenger{...}|None, _row_write{...}}] in slot order; the
        caller fills each entry's final `text` post-bake and persists the
        row writes.

    First sight of a slot pins the winner as incumbent (settled). A
    rejected challenger never re-offers. A challenger that lost the
    ranking again clears back to settled. Pure except snippet metric reads
    for the why-key (best-effort)."""
    by_key = {}
    for r in (rows or []):
        try:
            by_key[int(r.get("piece_key"))] = r
        except (TypeError, ValueError):
            continue

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
        row = by_key.get(key)

        if not row:
            # First sight: the winner IS the incumbent (settled).
            slides_out.append(s)
            meta.append({
                "piece_key": key,
                "snippet_id": winner_snip,
                "take_session_id": s.get("session_id"),
                "take_index": s.get("take_index"),
                "status": "settled",
                "challenger": None,
                "_row_write": {
                    "incumbent_snippet_id": winner_snip,
                    "incumbent_session_id": s.get("session_id"),
                    "incumbent_take_index": s.get("take_index"),
                    "incumbent_text": (s.get("verbatim")
                                       or s.get("text") or ""),
                    "status": "settled",
                    "challenger_snippet_id": None,
                    "challenger_session_id": None,
                    "challenger_take_index": None,
                    "challenger_text": None,
                    "challenger_why": None,
                },
            })
            continue

        inc_snip = str(row.get("incumbent_snippet_id") or "")
        rejected = {str(x) for x in (row.get("rejected_snippet_ids") or [])
                    if x}

        if winner_snip == inc_snip:
            # The incumbent held its ground — settled, any stale
            # challenger clears.
            slides_out.append(s)
            meta.append({
                "piece_key": key,
                "snippet_id": inc_snip,
                "take_session_id": s.get("session_id"),
                "take_index": s.get("take_index"),
                "status": "settled",
                "challenger": None,
                "_row_write": {
                    "status": "settled",
                    "challenger_snippet_id": None,
                    "challenger_session_id": None,
                    "challenger_take_index": None,
                    "challenger_text": None,
                    "challenger_why": None,
                },
            })
            continue

        # The winner differs from the incumbent → substitute the
        # incumbent into the displayed slide (the text NEVER swaps
        # silently), then either pin (rejected) or pend (challenger).
        sub = dict(s)
        sub["text"] = row.get("incumbent_text") or ""
        sub["verbatim"] = row.get("incumbent_text") or ""
        sub["polished"] = False   # the polish diff belonged to the winner
        sub["snippet_id"] = inc_snip
        sub["session_id"] = row.get("incumbent_session_id")
        sub["take_index"] = row.get("incumbent_take_index")
        slides_out.append(sub)

        if winner_snip in rejected:
            meta.append({
                "piece_key": key,
                "snippet_id": inc_snip,
                "take_session_id": row.get("incumbent_session_id"),
                "take_index": row.get("incumbent_take_index"),
                "status": "settled",
                "challenger": None,
                "_row_write": {
                    "status": "settled",
                    "challenger_snippet_id": None,
                    "challenger_session_id": None,
                    "challenger_take_index": None,
                    "challenger_text": None,
                    "challenger_why": None,
                },
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
            "text": (s.get("verbatim") or s.get("text") or ""),
            "why": why,
        }
        meta.append({
            "piece_key": key,
            "snippet_id": inc_snip,
            "take_session_id": row.get("incumbent_session_id"),
            "take_index": row.get("incumbent_take_index"),
            "status": "pending_swap",
            "challenger": challenger,
            "_row_write": {
                "status": "pending_swap",
                "challenger_snippet_id": winner_snip,
                "challenger_session_id": s.get("session_id"),
                "challenger_take_index": s.get("take_index"),
                "challenger_text": challenger["text"],
                "challenger_why": why,
            },
        })
    return slides_out, meta


def persist_piece_meta(database, arc_id: Any, meta: Any) -> int:
    """Write the per-slot row updates (incl. the final display_text the
    caller filled in). Best-effort — a missing table degrades to no
    provenance, never breaks assembly."""
    written = 0
    for m in (meta or []):
        try:
            fields = dict(m.get("_row_write") or {})
            if m.get("text") is not None:
                fields["display_text"] = m["text"]
            ok = database.upsert_ideal_piece_provenance(
                str(arc_id), int(m["piece_key"]), fields)
            if ok:
                written += 1
        except Exception as e:
            logger.warning("piece_provenance: write failed arc=%s key=%s: %s",
                           arc_id, m.get("piece_key"), e)
    return written
