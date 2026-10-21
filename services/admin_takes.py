"""One person's Takes with their acoustic data, for the admin profile
(founder 2026-10-14: "all acoustic data explorable per take", in the user
profile).

Admin only. These numbers never reach a speaker (CLAUDE.md, never #1).

  takes(user_id)          every Take, newest first: the Take row's own
                          measures plus averages of its pieces' acoustic
                          blobs, its AI clip (the problem practised and the
                          next try's outcome; for fillers, hesitations per
                          100 words before and after), and the person's
                          current acoustic baseline
  pieces(user_id, sid)    one Take's pieces, each with every measure stored
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from services.db import db

logger = logging.getLogger(__name__)

MAX_TAKES = 200

#: Measures stored on each piece's metrics blob that are averaged per Take.
PIECE_KEYS = ("f0_mean", "f0_sd", "f0_slope", "f0_mid_end_delta", "pause_count", "pause_ratio",
              "pause_regularity", "voiced_ratio", "voiced_duration_sec", "emphasis_per_min",
              "energy_ratio", "dynamic_db", "pitch_center_st", "wpm", "pause_ms")


def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _mean(values: list[float]) -> Optional[float]:
    return round(sum(values) / len(values), 3) if values else None


def _piece_means(pieces: list[dict]) -> dict:
    out: dict[str, Optional[float]] = {}
    for key in PIECE_KEYS:
        vals = [v for v in (_num((p.get("metrics") or {}).get(key)) for p in pieces) if v is not None]
        out[key] = _mean(vals)
    return out


def _willfidence(pieces: list[dict]) -> Optional[int]:
    """The Take's willfidence in whole percent (founder 2026-10-21): the mean
    of its pieces' S x W, the read the moments are picked by. Only pieces
    with a sound read count; None when there is none."""
    from services import moment_pick
    from services.voice_confidence import stamped_score
    reads = [moment_pick.read(stamped_score(p.get("metrics")), p.get("transcript"), p.get("metrics"))
             for p in pieces]
    heard = [r["value"] for r in reads if r["sound"]]
    return round(100 * sum(heard) / len(heard)) if heard else None


def _projects(ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    rows = (db.client.table("projects").select("id,display_name").in_("id", list(ids))
            .execute().data) or []
    return {str(r["id"]): r.get("display_name") or "" for r in rows}


def _ai_clips(user_id: str) -> dict[str, dict]:
    """Each Take's AI clip (the newest practice per Take), by Take id."""
    from services import ai_voice_store
    out: dict[str, dict] = {}
    for c in ai_voice_store.owner_cycles(db, user_id, limit=1000):
        take_id = str(c.get("take_session_id") or "")
        if not take_id or take_id in out:
            continue
        before, after = c.get("metrics_before") or {}, c.get("metrics_after") or {}
        out[take_id] = {
            "exercise": c.get("exercise"), "status": c.get("status"),
            "outcome": c.get("outcome"), "listened": bool(c.get("listened")),
            "plays": int(c.get("plays") or 0),
            "fillers_per_100_before": _num(before.get("fillers_per_100")),
            "fillers_per_100_after": _num(after.get("fillers_per_100")),
        }
    return out


def takes(user_id: str) -> dict:
    sessions = db.takes.list_sessions_for_user_admin(user_id)[:MAX_TAKES]
    pieces = db.get_snippets_by_sessions([s["id"] for s in sessions])
    clips = _ai_clips(user_id)
    try:
        names = _projects({str(s["project_id"]) for s in sessions if s.get("project_id")})
    except Exception:
        logger.warning("admin takes: project names unreadable user=%s", user_id, exc_info=True)
        names = {}
    rows = []
    for s in sessions:
        own = pieces.get(str(s["id"])) or []
        rows.append({
            "id": s["id"],
            "created_at": s.get("created_at"),
            "project": names.get(str(s.get("project_id") or ""), ""),
            "arc_id": s.get("arc_id"),
            "take_index": s.get("take_index"),
            "status": s.get("status"),
            "kind": s.get("recording_kind"),
            "duration_s": s.get("presentation_duration_seconds"),
            "pieces": len(own),
            "take": {
                "wpm": s.get("global_wpm"), "fillers": s.get("global_fillers"),
                "pause_ms": s.get("global_pause_ms"), "dynamic_db": s.get("global_dynamic_db"),
                "pitch_center": s.get("global_pitch_center"), "energy": s.get("global_energy"),
                "kpi_score": s.get("kpi_score"),
            },
            "piece_means": _piece_means(own),
            "willfidence": _willfidence(own),
            "ai_clip": clips.get(str(s["id"])),
        })
    baseline = None
    try:
        rows_b = (db.client.table("user_acoustic_baseline")
                  .select("features,n_sessions,n_samples,detector_version,computed_at")
                  .eq("user_id", str(user_id)).is_("superseded_at", "null")
                  .order("computed_at", desc=True).limit(1).execute().data) or []
        baseline = rows_b[0] if rows_b else None
    except Exception:
        logger.warning("admin takes: baseline unreadable user=%s", user_id, exc_info=True)
        baseline = None
    return {"takes": rows, "baseline": baseline}


def pieces(user_id: str, session_id: str) -> Optional[list[dict]]:
    """None when the Take is not this person's."""
    own = (db.client.table("v2_sessions").select("id").eq("id", session_id)
           .eq("user_id", user_id).limit(1).execute().data) or []
    if not own:
        return None
    from services.snippet_values import resolve_all
    out = []
    for p in db.get_snippets_by_sessions([session_id]).get(str(session_id)) or []:
        out.append({
            "id": p.get("id"),
            "start_ms": p.get("start_offset_ms"),
            "duration_ms": p.get("duration_ms"),
            "type": p.get("snippet_type"),
            "transcript": p.get("transcript") or "",
            "values": resolve_all(p),
            "metrics": {k: v for k, v in (p.get("metrics") or {}).items() if k != "intensity_envelope"},
        })
    return out
