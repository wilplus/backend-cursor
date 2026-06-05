"""Coach-notification helpers.

The old auto-publish/finalize spine (``finalize_session_pending_admin_
review`` + ``auto_publish_trial_session`` + their KPI/predictions/
charisma/learner-profile drafting) was removed in the old-subsystem
excision — those drove the retired charisma/diagnosis funnel and had
no callers left. What remains here is the willab-used surface:

  - ``_send_admin_notification`` — emails the coach that a session is
    in the review queue (called by services.lab_send on willab Send).
  - ``_fetch_user_email`` — its email lookup helper.
"""
from __future__ import annotations

import logging
from typing import Any

from services.db import db


logger = logging.getLogger(__name__)


def _send_admin_notification(
    *,
    session_id: str,
    user_id: str,
    snippet_count: int,
) -> str:
    """Email the coach/admin that a session was auto-published.

    Reuses ``email_service.send_lesson_complete_to_admin`` — same
    template as the homework-complete notification — so admins
    see a consistent "student finished a thing, click to review"
    signal regardless of which session type produced it.

    Returns the result.status from the email service ('sent',
    'pending', 'failed') or 'skipped' when we couldn't resolve
    the student's email (we don't block on that — the admin
    notification is informational, not transactional).
    """
    try:
        from services.email_service import email_service

        student_email = _fetch_user_email(user_id)
        student_name = ""
        try:
            details = db.v2_get_student_details(user_id) or {}
            student_name = (details.get("name") or "").strip()
        except Exception:
            pass

        report_preview = ""
        try:
            sess = db.v2_get_session_by_id(session_id) or {}
            report_preview = (sess.get("ai_task_alignment_comment") or "").strip()
            score_raw = sess.get("kpi_score")
        except Exception:
            score_raw = None
        # KPI on the row is 0..100; the admin helper expects 0..1.
        score = None
        if isinstance(score_raw, (int, float)):
            score = float(score_raw) / 100.0

        send_result = email_service.send_lesson_complete_to_admin(
            user_id=str(user_id),
            session_id=session_id,
            report_preview=report_preview,
            student_email=student_email,
            score=score,
            student_name=student_name,
        )
        status = (send_result or {}).get("status") or "unknown"
        logger.info(
            "auto_publish_trial: admin notification sid=%s status=%s snippets=%d",
            session_id, status, snippet_count,
        )
        return status
    except Exception as e:
        logger.warning(
            "auto_publish_trial: admin notification failed sid=%s err=%s",
            session_id, e,
        )
        return "failed"


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
