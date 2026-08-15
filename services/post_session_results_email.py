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
from services.email_threading import user_thread_headers


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
    arc_id: Optional[str] = None,
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
    # DEEP-LINK STRAIGHT TO THE REVIEWED TEXT (founder 2026-08-15: "does the
    # link from the email lead to this particular ideal text that holds these
    # reviews? if not make it a deep link").
    #
    # It did not. The CTA landed on /chat and left the student to find the
    # right bubble in a thread — for the ONE email whose entire subject is
    # "your coach reviewed this specific talk". `?idealArc=` opens that arc's
    # notebook on mount, the same way `?arc=` already opens the best
    # presentation and `?insight=` the insights overlay.
    #
    # Falls back to plain /chat when the arc is unknown: a take with no arc is
    # a real (if odd) state, and a link to nothing is worse than a link to the
    # thread that holds the card.
    _base = cfg.PUBLIC_FRONTEND_URL.rstrip("/")
    _arc = (arc_id or "").strip()
    journey_url = (
        f"{_base}/chat?idealArc={_url_quote(_arc, safe='')}" if _arc
        else f"{_base}/chat"
    )

    props: dict[str, Any] = {
        "userFirstName": (user_first_name or "").strip() or None,
        "snippetCount": int(snippet_count or 0),
        "topTheme": (top_theme or "").strip() or None,
        "journeyUrl": journey_url,
        "unsubscribeUrl": unsubscribe_url,
        "subscribedEmail": user_email,
    }

    # Render: try the React Email renderer first, fall back to an
    # inline-HTML template if anything in the round-trip fails
    # (EMAIL_RENDER_SECRET unset, frontend down, timeout, 5xx, empty
    # body, …). The user receiving SOME email is critical; a degraded
    # template beats silence. The render-failure path logs at error
    # level so Sentry still surfaces the underlying misconfig.
    render_mode = "rendered"
    render_error: Optional[str] = None
    try:
        rendered = render_post_session_results_email(props)
    except Exception as e:
        render_error = str(e)
        logger.error(
            "publish-results email: render failed user=%s err=%s "
            "— falling back to inline template",
            user_id, e,
        )
        rendered = _render_inline_fallback(props)
        render_mode = "fallback"

    subject = _build_subject()
    # Per-user thread root (fix-pack BE-3c): together with the stable
    # subject this stacks every publish-results mail for one user into
    # ONE conversation in their mail client.
    headers: dict[str, str] = dict(user_thread_headers(user_id))
    if unsubscribe_url:
        # RFC 8058 — Gmail / Apple show a one-click unsubscribe
        # button when both headers are present.
        headers["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    # Force the display name on this transactional email to "Willab"
    # regardless of what RESEND_FROM_EMAIL is configured as globally
    # (could be a personal name from a dev account). The mailbox part
    # is preserved — we only rewrite the display name.
    from_addr = _willab_branded_from(cfg.RESEND_FROM_EMAIL)

    try:
        result = send_email_resend(
            to=user_email,
            subject=subject,
            html=rendered["html"],
            text=rendered["text"] or None,
            from_addr=from_addr,
            headers=headers or None,
        )
        logger.info(
            "publish-results email: sent user=%s session=%s mode=%s",
            user_id, session_id, render_mode,
        )
        out: dict[str, Any] = {
            "status": "sent",
            "resend": result,
            "render_mode": render_mode,
        }
        if render_error:
            out["render_error"] = render_error
        return out
    except Exception as e:
        logger.error(
            "publish-results email: send failed user=%s err=%s mode=%s",
            user_id, e, render_mode,
        )
        return {"status": "send_failed", "error": str(e)}


def _build_subject() -> str:
    """STABLE subject (fix-pack BE-3c): mailbox threading needs the same
    subject on every send, so the old count-varying form ("N new voice
    moments are ready") is gone — the count still lives in the body."""
    return "Your feedback from WillpowerLab"


# Display name baked into every Post-Session-Results envelope. The
# user's mailbox part is preserved (extracted from RESEND_FROM_EMAIL);
# only the friendly-name half is rewritten so inboxes show "Willab"
# instead of whatever dev account label the global env var holds.
_BRAND_DISPLAY_NAME = "WillpowerLab"


def _willab_branded_from(raw_from: str | None) -> str | None:
    """Return ``"Willab <email@domain>"`` from any of these inputs:

      - ``"Artur <hello@willonski.com>"``  → ``"Willab <hello@willonski.com>"``
      - ``"hello@willonski.com"``          → ``"Willab <hello@willonski.com>"``
      - ``None`` / ``""``                  → ``None`` (caller falls
                                              back to send_email_resend's
                                              own default)

    The transformation is mailbox-preserving — we never touch the
    local-part or domain. Only the display name gets normalised.
    Robust against extra whitespace and stray quotes.
    """
    if not raw_from:
        return None
    s = raw_from.strip()
    if not s:
        return None

    # Case 1: already in "Name <email>" format. Extract the bracketed
    # mailbox and re-attach Willab as the display name.
    if "<" in s and s.endswith(">"):
        bracket_open = s.rfind("<")
        mailbox = s[bracket_open + 1 : -1].strip()
        if mailbox and "@" in mailbox:
            return f"{_BRAND_DISPLAY_NAME} <{mailbox}>"
        # Malformed — fall through to bare-email handling below.

    # Case 2: bare "email@domain" with no angle brackets.
    if "@" in s and "<" not in s and ">" not in s:
        return f"{_BRAND_DISPLAY_NAME} <{s}>"

    # Anything else (weird formatting): return as-is so we don't
    # silently drop the From header. send_email_resend will use it
    # verbatim; downstream Resend either accepts or 400s loudly.
    return raw_from


def _render_inline_fallback(props: dict) -> dict:
    """Last-resort renderer when the React Email round-trip fails.

    Builds a small, self-contained inline-HTML email from the same
    props the React template consumes. No env vars, no network — so
    it works even when EMAIL_RENDER_SECRET is unset, the frontend
    renderer is down, or the contract has drifted. Returns the same
    ``{html, text}`` shape as ``render_post_session_results_email``
    so the call site is identical.

    The visual is intentionally simple (no gradients, no images) —
    this template only ships when something upstream is already
    broken, so resilience > polish. The plain-text fallback is the
    same content with markup stripped.
    """
    import html as _html_lib

    first_name = (props.get("userFirstName") or "").strip()
    snippet_count = int(props.get("snippetCount") or 0)
    top_theme = (props.get("topTheme") or "").strip()
    journey_url = (props.get("journeyUrl") or "").strip()
    unsubscribe_url = (props.get("unsubscribeUrl") or "").strip()

    greeting_name = _html_lib.escape(first_name) if first_name else "there"
    safe_journey_url = _html_lib.escape(journey_url, quote=True)

    if snippet_count > 0:
        headline = (
            f"{snippet_count} new voice moment"
            f"{'s' if snippet_count != 1 else ''} are ready"
        )
    else:
        headline = "Your voice moments are ready"

    theme_line = ""
    if top_theme:
        theme_line = (
            f"<p style=\"font-size:15px;line-height:1.6;margin:8px 0 16px;"
            f"color:#444;\">Top theme this session: "
            f"<strong>{_html_lib.escape(top_theme)}</strong>.</p>"
        )

    cta_block = ""
    if journey_url:
        cta_block = (
            f"<div style=\"text-align:center;margin:28px 0;\">"
            f"<a href=\"{safe_journey_url}\" "
            f"style=\"display:inline-block;background:#000;color:#fff;"
            f"padding:14px 28px;border-radius:6px;text-decoration:none;"
            f"font-weight:600;font-size:16px;\">View your results</a></div>"
        )

    footer_unsub = ""
    if unsubscribe_url:
        safe_unsub = _html_lib.escape(unsubscribe_url, quote=True)
        footer_unsub = (
            f"<p style=\"font-size:12px;color:#888;margin:16px 0 0;\">"
            f"Don't want these updates? "
            f"<a href=\"{safe_unsub}\" style=\"color:#888;\">Unsubscribe</a>."
            f"</p>"
        )

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#222;">
  <div style="max-width:560px;margin:0 auto;padding:32px 24px;background:#ffffff;">
    <h1 style="font-size:22px;font-weight:600;margin:0 0 16px;">{headline}</h1>
    <p style="font-size:16px;line-height:1.6;margin:0 0 12px;">Hi {greeting_name},</p>
    <p style="font-size:16px;line-height:1.6;margin:0 0 8px;">
      Your voice analysis is complete. We extracted your best moments and added detailed feedback.
    </p>
    {theme_line}
    {cta_block}
    {footer_unsub}
  </div>
</body>
</html>"""

    # Plain-text fallback for clients that prefer text/plain. Hand-
    # built rather than regex-stripped so line breaks read cleanly.
    text_lines = [
        headline,
        "",
        f"Hi {first_name or 'there'},",
        "",
        "Your voice analysis is complete. We extracted your best "
        "moments and added detailed feedback.",
    ]
    if top_theme:
        text_lines.append(f"Top theme this session: {top_theme}.")
    if journey_url:
        text_lines.extend(["", f"View your results: {journey_url}"])
    if unsubscribe_url:
        text_lines.extend(["", f"Unsubscribe: {unsubscribe_url}"])

    return {"html": html_body, "text": "\n".join(text_lines)}
