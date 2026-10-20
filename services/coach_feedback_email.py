"""The email "Your coach's feedback is in." (founder 2026-10-14: bring it back).

The publish-results email went with the arc-level publish on 2026-10-01
(#838). Since then a coach's shared answer reached the speaker as a Lounge
dot and, for the Take's word, a WhatsApp, but no email. It is back, sent on
the same events as the WhatsApp: each message a coach shares, the Take's
word or the answer on one moment.

THE DESIGN IS THE ONE THE FOUNDER SIGNED OFF ON 2026-09-25 (the frontend's
PostSessionResultsEmail), confirmed again 2026-10-14, with the text logo of
2026-09-30 (`email_wordmark`). It is rendered here as plain inline HTML: no
round trip to the frontend, nothing that can fail between the coach's share
and the speaker's inbox. A count of moments, never a score (AC-9).

The send is best-effort and off the coach's request: a failed or skipped
email never fails the coach's save (LIVE LOOP). Off unless SEND_EMAILS is
true and Resend is set; skipped for a speaker who unsubscribed (the
`email_pref_publish_results` flag the footer link flips).
"""
from __future__ import annotations

import html
import logging
import threading
from typing import Any, Optional
from urllib.parse import quote

from config import Config

_log = logging.getLogger(__name__)

#: The subject is the same on every send so one speaker's emails thread.
SUBJECT = "Your feedback from WillpowerLab"
HEADLINE = "Your coach's feedback is in."
INVITE = ("Open it to hear each moment, say how it sounded to you, and see "
          "your coach's notes and exercises.")
BUTTON = "Open the feedback"
FROM_NAME = "WillpowerLab"


def moments_line(moments: int) -> str:
    """What happened, in words: a count of moments, never a score."""
    n = max(0, int(moments or 0))
    if n == 0:
        return "Your coach listened to your latest take and left feedback."
    return ("Your coach listened to your latest take and left feedback on "
            f"{n} {'moment' if n == 1 else 'moments'}.")


def render(*, project: Optional[str], moments: int, open_url: str,
           unsubscribe_url: Optional[str]) -> dict[str, str]:
    """``{html, text}`` for one email. Pure. The Take's word (no moment)
    leaves out ``INVITE``: its link opens a walk with no moment to hear or
    judge (founder 2026-10-19, N80). Nothing replaces it."""
    from services.email_wordmark import wordmark_html
    esc = html.escape
    invite = INVITE if int(moments or 0) > 0 else ""
    invite_html = (
        '<p style="margin:12px 0 0 0;font-size:16px;line-height:26px;color:#1F1A14;">'
        f"{esc(invite)}</p>" if invite else "")
    page = "https://www.willpowerlab.com"
    eyebrow = (
        '<p style="margin:0;font-size:12px;letter-spacing:0.08em;'
        'text-transform:uppercase;color:#F97316;font-weight:600;">'
        f"{esc(project)}</p>" if project else "")
    unsubscribe = (
        f'<a href="{esc(unsubscribe_url, quote=True)}" style="color:#6B6256;'
        'text-decoration:underline;">Unsubscribe</a>&nbsp;&nbsp;·&nbsp;&nbsp;'
        if unsubscribe_url else "")
    body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="color-scheme" content="light only"></head>
<body style="margin:0;padding:32px 16px;background-color:#FAF7F2;color:#1F1A14;font-family:ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
  <div style="display:none;max-height:0;overflow:hidden;">{esc(moments_line(moments))}</div>
  <div style="max-width:580px;margin:0 auto;">
    {wordmark_html()}
    <div style="background-color:#FCFAF6;border:1px solid #EFE9DE;border-radius:16px;padding:40px;">
      {eyebrow}
      <h1 style="margin:8px 0 0 0;font-weight:600;font-size:28px;line-height:34px;color:#1F1A14;">{esc(HEADLINE)}</h1>
      <p style="margin:20px 0 0 0;font-size:16px;line-height:26px;color:#1F1A14;">{esc(moments_line(moments))}</p>
      {invite_html}
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:100%;margin-top:32px;"><tr><td align="center">
        <a href="{esc(open_url, quote=True)}" style="display:inline-block;background-color:#F97316;color:#FFFFFF;text-decoration:none;font-weight:600;font-size:15px;line-height:20px;padding:14px 28px;border-radius:9999px;">{esc(BUTTON)}</a>
      </td></tr></table>
    </div>
    <p style="margin:0;padding:24px 8px 0 8px;text-align:center;font-size:12px;line-height:18px;color:#6B6256;">
      {unsubscribe}<a href="{page}/privacy" style="color:#6B6256;text-decoration:underline;">Privacy</a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="{page}/terms" style="color:#6B6256;text-decoration:underline;">Terms</a>
    </p>
  </div>
</body>
</html>"""
    lines = ["WillpowerLab", ""]
    if project:
        lines += [project.upper(), ""]
    lines += [HEADLINE, "", moments_line(moments), *([invite] if invite else []), "",
              f"{BUTTON}: {open_url}"]
    if unsubscribe_url:
        lines += ["", f"Unsubscribe: {unsubscribe_url}"]
    return {"html": body, "text": "\n".join(lines)}


def _base_url() -> str:
    return (Config.FRONTEND_URL or "https://www.willpowerlab.com").rstrip("/")


def _unsubscribe_url(user_id: str) -> Optional[str]:
    """The footer link, or None when tokens are not configured (the email
    then goes without the link rather than with a broken one)."""
    try:
        from services.unsubscribe_tokens import generate_unsubscribe_token
        token = generate_unsubscribe_token(user_id)
    except Exception as e:  # noqa: BLE001 -- no link beats a broken one
        _log.warning("coach feedback email: no unsubscribe link user=%s: %s", user_id, e)
        return None
    return f"{_base_url()}/unsubscribe?token={quote(token)}"


def _from_address() -> Optional[str]:
    """RESEND_FROM_EMAIL's mailbox under the WillpowerLab name."""
    raw = (Config.RESEND_FROM_EMAIL or "").strip()
    if "<" in raw and raw.endswith(">"):
        raw = raw[raw.rfind("<") + 1:-1].strip()
    return f"{FROM_NAME} <{raw}>" if "@" in raw else None


def send_coach_feedback_email(database: Any, *, take_session_id: str,
                              moments: int) -> str:
    """Send the email for one shared message on this Take. Returns what
    happened ("sent", or why it was skipped). Never raises."""
    try:
        if not Config.SEND_EMAILS:
            return "send_emails_off"
        session = database.v2_get_session_by_id(str(take_session_id)) or {}
        user_id = str(session.get("user_id") or "")
        if not user_id:
            return "no_speaker"
        try:
            if not database.get_email_pref_publish_results(user_id):
                return "unsubscribed"
        except Exception as e:  # noqa: BLE001 -- one extra email beats a silent drop
            _log.warning("coach feedback email: pref read failed user=%s: %s", user_id, e)
        to = database.get_user_email_from_auth(user_id)
        if not to:
            return "no_email"
        from services.arc_notifications import _arc_topic
        arc_id = str(session.get("arc_id") or "")
        base = _base_url()
        open_url = (f"{base}/chat?idealArc={quote(arc_id, safe='')}&feedback=1"
                    if arc_id else f"{base}/chat")
        unsubscribe_url = _unsubscribe_url(user_id)
        mail = render(project=_arc_topic(database, arc_id) if arc_id else None,
                      moments=moments, open_url=open_url,
                      unsubscribe_url=unsubscribe_url)
        from services.email_service import send_email_resend
        from services.email_threading import user_thread_headers
        headers = dict(user_thread_headers(user_id))
        if unsubscribe_url:
            headers["List-Unsubscribe"] = f"<{unsubscribe_url}>"
            headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        send_email_resend(to=to, subject=SUBJECT, html=mail["html"],
                          text=mail["text"], from_addr=_from_address(),
                          headers=headers)
        _log.info("coach feedback email: sent take=%s moments=%s",
                  take_session_id, moments)
        return "sent"
    except Exception as e:  # noqa: BLE001 -- the coach's save stands either way
        _log.warning("coach feedback email failed take=%s: %s",
                     take_session_id, e, exc_info=True)
        return "failed"


def send_coach_feedback_email_in_background(database: Any, *, take_session_id: Any,
                                            moments: int) -> None:
    """The same, off the coach's request so Resend never slows the save."""
    if not take_session_id:
        return
    if not Config.SEND_EMAILS:
        _log.info("coach feedback email: SEND_EMAILS is off, nothing sent")
        return
    threading.Thread(
        target=send_coach_feedback_email, args=(database,),
        kwargs={"take_session_id": str(take_session_id), "moments": int(moments)},
        name="coach-feedback-email", daemon=True).start()
