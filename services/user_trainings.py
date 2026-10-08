"""The training tab / project list, grouped BY ARC (founder 2026-07-13),
read by GET /v2/user/trainings.

Two callers, one shape. The project picker (no flag) and Data & consent's
"Your projects" (``include_archived=1``, D-CS-4). The second is strict and
batched: a database error raises (the route answers 500 V2_ERROR, never an
empty list that reads as "no projects"), and the coach-edits check behind
``ideal_ready`` is one read for every project instead of one per project
with slides. The picker keeps today's behaviour exactly (LIVE LOOP): a
failed sessions read is an empty list and the check runs per project.

Per training: the takes (all recordings, take order), ``batch_verified``
(the coach's explicit arc publish landed), and ``ideal_ready``. AC-9: no
scores anywhere.
"""
from __future__ import annotations

from typing import Any, Callable, Optional


def _context(session: dict) -> dict:
    ctx = session.get("intake_context")
    return ctx if isinstance(ctx, dict) else {}


def _spoken(sessions: list) -> list:
    """Reads are paired variants of their spoken take (2026-07-14): they
    must not appear or count as takes of their own. Take order."""
    out = [s for s in sessions
           if s.get("recording_kind") != "read" and not s.get("paired_session_id")]
    out.sort(key=lambda s: (s.get("take_index") or 0))
    return out


def _deck(sessions: list) -> tuple[Optional[str], int, Any]:
    """(topic, slide count, cover ref): the latest take's topic wins; the
    cover is the first deck PDF across takes (founder 2026-07-15)."""
    topic, n_slides, cover_ref = None, 0, None
    for s in sessions:
        ctx = _context(s)
        t = ctx.get("topic")
        if isinstance(t, str) and t.strip():
            topic = t.strip()
        n_slides = max(n_slides, len(ctx.get("slides") or []))
        if cover_ref is None and ctx.get("presentation_ref"):
            cover_ref = ctx.get("presentation_ref")
    return topic, n_slides, cover_ref


def _take(s: dict) -> dict:
    published = bool(s.get("results_published_at"))
    return {
        "session_id": str(s.get("id")),
        "take_index": s.get("take_index"),
        "created_at": s.get("created_at"),
        "has_slides": bool(_context(s).get("slides")),
        "coach_reviewed": published,
        # The take opens its FEEDBACK page once published (founder
        # 2026-07-15) — alias kept beside coach_reviewed for the FE.
        "feedback_available": published,
    }


def _coach_finalized(edits: dict, n_slides: int) -> bool:
    """Cheap coach_finalized mirror (same rule as /progress): every deck
    slide coach-corrected. Deckless arcs become ideal_ready via the batch
    delivery itself."""
    return bool(n_slides) and all(
        isinstance(edits.get(i), str) and edits[i].strip() for i in range(n_slides))


def _training(aid: str, sess: list, delivered: Optional[dict],
              edits_for: Callable[[str], dict]) -> dict:
    from services.coach_video_storage import refreshed_media_url
    from services.slide_selection import TAKES_TARGET
    topic, n_slides, cover_ref = _deck(sess)
    finalized = _coach_finalized(edits_for(aid) if n_slides else {}, n_slides)
    return {
        "arc_id": aid,
        # FE also accepts "title"; the ideal-presentation deep link uses
        # best_presentation_arc_id (== arc_id here).
        "topic": topic,
        "best_presentation_arc_id": aid,
        "cover_ref": refreshed_media_url(cover_ref),
        "created_at": sess[0].get("created_at") if sess else None,
        "take_count": len(sess),
        "takes_target": TAKES_TARGET,
        "takes": [_take(s) for s in sess],
        "batch_verified": bool(delivered),
        "delivered_at": (delivered or {}).get("published_at"),
        "ideal_ready": bool(delivered) or finalized,
    }


def list_trainings(database: Any, user_id: Any, *, every_project: bool) -> list:
    """Every training of this user, newest first, stamped with its deletion
    and archive state (archived ones only when ``every_project``)."""
    from services.project_deletion import with_deletion_state
    if every_project:
        rows = database.takes.list_user_arc_sessions(user_id, strict=True) or []
    else:
        rows = database.takes.list_user_arc_sessions(user_id) or []
    by_arc: dict = {}
    for r in rows:
        if r.get("arc_id"):
            by_arc.setdefault(str(r["arc_id"]), []).append(r)
    deliveries = database.list_arc_batch_deliveries(list(by_arc.keys())) or {}
    if every_project:
        batched = database.get_coach_best_presentation_edits_for_arcs(list(by_arc.keys()))

        def edits_for(aid: str) -> dict:
            return (batched or {}).get(aid, {})
    else:
        def edits_for(aid: str) -> dict:
            return database.get_coach_best_presentation_edits(aid) or {}
    trainings = []
    for aid, sess in by_arc.items():
        spoken = _spoken(sess)
        if spoken:
            trainings.append(_training(aid, spoken, deliveries.get(aid), edits_for))
    trainings.sort(key=lambda t: t.get("created_at") or "", reverse=True)
    return with_deletion_state(database, trainings, every_project)
