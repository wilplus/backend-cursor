"""PostSessionResultsEmail render + send pipeline.

Phase 14. Replaces the inline HTML string the legacy publish-results
endpoint used to ship with a server-to-server render call into the
frontend's React Email pipeline:

  backend  --POST props-->  /api/internal/emails/post-session-results
                            (Vercel, signed with EMAIL_RENDER_SECRET)
  frontend                  renders PostSessionResultsEmail.tsx →
                            { html, text }
  backend  ←----------------┘
  backend  --send-->        Resend, with RFC 8058 List-Unsubscribe
                            headers + the unsubscribe URL in the
                            template footer

Why proxy through the frontend at all
-------------------------------------
The template is a React component (.tsx). Doing the render here
would mean either (a) running Node sidecar from Python, or (b)
porting the template to a Python template engine. Neither is
worth the maintenance cost when a single fetch into the existing
Next.js process does it cleanly. The render endpoint is internal-
only (gated by EMAIL_RENDER_SECRET) so external clients can't
abuse it to render arbitrary emails.

Unsubscribe + skip logic
------------------------
``send_publish_results_email`` checks ``user_settings.email_pref_
publish_results`` BEFORE rendering. When FALSE, returns a skip
result and never calls the frontend or Resend — that's the
functional unsubscribe (the working link is a courtesy; the skip
is the enforcement).

Failure modes return structured dicts; the caller (the publish
endpoint) maps to HTTP responses. We never raise to the user.
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import quote as _url_quote

import httpx

from config import Config
from services.db import db
from services.email_service import send_email_resend


logger = logging.getLogger(__name__)


# Wall-clock budget for the round-trip into the frontend renderer.
# 10s is generous; React Email render typically returns in <1s.
_RENDER_TIMEOUT_SECONDS = 10.0


def build_unsubscribe_url(user_id: str) -> Optional[str]:
    """Mint an unsubscribe token + URL for the email footer.

    Returns None when the secret is unset (the email path will then
    omit the unsubscribe link rather than send a broken one). The
    URL is built off PUBLIC_FRONTEND_URL so the link is whatever the
    user-facing frontend domain is, not an internal hostname.
    """
    cfg = Config()
    try:
        from services.unsubscribe_tokens import (
            generate_unsubscribe_token,
            UnsubscribeTokenNotConfigured,
        )
        token = generate_unsubscribe_token(user_id)
    except UnsubscribeTokenNotConfigured:
        logger.warning(
            "build_unsubscribe_url: UNSUBSCRIBE_TOKEN_SECRET unset — "
            "omitting unsubscribe link"
        )
        return None
    except Exception as e:
        logger.warning(
            "build_unsubscribe_url: token mint failed user=%s err=%s",
            user_id, e,
        )
        return None

    base = cfg.PUBLIC_FRONTEND_URL.rstrip("/")
    return f"{base}/unsubscribe?token={_url_quote(token)}"


def render_post_session_results_email(props: dict) -> dict:
    """POST props to the frontend renderer and return ``{html, text}``.

    Raises ``RuntimeError`` when the secret / URL aren't configured
    so the caller surfaces a clear failure rather than silently
    sending a blank email. Network / status errors bubble up as
    httpx exceptions; the publish endpoint catches them and falls
    back to skipping the send rather than crashing the publish.
    """
    cfg = Config()
    if not cfg.EMAIL_RENDER_SECRET:
        raise RuntimeError("EMAIL_RENDER_SECRET not configured")
    base = cfg.FRONTEND_BASE_URL.rstrip("/")
    if not base:
        raise RuntimeError("FRONTEND_BASE_URL not configured")

    url = f"{base}/api/internal/emails/post-session-results"
    resp = httpx.post(
        url,
        json=props,
        headers={"x-internal-secret": cfg.EMAIL_RENDER_SECRET},
        timeout=_RENDER_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data = resp.json() or {}
    html_body = (data.get("html") or "").strip()
    text_body = (data.get("text") or "").strip()
    if not html_body:
        raise RuntimeError("renderer returned empty html")
    return {"html": html_body, "text": text_body}


def send_publish_results_email(
    *,
    user_id: str,
    user_email: str,
    user_first_name: Optional[str],
    snippet_count: int,
    top_theme: Optional[str],
    session_id: str,
) -> dict[str, Any]:
    """Render + send one PostSessionResultsEmail to ``user_email``.

    Returns one of:
      {"status": "sent",          "resend": <resend response>}
      {"status": "skipped",       "reason": "unsubscribed"}
      {"status": "skipped",       "reason": "send_emails_disabled"}
      {"status": "render_failed", "error": str}
      {"status": "send_failed",   "error": str}

    The publish endpoint maps these to its outer HTTP response —
    "skipped" is a success state from the user's perspective (we
    completed the publish flow, we just respected their opt-out).
    """
    # Functional unsubscribe — the per-category flag is the source
    # of truth. The link in the email is the user-facing path to
    # this flip; the enforcement is here.
    try:
        if not db.get_email_pref_publish_results(user_id):
            logger.info(
                "publish-results email: skipping unsubscribed user=%s",
                user_id,
            )
            return {"status": "skipped", "reason": "unsubscribed"}
    except Exception as e:
        # On a DB hiccup we err on the side of sending — better one
        # extra email than a silent drop for a user who actually
        # wants the notification.
        logger.warning(
            "publish-results email: pref lookup failed user=%s err=%s "
            "— sending anyway", user_id, e,
        )

    cfg = Config()
    if not cfg.SEND_EMAILS:
        return {"status": "skipped", "reason": "send_emails_disabled"}

    unsubscribe_url = build_unsubscribe_url(user_id)
    journey_url = f"{cfg.PUBLIC_FRONTEND_URL.rstrip('/')}/results/{session_id}"

    props: dict[str, Any] = {
        "userFirstName": (user_first_name or "").strip() or None,
        "snippetCount": int(snippet_count or 0),
        "topTheme": (top_theme or "").strip() or None,
        "journeyUrl": journey_url,
        "unsubscribeUrl": unsubscribe_url,
        "subscribedEmail": user_email,
    }

    try:
        rendered = render_post_session_results_email(props)
    except Exception as e:
        logger.error(
            "publish-results email: render failed user=%s err=%s",
            user_id, e,
        )
        return {"status": "render_failed", "error": str(e)}

    subject = _build_subject(snippet_count)
    headers: dict[str, str] = {}
    if unsubscribe_url:
        # RFC 8058 — Gmail / Apple show a one-click unsubscribe
        # button when both headers are present.
        headers["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    try:
        result = send_email_resend(
            to=user_email,
            subject=subject,
            html=rendered["html"],
            text=rendered["text"] or None,
            headers=headers or None,
        )
        logger.info(
            "publish-results email: sent user=%s session=%s",
            user_id, session_id,
        )
        return {"status": "sent", "resend": result}
    except Exception as e:
        logger.error(
            "publish-results email: send failed user=%s err=%s",
            user_id, e,
        )
        return {"status": "send_failed", "error": str(e)}


def _build_subject(snippet_count: int) -> str:
    """Match the contract example: "N new voice moments are ready"."""
    n = max(0, int(snippet_count or 0))
    return (
        "Your voice moments are ready"
        if n == 0
        else f"{n} new voice moments are ready"
    )
