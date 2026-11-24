"""The training tab / project list, grouped BY ARC (founder 2026-07-13),
read by GET /v2/user/trainings.

Two callers, one shape. The project picker (no flag) and Data & consent's
"Your projects" (``include_archived=1``, D-CS-4). The second is strict and
batched: a database error raises (the route answers 500 V2_ERROR, never an
empty list that reads as "no projects"), and the coach-edits check behind
``ideal_ready`` is one read for every project instead of one per project
with slides. The picker keeps today's behaviour exactly (LIVE LOOP): a
failed sessions read is an empty list and the check runs per project.

Each project carries its ordered Takes, including each Take's recorded
slide range when the recording has slide advances. The project also reports
which distinct parts have been practised and whether its Ideal Text is ready.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from services.take_review_history import is_ready as _review_ready


_DECKLESS_PARTS = 3


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
    span = _practice_range(s)
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
        "review_available": _review_ready(s),
        **({"recorded_range": {"start_slide": span[0], "end_slide": span[1]}} if span else {}),
    }


def _practised_parts(session: dict) -> set[int]:
    """The actual slide or section advances, one-based."""
    advances = _context(session).get("slide_advances")
    if not isinstance(advances, list):
        return set()
    slides: set[int] = set()
    for advance in advances:
        if not isinstance(advance, dict):
            continue
        index = advance.get("index")
        slide = advance.get("slide")
        if isinstance(index, int) and not isinstance(index, bool) and index >= 0:
            slides.add(index + 1)
        elif isinstance(slide, int) and not isinstance(slide, bool) and slide >= 1:
            slides.add(slide)
    return slides


def _practice_range(session: dict) -> tuple[int, int] | None:
    slides = _practised_parts(session)
    return (min(slides), max(slides)) if slides else None


def _coverage(sessions: list, total: int, has_deck: bool) -> dict:
    """Coverage is the union of parts in delivered, spoken Takes."""
    total = total or _DECKLESS_PARTS
    parts: set[int] = set()
    for take in sessions:
        if _review_ready(take):
            parts.update(part for part in _practised_parts(take) if part <= total)
    return {"practised": len(parts), "total": total,
            "unit": "slides" if has_deck else "sections"}


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
        "practice_coverage": _coverage(sess, n_slides, bool(cover_ref)),
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
    from services.parallel import run_in_parallel

    arc_ids = list(by_arc.keys())

    def read_edits() -> Any:
        if every_project:
            return database.get_coach_best_presentation_edits_for_arcs(arc_ids)
        return database.get_coach_best_presentation_edits_for_arcs(
            arc_ids, strict=False)

    def read_project_states() -> list[dict]:
        # Deletion/archive state depends only on the arc ids too. Read it on
        # the same latency wave as the delivery and edits batches; applying it to tiny
        # placeholder rows preserves the existing best-effort policy while
        # keeping a second group of database calls off the critical path.
        return with_deletion_state(
            database,
            [{"arc_id": aid} for aid in arc_ids],
            every_project,
        )

    # Deliveries, edits and project state all depend on the same arc ids.
    deliveries, batched, project_states = run_in_parallel(
        lambda: database.list_arc_batch_deliveries(arc_ids) or {},
        read_edits,
        read_project_states,
    )
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
                aid, spoken, deliveries.get(aid), edits_for))
    state_by_arc = {
        str(row.get("arc_id")): row
        for row in (project_states or [])
        if isinstance(row, dict) and row.get("arc_id")
    }
    trainings = [
        training for training in trainings
        if str(training.get("arc_id")) in state_by_arc
    ]
    for training in trainings:
        state = state_by_arc[str(training.get("arc_id"))]
        training["deletion"] = state.get("deletion")
        training["archived"] = bool(state.get("archived"))
    trainings.sort(key=lambda t: t.get("created_at") or "", reverse=True)
    return trainings
