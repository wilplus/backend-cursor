"""willab — Paid Audits, take-1-vs-take-2 comparison (BE chunk A6).

The neutral teaser shown at the paywall (after take 2): a side-by-side of RAW
acoustic aggregates for take 1 vs take 2, plus a NEUTRAL movement descriptor
for the pitch range. Reuses the per-snippet ``metrics`` (charisma_snippets)
already computed by the pipeline — no new analysis.

AC-9 / D8 (HARD): RAW VALUES + neutral movement words ONLY. NEVER a score, a
ratio, a verdict word (better/worse/stronger/improved/...), or any charisma/
stress vocabulary. The movement descriptor is drawn ONLY from
``_NEUTRAL_DESCRIPTORS`` ({widened, narrowed, steadied}); test_take_comparison
asserts a verdict denylist never appears in the serialized payload.
"""
from __future__ import annotations

from typing import Any, Optional

# The ONLY descriptor words this surface may emit — all neutral movement, no
# valence. (Pitch range got bigger / smaller / about the same.)
_NEUTRAL_DESCRIPTORS = ("widened", "narrowed", "steadied")

# Movement threshold: a change in f0 range counts only above max(absolute Hz,
# relative fraction) — below it, the range "steadied" (avoids noise reading as
# a change).
_RANGE_ABS_HZ = 5.0
_RANGE_REL = 0.10


def _default_db():
    from services.db import db
    return db


def _nums(values: list) -> list:
    return [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]


def _mean(values: list) -> Optional[float]:
    nums = _nums(values)
    return round(sum(nums) / len(nums), 1) if nums else None


def _take_metrics(snippets: list) -> dict:
    """Per-take RAW acoustic aggregates from the take's snippet metrics."""
    f0s, wpms, pauses = [], [], []
    for s in snippets or []:
        m = s.get("metrics") if isinstance(s, dict) and isinstance(s.get("metrics"), dict) else {}
        f0s.append(m.get("f0_mean"))
        wpms.append(m.get("wpm"))
        pauses.append(m.get("pause_ms"))
    f0_valid = _nums(f0s)
    if len(f0_valid) >= 2:
        f0_range = round(max(f0_valid) - min(f0_valid), 1)
    elif len(f0_valid) == 1:
        f0_range = 0.0
    else:
        f0_range = None
    return {
        "f0_mean_hz": _mean(f0s),
        "speech_rate_wpm": _mean(wpms),
        "f0_range_hz": f0_range,
        "pause_ms_mean": _mean(pauses),
    }


def _range_descriptor(t1_range: Any, t2_range: Any) -> Optional[str]:
    """Neutral movement of the pitch RANGE, take 2 vs take 1. None if either
    take lacks a range."""
    if not isinstance(t1_range, (int, float)) or not isinstance(t2_range, (int, float)):
        return None
    delta = t2_range - t1_range
    threshold = max(_RANGE_ABS_HZ, _RANGE_REL * abs(t1_range))
    if delta > threshold:
        return "widened"
    if delta < -threshold:
        return "narrowed"
    return "steadied"


def _signed_delta(a: Any, b: Any) -> Optional[float]:
    """b - a, rounded; None if either missing. RAW signed difference (neutral)."""
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return None
    return round(b - a, 1)


def _read_snippets(db, sess_ids: list) -> dict:
    """{sid: [snippets]} for the takes — batched when available."""
    if not sess_ids:
        return {}
    if hasattr(db, "get_snippets_by_sessions"):
        batch = db.get_snippets_by_sessions(sess_ids, include_words=False)
        if batch is not None:
            return {str(k): v for k, v in batch.items()}
    out = {}
    for sid in sess_ids:
        out[str(sid)] = db.get_snippets_by_session(sid) if sid else []
    return out


def build_take_comparison(arc_id: Optional[str], *, database=None) -> dict:
    """Take-1-vs-take-2 comparison payload for an arc.

    Response::

        {
          "arc_id": ...,
          "take_count": <int — takes with at least one snippet>,
          "takes": [ {"take_index": 1, "snippet_count": n, "metrics": {...}},
                     {"take_index": 2, "snippet_count": n, "metrics": {...}} ],
          "comparison": {                      # take 2 vs take 1; None if <2 takes
            "f0_range": "widened"|"narrowed"|"steadied"|None,
            "deltas": { "f0_mean_hz", "speech_rate_wpm",
                        "f0_range_hz", "pause_ms_mean" }   # RAW signed
          } | None
        }

    Best-effort: empty/partial arc → take_count reflects what's there,
    comparison is None until both takes exist.
    """
    db = database if database is not None else _default_db()
    sessions = db.get_arc_sessions(arc_id) if arc_id else []

    # Order by take_index, keep the first two takes (take 1 vs take 2).
    def _ti(s):
        v = s.get("take_index")
        return v if isinstance(v, int) else 9999
    ordered = sorted(
        [s for s in sessions if isinstance(s, dict)], key=_ti,
    )[:2]

    snips_by_sid = _read_snippets(db, [s.get("id") for s in ordered if s.get("id")])

    takes = []
    for s in ordered:
        sid = str(s.get("id"))
        snippets = snips_by_sid.get(sid, []) or []
        takes.append({
            "take_index": s.get("take_index"),
            "snippet_count": len(snippets),
            "metrics": _take_metrics(snippets),
        })

    comparison = None
    if len(takes) >= 2:
        m1, m2 = takes[0]["metrics"], takes[1]["metrics"]
        comparison = {
            "f0_range": _range_descriptor(m1.get("f0_range_hz"), m2.get("f0_range_hz")),
            "deltas": {
                k: _signed_delta(m1.get(k), m2.get(k))
                for k in ("f0_mean_hz", "speech_rate_wpm", "f0_range_hz", "pause_ms_mean")
            },
        }

    return {
        "arc_id": arc_id,
        "take_count": sum(1 for t in takes if t["snippet_count"] > 0),
        "takes": takes,
        "comparison": comparison,
    }
