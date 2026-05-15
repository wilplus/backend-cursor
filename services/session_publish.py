"""Auto-publish flow for sessions that don't go through admin review.

Today the only caller is the coaching trial-recording flow — the
user re-records a 30s answer after the coaching chat and expects
feedback within minutes, not after an admin review. The admin
publish endpoint (``v2_internal_publish_session_results``) stays
as-is for the standard onboarding/path flow; this module is a
focused parallel that mirrors only the steps the trial flow needs.

What we mirror from the admin publish:
  1. Generate AI drafts for any extracted snippets that don't
     already have one — without these the admin_comment column
     would stay NULL and the user-facing /results page would
     filter out every card.
  2. Promote ai_draft_admin_comment → admin_comment so the
     snippets render.
  3. Flip ``status`` to "completed".
  4. Stamp ``results_published_at`` so the BFF queries surface
     the session.
  5. Compute + persist ``charisma_profile`` so the dashboard
     renders the radar/heatmap on first load.
  6. Send the standard PostSessionResultsEmail.

What we deliberately skip:
  - ``record_snippet_publish_annotations`` — no admin in the loop,
    so there's no (admin_final, ai_draft) pair to capture as an
    RLHF event. The auto-promoted draft IS the final; that's the
    signal we'd want to capture later anyway, but a dedicated
    event type (``auto_promoted``) is a separate piece of work.

Every step is best-effort: a failure logs + continues so the
user always reaches /results with something rather than getting
stuck on the coaching screen with no feedback.
"""
from __future__ import annotations

import logging
from typing import Any

from services.db import db


logger = logging.getLogger(__name__)


def auto_publish_trial_session(
    session_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Run the full auto-publish + notify pipeline for a trial session.

    Returns a structured dict so the caller can log / surface what
    happened::

        {
          "ok":              bool,
          "step_failed":     str | None,   # first step that failed, if any
          "promoted_drafts": int,
          "published":       bool,
          "email_status":    str | None,   # 'sent' | 'skipped' | 'render_failed' | 'send_failed' | 'no_email'
          "snippet_count":   int,
          "skipped_reason":  str | None,   # e.g. 'no_snippets', 'no_owner', 'no_email'
        }
    """
    result: dict[str, Any] = {
        "ok": False,
        "step_failed": None,
        "promoted_drafts": 0,
        "published": False,
        "email_status": None,
        "snippet_count": 0,
        "skipped_reason": None,
    }

    # ── Step 1: AI-draft generation for any missing drafts.
    # extract_recording_snippets runs upstream of us; depending on
    # how the recording-1 job is configured it may or may not have
    # already produced ai_draft_admin_comment. We call into the
    # generator for any snippet that has a transcript but no draft
    # so promotion below has something to copy.
    try:
        _ensure_drafts(session_id)
    except Exception as e:
        logger.warning(
            "auto_publish_trial: draft generation failed sid=%s err=%s",
            session_id, e,
        )

    # ── Step 2: Promote drafts → admin_comment.
    try:
        promoted = db.promote_ai_drafts_to_admin_comments(session_id)
        result["promoted_drafts"] = promoted
    except Exception as e:
        logger.warning(
            "auto_publish_trial: promote failed sid=%s err=%s",
            session_id, e,
        )

    # Count published-able snippets (admin_comment now populated).
    snippet_count = 0
    try:
        snippets = db.get_snippets_with_comments_by_session(session_id) or []
        snippet_count = len(snippets)
        result["snippet_count"] = snippet_count
    except Exception as e:
        logger.warning(
            "auto_publish_trial: snippet count failed sid=%s err=%s",
            session_id, e,
        )

    if snippet_count == 0:
        # No commented snippets means the /results page would render
        # an empty journey card. Don't email the user in that case —
        # they'd open the email and find nothing. The session row
        # still exists; admin can revisit it manually.
        result["step_failed"] = "no_snippets"
        result["skipped_reason"] = "no_snippets"
        logger.info(
            "auto_publish_trial: no commented snippets, skipping publish "
            "sid=%s", session_id,
        )
        return result

    # ── Step 3: Flip session status to completed.
    try:
        db.v2_update_session_status_unscoped(session_id, "completed")
    except Exception as e:
        logger.warning(
            "auto_publish_trial: status flip failed sid=%s err=%s",
            session_id, e,
        )

    # ── Step 4: Stamp results_published_at (the gate the BFF
    # queries filter on).
    try:
        published = db.v2_publish_session_results(session_id)
        result["published"] = bool(published)
    except Exception as e:
        logger.warning(
            "auto_publish_trial: results_published_at stamp failed sid=%s err=%s",
            session_id, e,
        )

    # ── Step 5: Compute + persist charisma profile.
    try:
        from services.charisma_profile import (
            compute_and_persist_charisma_profile,
        )
        compute_and_persist_charisma_profile(
            session_id=session_id, user_id=str(user_id),
        )
    except Exception as e:
        logger.warning(
            "auto_publish_trial: charisma profile compute failed "
            "sid=%s err=%s", session_id, e,
        )

    # ── Step 6: Look up email + name, then send the standard
    # PostSessionResultsEmail. We resolve email from Supabase auth
    # exactly the way the admin publish endpoint does so failure
    # modes (no email, unsubscribed) get the same treatment.
    email_status, skipped_reason = _send_results_email(
        session_id=session_id,
        user_id=user_id,
        snippet_count=snippet_count,
    )
    result["email_status"] = email_status
    if skipped_reason and not result["skipped_reason"]:
        result["skipped_reason"] = skipped_reason

    result["ok"] = True
    return result


# ── Internals ──────────────────────────────────────────────────────


def _ensure_drafts(session_id: str) -> None:
    """For every snippet in the session that has a transcript but no
    ai_draft_admin_comment, fire the existing draft generator.

    No-op for snippets that already have a draft. Bounded by the
    number of snippets in the session (typically 1-5 for a trial).
    """
    try:
        rows = (
            db.client.table("charisma_snippets")
            .select("id, transcript, ai_draft_admin_comment")
            .eq("session_id", session_id)
            .execute()
            .data
            or []
        )
    except Exception as e:
        logger.warning(
            "auto_publish_trial: snippet listing for drafts failed "
            "sid=%s err=%s", session_id, e,
        )
        return

    from services.snippet_drafts import generate_charisma_draft_for_snippet

    for row in rows:
        if (row.get("ai_draft_admin_comment") or "").strip():
            continue
        if not (row.get("transcript") or "").strip():
            continue
        try:
            generate_charisma_draft_for_snippet(row["id"])
        except Exception as e:
            # Per-snippet failure is non-fatal — we'll just skip that
            # snippet on the promotion step.
            logger.warning(
                "auto_publish_trial: draft gen failed sn=%s err=%s",
                row["id"], e,
            )


def _send_results_email(
    *,
    session_id: str,
    user_id: str,
    snippet_count: int,
) -> tuple[str, str | None]:
    """Resolve user + send the standard results email.

    Returns (status, skipped_reason). status is one of:
        'sent', 'skipped', 'render_failed', 'send_failed', 'no_email'.
    skipped_reason is the unsubscribe / error code from the email
    service when status != 'sent', or 'no_email' when the auth
    lookup didn't yield an address.
    """
    user_email = _fetch_user_email(user_id)
    if not user_email:
        return "no_email", "no_email"

    first_name: str | None = None
    try:
        details = db.v2_get_student_details(user_id) or {}
        full_name = (details.get("name") or "").strip()
        if full_name:
            first_name = full_name.split()[0]
    except Exception as e:
        logger.warning(
            "auto_publish_trial: name lookup failed uid=%s err=%s",
            user_id, e,
        )

    top_theme: str | None = None
    try:
        sess = db.v2_get_session_by_id(session_id) or {}
        top_theme = (sess.get("stickiness_top_topic") or "").strip() or None
    except Exception:
        pass

    try:
        from services.post_session_results_email import (
            send_publish_results_email,
        )
        send_result = send_publish_results_email(
            user_id=str(user_id),
            user_email=user_email,
            user_first_name=first_name,
            snippet_count=snippet_count,
            top_theme=top_theme,
            session_id=session_id,
        )
        status = send_result.get("status") or "unknown"
        reason = send_result.get("reason") or send_result.get("error")
        return status, (reason if status != "sent" else None)
    except Exception as e:
        logger.warning(
            "auto_publish_trial: email send failed sid=%s err=%s",
            session_id, e,
        )
        return "send_failed", str(e)


def _fetch_user_email(user_id: str) -> str | None:
    """Pull the user's email from Supabase auth. Returns None on any
    failure — caller decides whether that's fatal."""
    try:
        import httpx
        from config import Config
        headers = {
            "Authorization": f"Bearer {Config.SUPABASE_SERVICE_ROLE_KEY}",
            "apikey": Config.SUPABASE_SERVICE_ROLE_KEY,
        }
        url = (
            f"{Config.SUPABASE_URL.rstrip('/')}"
            f"/auth/v1/admin/users/{user_id}"
        )
        resp = httpx.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json() or {}
        email = (data.get("email") or "").strip()
        return email or None
    except Exception as e:
        logger.warning(
            "auto_publish_trial: auth fetch failed uid=%s err=%s",
            user_id, e,
        )
        return None
