import html
import logging
import re
from typing import Any
import resend
from config import Config
import sentry_sdk

config = Config()
logger = logging.getLogger(__name__)

class EmailService:
    @staticmethod
    def _escape_html(s: str) -> str:
        return html.escape(s, quote=True) if s else ""

    def __init__(self):
        # Set Resend API key (required for resend.Emails.send())
        if config.RESEND_API_KEY:
            resend.api_key = config.RESEND_API_KEY
        self.api_key_set = bool(config.RESEND_API_KEY)
    
    def send_lesson_complete_to_admin(
        self,
        user_id: str,
        session_id: str,
        report_preview: str = "",
        student_email: str | None = None,
        score: float | None = None,
        student_name: str = "",
    ) -> dict:
        """
        Notify the coach (ADMIN_EMAIL) that a student completed a homework lesson.
        score is the canonical end score (0-1) stored on the session.
        Shown in email as "End score: X%".
        Returns dict with status "sent" | "pending" (emails off) | "failed".

        Threading (fix-pack BE-3b): stable subject "Homework — {pseudonym}"
        (NO session id — a per-session subject defeats mailbox threading) +
        per-student References/In-Reply-To root, so every homework ping for
        the same student stacks into ONE coach-inbox conversation. Guest
        sends (falsy user_id) go out unthreaded with an 'Anonymous' handle
        — never a crash.
        """
        if not config.SEND_EMAILS:
            logger.info(
                "Coach notification skipped: SEND_EMAILS is false. Set SEND_EMAILS=true to receive homework-complete emails at %s",
                config.ADMIN_EMAIL,
            )
            return {"status": "pending", "sent": False}
        if not self.api_key_set:
            return {"status": "failed", "sent": False, "error": "Resend API key not set"}
        from services.assignment_email import build_admin_homework_completed_email_html

        frontend_url = (config.FRONTEND_URL or "").rstrip("/")
        admin_student_url = f"{frontend_url}/admin/students/{user_id}" if frontend_url else "#"
        logo_url = (getattr(config, "APP_LOGO_URL", None) or "").strip() or (f"{frontend_url}/icon" if frontend_url else None)
        preview = (report_preview or "").strip()
        if preview and len(preview) > 280:
            preview = preview[:280].rstrip() + "..."
        score_str = ""
        if score is not None:
            pct = round(float(score) * 100)
            score_str = f"Final performance score: {pct}%."
        # ``or ""`` guards the guest case (user_id=None AND no email) —
        # the old ``(student_email or user_id).strip()`` crashed on None.
        who = (student_email or user_id or "").strip() or (user_id or "Guest")

        coach_message = f"Student completed homework.\n\nStudent: {who}"
        if score_str:
            coach_message += f"\n\n{score_str}"
        if preview:
            coach_message += f"\n\nReport preview: {preview}"
        coach_message += "\n\nOpen the student profile to review and send next homework."

        html = build_admin_homework_completed_email_html(
            student_email=who,
            score=score,
            profile_url=admin_student_url,
            transcript_excerpt=preview or report_preview or "",
            pace_wpm=None,
            filler_count=None,
            strength="Loudness (pending)",
            logo_url=logo_url,
            student_name=student_name,
        )

        # Stable per-student subject + synthetic thread root → one coach-
        # inbox conversation per student (BE-3b). The session id stays out
        # of the subject on purpose; the profile link in the body is the
        # per-event pointer.
        from services.coach_pseudonym import coach_pseudonym
        from services.email_threading import student_thread_headers

        subject = f"Homework — {coach_pseudonym(user_id)}"
        headers = student_thread_headers(user_id)

        text = f"A student has completed a homework lesson.\n\nStudent: {who}\n"
        if score_str:
            text += f"{score_str}\n\n"
        if preview:
            text += f"Report preview: {preview}\n\n"
        text += f"View profile and send next homework: {admin_student_url}\n"
        try:
            send_email_resend(
                to=config.ADMIN_EMAIL,
                subject=subject,
                html=html,
                text=text,
                headers=headers or None,
            )
            return {"status": "sent", "sent": True}
        except Exception as e:
            # send_email_resend already captured to Sentry; this method's
            # contract is never-raise (the notification is a nudge).
            return {"status": "failed", "sent": False, "error": str(e)}

# Singleton instance
email_service = EmailService()


def send_email_resend(
    *,
    to: str,
    subject: str,
    html: str,
    text: str | None = None,
    from_addr: str | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    """Thin module-level wrapper around resend.Emails.send().

    Two routes in routes/v2_routes.py (publish-session-results around
    L9333, the cleaner /admin/sessions/<id>/publish alias around L9873)
    already import this name and call it with (to, subject, html). The
    function was never defined, so every publish click crashed with:

        ImportError: cannot import name 'send_email_resend'
                     from 'services.email_service'

    What it does:
      - validates the Resend API key is present and SEND_EMAILS is true
      - picks the From: address (passed-in override, else
        config.RESEND_FROM_EMAIL)
      - synthesises a plain-text fallback from the HTML (strip tags) if
        the caller didn't supply one
      - calls resend.Emails.send() and returns the response dict, or
        raises on failure (the route handlers catch + log + 502 on
        their side, so we don't swallow)

    Kept module-level (rather than an EmailService method) because the
    callers import it as a free function and it's a tiny generic
    sender — no need to instantiate.
    """
    if not config.SEND_EMAILS:
        logger.info("send_email_resend: SEND_EMAILS is false — skipping (to=%s)", to)
        return {"status": "pending", "sent": False}

    if not config.RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY not configured")

    # resend.api_key is set in EmailService.__init__ (singleton above
    # initialises it). If for any reason the singleton hasn't been
    # constructed yet, set it here defensively so a direct module-level
    # call works without an explicit EmailService() instantiation.
    if not getattr(resend, "api_key", None):
        resend.api_key = config.RESEND_API_KEY

    fallback_text = text or re.sub(r"<[^>]+>", "", html or "").strip()
    params: dict[str, Any] = {
        "from": (from_addr or config.RESEND_FROM_EMAIL),
        "to": [to],
        "subject": subject,
        "text": fallback_text,
        "html": html,
    }
    # RFC 8058 List-Unsubscribe + arbitrary delivery headers (e.g.
    # X-Entity-Ref-ID for grouping). Resend forwards the dict
    # verbatim to the SMTP layer. Empty / falsy values are dropped
    # so callers can pass headers={} without polluting the request.
    if headers:
        clean_headers = {
            str(k): str(v) for k, v in headers.items()
            if k and v
        }
        if clean_headers:
            params["headers"] = clean_headers
    try:
        response = resend.Emails.send(params)
        logger.info("send_email_resend: accepted to=%s subject=%r", to, subject)
        return {"status": "sent", "sent": True, "resend_response": response}
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.warning("send_email_resend failed to=%s err=%r", to, e)
        raise
