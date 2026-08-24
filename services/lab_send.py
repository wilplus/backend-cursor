"""willab beta — Lab send-to-coach (design §13, contract §3.4–3.7).

"Send" puts a Lab recording into the coach review queue. The willab Lab
already processed the recording at upload (snippets + features +
stickiness exist), so send is light: flip the session into the coach
queue (status pending_admin_review — the SAME queue the admin/coach
review surface already reads, §3.8 reuse) + a best-effort admin
notification. No re-processing.

Idempotent (contract §3.4/§3.6): a session already in/through the queue
is a no-op — covers double-tap and duplicate client delivery. "Confirm only on send success"
means the status flip is the success signal; the email is a nudge.

This is the internal primitive used by the analysis worker and the canonical
Project/Take send endpoint. Ownership is verified before this function runs.
"""
from __future__ import annotations

import logging


logger = logging.getLogger(__name__)


# Statuses that mean the session is already in or past the coach queue —
# sending again is a no-op.
_ALREADY_SENT_STATUSES = {"pending_admin_review", "completed"}


def send_lab_recording_to_coach(session_id: str, user_id: str) -> dict:
    """Idempotently send a (claimed) Lab session to the coach queue.

    Returns::
        {"ok": bool, "already_sent": bool, "status": str|None}

    ``ok`` is the send-success signal (the status flip landed). The
    admin email is best-effort and never gates ``ok``. Never raises —
    the caller must not unwind durable ownership on a send hiccup; a retry
    re-sends the exact Project Take.
    """
    if not session_id or not user_id:
        return {"ok": False, "already_sent": False, "status": None}

    from services.db import db

    try:
        session = db.v2_get_session_by_id(session_id) or {}
    except Exception as e:
        logger.warning("lab_send: session load failed sid=%s err=%s", session_id, e)
        return {"ok": False, "already_sent": False, "status": None}
    if not session:
        return {"ok": False, "already_sent": False, "status": None}

    current = session.get("status")
    if current in _ALREADY_SENT_STATUSES or session.get("results_published_at"):
        # Already in/through the coach queue — idempotent no-op.
        return {"ok": True, "already_sent": True, "status": current}

    # Flip into the coach review queue (the success signal).
    try:
        flipped = db.v2_mark_session_pending_review(session_id)
        ok = bool(flipped)
    except Exception as e:
        logger.error("lab_send: status flip failed sid=%s err=%s", session_id, e)
        return {"ok": False, "already_sent": False, "status": current}

    if not ok:
        return {"ok": False, "already_sent": False, "status": current}

    # Best-effort admin notification — a nudge, not part of send-success.
    # Founder 2026-07-16 (BE-3a): a mid-take RE-READ is part of its parent
    # take — it still enters the review flow (the coach packet folds it),
    # but it NEVER fires its own "homework completed" email. One email per
    # spoken take ⇒ max 3 per arc.
    _is_read = (session.get("recording_kind") == "read"
                or bool(session.get("paired_session_id")))
    if _is_read:
        logger.info(
            "lab_send: re-read sid=%s — admin email skipped (folds into "
            "take %s)", session_id, session.get("paired_session_id"),
        )
    else:
        try:
            from services.session_publish import _send_admin_notification
            snippets = db.get_snippets_by_session(session_id) or []
            _send_admin_notification(
                session_id=session_id,
                user_id=user_id,
                snippet_count=len(snippets),
            )
        except Exception as e:
            logger.warning(
                "lab_send: admin notify failed sid=%s err=%s (non-fatal)",
                session_id, e,
            )

    logger.info("lab_send: sent to coach sid=%s user=%s", session_id, user_id)
    return {"ok": True, "already_sent": False, "status": "pending_admin_review"}
