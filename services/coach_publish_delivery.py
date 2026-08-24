"""Retryable effects derived from an already-visible coach-review revision."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
DELIVERY_JOB_PATH = "services.coach_publish_delivery.deliver_review"


def enqueue_review_delivery(revision_id: str, *, delay_seconds: int = 0) -> bool:
    if not revision_id:
        return False
    from services.job_queue import enqueue

    return enqueue(
        DELIVERY_JOB_PATH,
        str(revision_id),
        delay_seconds=delay_seconds,
        rq_job_id=f"coach-review-delivery:{revision_id}",
    )


def _freeze_shared_video(database, session_id: str, overall_message: str | None) -> None:
    text = str(overall_message or "").strip()
    if not text:
        return
    for asset in database.get_current_coach_video_assets_for_session(session_id) or []:
        if asset.get("content_type") != "take_summary":
            continue
        if not asset.get("comment_text_at_publish"):
            database.set_coach_video_comment_at_publish(asset.get("id"), text)


def _deliver(database, row: dict) -> None:
    revision = row.get("coach_review_revisions") or {}
    payload = row.get("payload") or {}
    revision_id = str(row.get("revision_id") or "")
    session_id = str(row.get("session_id") or "")
    owner_id = str(revision.get("owner_user_id") or payload.get("owner_user_id") or "")
    project_id = str(revision.get("project_id") or payload.get("project_id") or "")

    database.record_snippet_publish_annotations(
        session_id=session_id,
        admin_user_id=str(revision.get("actor_user_id") or ""),
    )

    from services.arc_notifications import (
        fire_coach_video_shared,
        fire_material_coach_correction,
        fire_voice_album_ready,
        maybe_fire_best_presentation_ready,
    )

    for item in payload.get("material_corrections") or []:
        fire_material_coach_correction(database, owner_id, revision_id, item)

    if payload.get("share_video") is True:
        _freeze_shared_video(database, session_id, revision.get("overall_message"))
        fire_coach_video_shared(
            database, owner_id, revision_id, project_id, session_id,
        )

    from services.voice_album import reconcile_voice_album_clip

    for clip_id in payload.get("voice_album_clip_ids") or []:
        reconcile_voice_album_clip(
            project_id,
            clip_id,
            take_session_id=session_id,
            database=database,
        )
    if payload.get("voice_album_clip_ids"):
        fire_voice_album_ready(database, owner_id, project_id)
    maybe_fire_best_presentation_ready(database, project_id)


def deliver_review(revision_id: str, *, database=None) -> bool:
    """Run one outbox event. Failures leave it retryable, never hidden."""
    if not revision_id:
        return False
    if database is None:
        from services.db import db as database
    row = database.get_coach_review_delivery(str(revision_id)) or {}
    if not row or row.get("status") == "done":
        return True
    if not database.start_coach_review_delivery(str(row.get("id") or "")):
        return row.get("status") in ("running", "done")
    try:
        _deliver(database, row)
        database.finish_coach_review_delivery(str(row["id"]))
        return True
    except Exception as error:
        attempts = int(row.get("attempts") or 0) + 1
        delay = min(3600, 30 * (2 ** min(attempts, 7)))
        database.finish_coach_review_delivery(
            str(row["id"]), error=str(error), retry_after_seconds=delay,
        )
        logger.exception(
            "coach review delivery failed revision=%s", revision_id,
        )
        raise


def sweep_pending_deliveries(*, database=None, limit: int = 100) -> int:
    if database is None:
        from services.db import db as database
    queued = 0
    for row in database.list_pending_coach_review_deliveries(limit=limit) or []:
        if enqueue_review_delivery(str(row.get("revision_id") or "")):
            queued += 1
    return queued
