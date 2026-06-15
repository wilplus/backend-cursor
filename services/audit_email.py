"""Audit-ready email (willab Prompt C §4).

When a coach uploads a PDF audit, the user is emailed a link to their audits
page (the PDF is ALSO reachable via the Lounge bubble). Best-effort: the
upload succeeds even if this fails. Reuses the Post-Session-Results sender
(Resend) + the "WillpowerLab" branded-from + the PUBLIC_FRONTEND_URL deep-link.

FENCE: no explanation of what an audit is — a short subject + one CTA button
to the audits page (founder rule).
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def send_audit_ready_email(
    user_id: str, *, user_email: Optional[str] = None,
) -> bool:
    """Email the user that a new audit is available. Returns True iff accepted
    by the provider. Never raises — every failure logs + returns False."""
    if not user_id:
        return False
    try:
        import config
        from services.db import db
        from services.email_service import send_email_resend
        from services.post_session_results_email import _willab_branded_from
    except Exception as e:  # pragma: no cover - import guard
        logger.warning("audit_email: import failed: %s", e)
        return False

    try:
        email = (user_email or "").strip() or db.get_user_email_from_auth(user_id)
        if not email:
            logger.warning("audit_email: no email for user=%s", user_id)
            return False

        audits_url = f"{config.PUBLIC_FRONTEND_URL.rstrip('/')}/audits"
        subject = "Your audit is ready"
        # Short + no explanation — just the link (founder rule).
        html = (
            '<div style="font-family:sans-serif;font-size:16px;color:#222">'
            "<p>Your audit is ready.</p>"
            f'<p><a href="{audits_url}" '
            'style="display:inline-block;padding:10px 18px;background:#f97316;'
            'color:#fff;border-radius:8px;text-decoration:none;font-weight:600">'
            "Open your audit</a></p>"
            "</div>"
        )
        text = f"Your audit is ready. Open it: {audits_url}"

        res = send_email_resend(
            to=email, subject=subject, html=html, text=text,
            from_addr=_willab_branded_from(config.RESEND_FROM_EMAIL),
        )
        sent = bool(res and res.get("sent"))
        logger.info("audit_email: user=%s sent=%s", user_id, sent)
        return sent
    except Exception as e:
        logger.warning("audit_email: send failed user=%s: %s", user_id, e)
        return False
