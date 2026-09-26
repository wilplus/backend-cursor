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


def _deliver(database, row: dict) -> None:
    revision = row.get("coach_review_revisions") or {}
    payload = row.get("payload") or {}
    session_id = str(row.get("session_id") or "")
    owner_id = str(revision.get("owner_user_id") or payload.get("owner_user_id") or "")
    project_id = str(revision.get("project_id") or payload.get("project_id") or "")

    database.record_snippet_publish_annotations(
        session_id=session_id,
        admin_user_id=str(revision.get("actor_user_id") or ""),
    )

    from services.arc_notifications import bump_ideal_bubble
    from services.voice_album import reconcile_voice_album_clip

    # NO NEW BUBBLE PER PUBLISH (founder 2026-09-25, Q34 B, then "the
    # feedback bubble can be deleted"). Correction cards,
    # the coach's shared-video card, "Voice Album ready" and the best-
    # presentation milestone used to fire here too; every one of them is
    # reached from the one sheet the bubble and the email open. The coach's
    # own Take video is gone from the product: the exercise video is the only
    # video (founder, same day).
    #
    # The album clips are still reconciled -- that is data, not a message.
    for clip_id in payload.get("voice_album_clip_ids") or []:
        reconcile_voice_album_clip(
            project_id,
            clip_id,
            take_session_id=session_id,
            database=database,
        )
    # THE MOMENT THE WORK LANDS (founder 2026-09-25, Q39 B / Q41 A): no new
    # bubble -- the project's own Ideal Text bubble moves to the bottom of the
    # chat, where it wears the orange dot with the unopened feedback count.
    bump_ideal_bubble(database, owner_id, project_id)
    _mail_the_speaker(database, owner_id, project_id, session_id, payload)


def _mail_the_speaker(database, owner_id, project_id, session_id, payload):
    """The publish-results email — the ONLY thing that reaches a speaker who
    is not looking at the app.

    It was called from the publish endpoint until b73697f moved delivery
    effects here and left it behind; it has sent nothing since 2026-08-24.
    Founder 2026-09-24: "You should turn on the email so that they know that
    they have it."

    BEST-EFFORT ON PURPOSE. This module is a retrying outbox: a raise leaves
    the event to run again, and the Lounge bubbles above survive that because
    each is idempotent on its client key. An email is not — a retry would put
    a second copy in the inbox. So a failed send is logged and swallowed, and
    the publish stands. Silence in an inbox beats a duplicate, and beats a
    delivery row that never finishes.
    """
    if not owner_id:
        return
    try:
        from services.arc_notifications import _arc_topic
        from services.post_session_results_email import (
            send_publish_results_email,
        )

        email = database.get_user_email_from_auth(str(owner_id))
        if not email:
            logger.info(
                "publish email: no address on file user=%s", owner_id)
            return
        items = payload.get("feedback_items")
        result = send_publish_results_email(
            user_id=str(owner_id),
            user_email=email,
            user_first_name=None,
            # The project's own name. Non-empty matters: the render endpoint
            # refuses a blank topTheme, and the sender would quietly fall back
            # to its degraded inline template rather than the designed one.
            top_theme=_arc_topic(database, project_id) or "your latest take",
            snippet_count=len(items) if isinstance(items, list) else 0,
            session_id=str(session_id or ""),
            arc_id=str(project_id) if project_id else None,
        )
        logger.info(
            "publish email: %s user=%s arc=%s",
            (result or {}).get("status"), owner_id, project_id,
        )
    except Exception as e:
        logger.exception(
            "publish email failed user=%s arc=%s err=%s",
            owner_id, project_id, e,
        )


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
