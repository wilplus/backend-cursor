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
(the coach's explicit arc publish landed), ``ideal_ready``, and the compact
practice history used by the project chat. A chunk keeps its own range,
attempt count, and plain-language delivery label. The only number shown to
the speaker is the project-level progress percentage; detector scores remain
private implementation evidence.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional


_DELIVERY_LABELS = (
    (80, "Strong delivery"),
    (60, "Good"),
    (40, "Almost"),
    (0, "Not yet there"),
)

logger = logging.getLogger(__name__)


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
        # The upload key the Take was sent with (null for a Take made another
        # way): a Take kept on the phone knows by it whether it arrived, and
        # whether a newer Take of its project is on the server (N556 item 3).
        "upload_key": s.get("upload_idempotency_key"),
        "has_slides": bool(_context(s).get("slides")),
        "coach_reviewed": published,
        # The take opens its FEEDBACK page once published (founder
        # 2026-07-15) — alias kept beside coach_reviewed for the FE.
        "feedback_available": published,
    }


def _practice_range(session: dict) -> tuple[int, int] | None:
    """The actual first/last slide shown during this recording, one-based."""
    advances = _context(session).get("slide_advances")
    if not isinstance(advances, list):
        return None
    slides: list[int] = []
    for advance in advances:
        if not isinstance(advance, dict):
            continue
        index = advance.get("index")
        slide = advance.get("slide")
        if isinstance(index, int) and not isinstance(index, bool) and index >= 0:
            slides.append(index + 1)
        elif isinstance(slide, int) and not isinstance(slide, bool) and slide >= 1:
            slides.append(slide)
    return (min(slides), max(slides)) if slides else None


def _delivery_read(rows: list[dict]) -> tuple[int, str]:
    """Translate surfaced feedback into the four signed product labels.

    Attempts never improve this read. Praise/confident evidence raises it; a
    clarity rewrite lowers it. No evidence stays conservatively at the first
    label instead of inventing confidence.
    """
    families = [str(row.get("feedback_family") or "") for row in rows
                if isinstance(row, dict) and row.get("surfaced")]
    positive = sum(f in ("confident_voice", "great_formulation", "strong")
                   for f in families)
    rewrite = sum(f in ("rewrite_clarity", "rewrite_for_clarity", "to_work_on")
                  for f in families)
    if positive and not rewrite:
        score = 90
    elif positive > rewrite:
        score = 70
    elif positive and positive == rewrite:
        score = 50
    else:
        score = 25
    label = next(label for floor, label in _DELIVERY_LABELS if score >= floor)
    return score, label


def _practice_summary(sessions: list[dict], drafts_by_session: dict,
                      n_slides: int) -> tuple[int, list[dict]]:
    """Project progress and chronological exact-range chunks.

    For overlapping practice, every slide uses the latest attempt that
    covered it. Unpractised slides contribute zero, so the top bar describes
    the whole presentation rather than effort or attempt count.
    """
    grouped: dict[tuple[int, int], dict] = {}
    for order, session in enumerate(sessions):
        slide_range = _practice_range(session)
        if slide_range is None:
            continue
        sid = str(session.get("id"))
        score, label = _delivery_read(list((drafts_by_session or {}).get(sid) or []))
        chunk = grouped.setdefault(slide_range, {
            "start_slide": slide_range[0],
            "end_slide": slide_range[1],
            "attempts": 0,
            "delivery_label": label,
            "latest_session_id": sid,
            "_score": score,
            "_order": order,
        })
        chunk.update({
            "attempts": int(chunk["attempts"]) + 1,
            "delivery_label": label,
            "latest_session_id": sid,
            "_score": score,
            "_order": order,
        })

    chunks = sorted(grouped.values(), key=lambda chunk: int(chunk["_order"]))
    if n_slides > 0:
        per_slide = [0] * n_slides
        for chunk in chunks:
            first = max(1, int(chunk["start_slide"]))
            last = min(n_slides, int(chunk["end_slide"]))
            for slide in range(first, last + 1):
                per_slide[slide - 1] = int(chunk["_score"])
        progress = round(sum(per_slide) / n_slides)
    elif chunks:
        progress = round(sum(int(chunk["_score"]) for chunk in chunks) / len(chunks))
    else:
        progress = 0
    public_chunks = [{key: value for key, value in chunk.items()
                      if not key.startswith("_")} for chunk in chunks]
    return progress, public_chunks


def _coach_finalized(edits: dict, n_slides: int) -> bool:
    """Cheap coach_finalized mirror (same rule as /progress): every deck
    slide coach-corrected. Deckless arcs become ideal_ready via the batch
    delivery itself."""
    return bool(n_slides) and all(
        isinstance(edits.get(i), str) and edits[i].strip() for i in range(n_slides))


def _training(aid: str, sess: list, delivered: Optional[dict],
              edits_for: Callable[[str], dict], drafts_by_session: dict) -> dict:
    from services.coach_video_storage import refreshed_media_url
    from services.slide_selection import TAKES_TARGET
    topic, n_slides, cover_ref = _deck(sess)
    practice_progress, practice_chunks = _practice_summary(
        sess, drafts_by_session, n_slides)
    finalized = _coach_finalized(edits_for(aid) if n_slides else {}, n_slides)
    return {
        "arc_id": aid,
        # FE also accepts "title"; the ideal-presentation deep link uses
        # best_presentation_arc_id (== arc_id here).
        "topic": topic,
        "best_presentation_arc_id": aid,
        "cover_ref": refreshed_media_url(cover_ref),
        "created_at": sess[0].get("created_at") if sess else None,
        # The newest spoken Take's time: the project with the newest is the
        # current one (N254, one project at a time).
        "last_take_at": max((str(s["created_at"]) for s in sess
                             if s.get("created_at")), default=None),
        "take_count": len(sess),
        "takes_target": TAKES_TARGET,
        "takes": [_take(s) for s in sess],
        "batch_verified": bool(delivered),
        "delivered_at": (delivered or {}).get("published_at"),
        "ideal_ready": bool(delivered) or finalized,
        "practice_progress": practice_progress,
        "practice_chunks": practice_chunks,
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
    spoken_ids = [str(row.get("id")) for rows in by_arc.values()
                  for row in _spoken(rows) if row.get("id")]
    try:
        drafts_by_session = (
            database.get_coach_snippet_drafts_by_sessions(spoken_ids) or {})
    except Exception:
        # Keep the project list available if feedback evidence is briefly
        # unreadable; the conservative fallback is "Not yet there".
        logger.warning("practice feedback evidence unreadable", exc_info=True)
        drafts_by_session = {}
    if every_project:
        batched = database.get_coach_best_presentation_edits_for_arcs(
            list(by_arc.keys()))
    else:
        batched = database.get_coach_best_presentation_edits_for_arcs(
            list(by_arc.keys()), strict=False)
    if batched is not None:
        def edits_for(aid: str) -> dict:
            return batched.get(aid, {})
    else:
        # The picker historically swallowed an individual coach-edits read
        # failure and kept the rest of the list available. Preserve that
        # behavior if the new batch read is unavailable.
        def edits_for(aid: str) -> dict:
            return database.get_coach_best_presentation_edits(aid) or {}
    trainings = []
    for aid, sess in by_arc.items():
        spoken = _spoken(sess)
        if spoken:
            trainings.append(_training(
                aid, spoken, deliveries.get(aid), edits_for, drafts_by_session))
    trainings.sort(key=lambda t: t.get("created_at") or "", reverse=True)
    return with_deletion_state(database, trainings, every_project)
