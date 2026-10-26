"""The five emails of Email and password on Data & consent (WIL-95; founder
2026-10-26, N190, approved on the prototype
docs/design/settings-email-password-2026-10-26.html).

Every word below is the prototype's, signed with it. The logic that decides
which email goes where is services/account_security.py; this module only
renders them, in the same look as the coach's feedback email.

  confirm_new     to the new address: the link that changes the email
  notice_old      to the old address, at the same moment
  password_changed to the account, after the password changed
  reset           to the account: the link to Set new password
  set_password    to an account that signs in with Google or LinkedIn
"""
from __future__ import annotations

import html
from typing import Any, Optional

SUPPORT = "contact@willpowerlab.com"
IGNORE = "If you didn’t ask for this, ignore this email."
NOT_YOU = f"If this wasn’t you, write to {SUPPORT}."


def _mail(subject: str, lines: list[str], *, cta: Optional[str] = None,
          url: Optional[str] = None, foot: Optional[str] = None) -> dict[str, Any]:
    return {"subject": subject, "lines": lines, "cta": cta or "", "url": url or "",
            "foot": foot or ""}


def confirm_new(*, to: str, url: str) -> dict[str, Any]:
    return _mail("Confirm your new email",
                 [f"Open this link to make {to} your WillpowerLab email."],
                 cta="Confirm email", url=url, foot=IGNORE)


def notice_old(*, to: str) -> dict[str, Any]:
    return _mail("Your email is changing",
                 [f"You asked to change your WillpowerLab email to {to}. "
                  "It changes when you open the link we sent there.", NOT_YOU])


def password_changed(*, when: str) -> dict[str, Any]:
    return _mail("Your password was changed",
                 [f"Your WillpowerLab password was changed on {when}. "
                  "Other devices were signed out.", NOT_YOU])


def reset(*, url: str) -> dict[str, Any]:
    return _mail("Reset your password",
                 ["Open this link to set a new WillpowerLab password. It works for 1 hour."],
                 cta="Set a new password", url=url, foot=IGNORE)


def set_password(*, provider: str, url: str) -> dict[str, Any]:
    return _mail("Set your password",
                 ["Open this link to set a WillpowerLab password. "
                  f"You can still sign in with {provider}."],
                 cta="Set a password", url=url, foot=IGNORE)


def render(mail: dict[str, Any]) -> dict[str, str]:
    """``{subject, html, text}`` for one of the mails above. Pure."""
    from services.email_wordmark import wordmark_html
    esc = html.escape
    paragraphs = "".join(
        '<p style="margin:16px 0 0 0;font-size:16px;line-height:26px;color:#1F1A14;">'
        f"{esc(line)}</p>" for line in mail["lines"])
    button = (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;margin-top:32px;"><tr><td align="center">'
        f'<a href="{esc(mail["url"], quote=True)}" style="display:inline-block;'
        "background-color:#F97316;color:#FFFFFF;text-decoration:none;font-weight:600;"
        "font-size:15px;line-height:20px;padding:14px 28px;border-radius:9999px;\">"
        f'{esc(mail["cta"])}</a></td></tr></table>' if mail["cta"] else "")
    foot = (
        '<p style="margin:24px 0 0 0;font-size:13px;line-height:20px;color:#6B6256;">'
        f'{esc(mail["foot"])}</p>' if mail["foot"] else "")
    page = "https://www.willpowerlab.com"
    body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="color-scheme" content="light only"></head>
<body style="margin:0;padding:32px 16px;background-color:#FAF7F2;color:#1F1A14;font-family:ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
  <div style="max-width:580px;margin:0 auto;">
    {wordmark_html()}
    <div style="background-color:#FCFAF6;border:1px solid #EFE9DE;border-radius:16px;padding:24px 40px 40px 40px;">
      {paragraphs}
      {button}
      {foot}
    </div>
    <p style="margin:0;padding:24px 8px 0 8px;text-align:center;font-size:12px;line-height:18px;color:#6B6256;">
      <a href="{page}/privacy" style="color:#6B6256;text-decoration:underline;">Privacy</a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="{page}/terms" style="color:#6B6256;text-decoration:underline;">Terms</a>
    </p>
  </div>
</body>
</html>"""
    text = ["WillpowerLab", "", *mail["lines"]]
    if mail["cta"]:
        text += ["", f'{mail["cta"]}: {mail["url"]}']
    if mail["foot"]:
        text += ["", mail["foot"]]
    return {"subject": mail["subject"], "html": body, "text": "\n".join(text)}
