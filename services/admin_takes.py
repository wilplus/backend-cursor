"""One person's Takes with their acoustic data, for the admin profile
(founder 2026-10-14: "all acoustic data explorable per take", in the user
profile).

Admin only. These numbers never reach a speaker (CLAUDE.md, never #1).

  takes(user_id)          every Take, newest first: the Take row's own
                          measures plus averages of its pieces' acoustic
                          blobs, its AI clip (the problem practised and the
                          next try's outcome; for fillers, hesitations per
                          100 words before and after), its anchored
                          willfidence and the fixes it gave with whether
                          each came back on the next Take
                          (``services.take_progress``, N291), and the
                          person's current acoustic baseline
  pieces(user_id, sid)    one Take's pieces, each with every measure stored
  transcripts_export(uid) every Take's full transcript, ONLY while the person
                          holds the training yes (founder 2026-10-26, WIL-110;
                          the profile's Export CSV; founder-only route)

The Take rows carry a one-line preview of the transcript, never the whole
text: the full text leaves only through ``transcripts_export``.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from services.db import db

logger = logging.getLogger(__name__)

MAX_TAKES = 200
#: The newest Takes whose fixes are checked against the next Take (two
#: frame reads each).
MAX_FIX_TAKES = 40

#: The most characters of a Take's transcript on its row (one line).
PREVIEW_CHARS = 160

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


def _slide_texts(session: dict, own: list[dict]) -> list[str]:
    """What the speaker said in this Take, one text per slide: the whole
    per-slide transcript when the Take holds it, else its pieces in the
    order they were said."""
    slides = session.get("slide_transcripts")
    texts = [str(s.get("transcript") or "").strip() for s in slides if isinstance(s, dict)] \
        if isinstance(slides, list) else []
    texts = [t for t in texts if t]
    if texts:
        return texts
    ordered = sorted(own, key=lambda p: _num(p.get("start_offset_ms")) or 0)
    return [t for t in (str(p.get("transcript") or "").strip() for p in ordered) if t]


def _preview(texts: list[str]) -> str:
    """The transcript as one line of at most PREVIEW_CHARS, cut at a word."""
    flat = " ".join(" ".join(texts).split())
    if len(flat) <= PREVIEW_CHARS:
        return flat
    cut = flat[:PREVIEW_CHARS]
    return (cut[: cut.rfind(" ")] if " " in cut else cut) + "…"


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


def _anchored(pieces: list[dict], reference: Optional[dict]) -> Optional[int]:
    """The Take's anchored willfidence in whole percent (N291 item 2)."""
    from services.take_progress import anchored_willfidence
    value = anchored_willfidence(pieces, reference)
    return round(100 * value) if value is not None else None


def _next_takes(sessions: list[dict]) -> dict[str, str]:
    """Each Take's next Take of the same talk, by id."""
    by_arc: dict[str, list[dict]] = {}
    for s in sessions:
        if s.get("arc_id"):
            by_arc.setdefault(str(s["arc_id"]), []).append(s)
    out: dict[str, str] = {}
    for takes_ in by_arc.values():
        ordered = sorted(takes_, key=lambda s: (s.get("take_index") or 0, str(s.get("created_at") or "")))
        for here, after in zip(ordered, ordered[1:]):
            out[str(here["id"])] = str(after["id"])
    return out


def takes(user_id: str) -> dict:
    from services.take_progress import fix_outcomes, frozen_reference
    sessions = db.takes.list_sessions_for_user_admin(user_id)[:MAX_TAKES]
    pieces = db.get_snippets_by_sessions([s["id"] for s in sessions])
    oldest = sorted(sessions, key=lambda s: str(s.get("created_at") or ""))
    reference = frozen_reference([[p.get("metrics") for p in pieces.get(str(s["id"])) or []]
                                  for s in oldest if pieces.get(str(s["id"]))])
    next_of = _next_takes(sessions)
    fix_ids = {str(s["id"]) for s in sessions[:MAX_FIX_TAKES]}
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
            "transcript": _preview(_slide_texts(s, own)),
            "piece_means": _piece_means(own),
            "willfidence": _willfidence(own),
            "willfidence_anchored": _anchored(own, reference),
            "fixes": (fix_outcomes(db, s["id"], next_of.get(str(s["id"])))
                      if str(s["id"]) in fix_ids else []),
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


def transcripts_export(user_id: str) -> dict:
    """Every Take's full transcript for the profile's CSV, only while this
    person holds the training yes (Privacy 3.7 section 4: the person who runs
    WillpowerLab may see transcripts, but the policy names no export of them,
    so the file carries only what the speaker said yes to for learning).

    ``{"allowed": False, "transcripts": {}}`` without the yes, and on any
    doubt: an unreadable consent, an unreadable project state. A project the
    speaker erased or archived is left out, as in Will's own lookup. The
    text is keyed by Take id; the caller logs the release.
    """
    from services import pair_consent
    from services.project_deletion import ProjectDeletionService
    refused: dict = {"allowed": False, "transcripts": {}}
    if not pair_consent.user_holds_training_yes(db, user_id):
        return refused
    sessions = db.takes.list_sessions_for_user_admin(user_id)[:MAX_TAKES]
    try:
        arcs = {str(s["arc_id"]) for s in sessions if s.get("arc_id")}
        service = ProjectDeletionService(db)
        hidden = service.erased_projects(arcs) | service.archived_projects(arcs)
    except Exception:
        logger.warning("admin transcripts: project state unreadable user=%s", user_id, exc_info=True)
        return refused
    kept = [s for s in sessions if str(s.get("arc_id") or "") not in hidden]
    pieces = db.get_snippets_by_sessions([s["id"] for s in kept])
    out = {}
    for s in kept:
        texts = _slide_texts(s, pieces.get(str(s["id"])) or [])
        if texts:
            out[str(s["id"])] = "\n".join(texts)
    return {"allowed": True, "transcripts": out}
