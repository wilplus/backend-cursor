"""Dedicated HTML builders for the 3 email templates."""
from html import escape

from services.email_wordmark import wordmark_html


def _short(text: str | None, limit: int) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[:limit].rstrip() + "..."


# Mirrored from emails/PostSessionResultsEmail.tsx (FONT_STACK_SYSTEM).
_FONT_STACK = (
    "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "
    "'Segoe UI', Roboto, sans-serif"
)


def _email_row(label: str, value_html: str) -> str:
    """One label/value line, styled like the student email's rows.

    `value_html` is HTML and is NOT escaped here: the student row needs a
    pre-escaped "Name (email)" built by the caller. Escape at the call site,
    never here, or the parentheses come back double-escaped. The label IS
    escaped, because every label is a literal.
    """
    return (
        '<tr><td style="padding:12px 0;border-top:1px solid #EFE9DE;'
        'font-size:13px;color:#6B6256;width:40%;vertical-align:top;">'
        f'{escape(label)}</td>'
        '<td style="padding:12px 0;border-top:1px solid #EFE9DE;'
        f'font-size:16px;color:#1F1A14;font-weight:600;">{value_html}</td></tr>'
    )


def build_admin_homework_completed_email_html(
    *,
    student_email: str,
    profile_url: str,
    moments_awaiting: int | None = None,
    lesson_label: str = "",
    transcript_excerpt: str = "",
    logo_url: str | None = None,
    student_name: str = "",
) -> str:
    """The coach's "a lesson is in your queue" email.

    RESTYLED 2026-09-29 to the student email, token for token. Every value
    below is copied from emails/PostSessionResultsEmail.tsx in the frontend
    repo: the same ground, card, border, wordmark, type scale and pill.

    TWO SOURCES OF TRUTH, DELIBERATELY FLAGGED. The student email is a React
    Email template the FRONTEND renders: the backend POSTs props to
    /api/internal/emails/post-session-results and gets HTML back, so that
    "the React Email template stays the single source of truth: backend never
    re-implements the layout in Jinja or hand-written HTML" (that route's own
    words). THIS email is hand-written HTML in Python, so it can drift from
    the template it copies the moment either side is edited. Matching by hand
    is the stopgap; the fix is a second React Email template rendered the
    same way.

    WHAT IS NOT HERE, AND WHY:

    * Pace and Filler words. The caller passed `pace_wpm=None,
      filler_count=None` as LITERALS, so both rows could only ever render
      "n/a WPM (target 120-160)" and "n/a", for every student, forever.
      They were not missing data; they were rows with no source.
    * "Strength: Loudness (pending)" - a constant default that never became
      anything.
    * The performance score. center_hold_ratio * 100 minus three points per
      filler (services/metrics_v2.py) - loudness and filler count, the
      pre-V3 "good public speaker" measure. Founder deferred it 2026-09-28.
      A confidence-based score is NOT a drop-in replacement: this email
      reaches the coach BEFORE they blind-rate the take, so a machine read
      inside it would hand them the answer first (BLIND COACH).

    The eyebrow carries the lesson rather than a new phrase, so the design
    gains its top line without inventing copy to fill it.

    An empty report preview draws NO card, rather than a card announcing
    there is nothing - contract 24f's rule for an honest empty lane.
    """
    safe_name = escape((student_name or "").strip())
    student_label = (
        f"{safe_name} ({escape(student_email)})" if safe_name
        else escape(student_email)
    )
    eyebrow = escape((lesson_label or "").strip()) or "Homework"
    rows = [_email_row("Student", student_label)]
    if isinstance(moments_awaiting, int) and moments_awaiting > 0:
        rows.append(_email_row("Moments to review", str(moments_awaiting)))
    excerpt = _short(transcript_excerpt, 260)
    preview_block = ""
    if excerpt:
        preview_block = (
            '<div style="margin:24px 0 0;padding:18px 20px;background:#FFEDD5;'
            'border-radius:12px;">'
            '<p style="margin:0 0 8px;font-size:11px;letter-spacing:0.06em;'
            'text-transform:uppercase;color:#6B6256;font-weight:600;">'
            'Report preview</p>'
            '<p style="margin:0;font-size:15px;line-height:24px;color:#1F1A14;'
            f'font-style:italic;">&ldquo;{escape(excerpt)}&rdquo;</p></div>'
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Student Homework Completed — Willab</title>
</head>
<body style="margin:0;padding:0;background:#FAF7F2;font-family:{_FONT_STACK};color:#1F1A14;">
  <div style="max-width:600px;margin:0 auto;padding:32px 20px;">
    {wordmark_html()}
    <div style="background:#FCFAF6;border:1px solid #EFE9DE;border-radius:16px;padding:40px;">
      <p style="margin:0;font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#F97316;font-weight:600;">{eyebrow}</p>
      <h1 style="margin:8px 0 0 0;font-family:{_FONT_STACK};font-weight:600;font-size:28px;line-height:34px;color:#1F1A14;">A student has completed a homework lesson.</h1>
      <table width="100%" cellpadding="0" cellspacing="0" style="margin:24px 0 0;border-collapse:collapse;">{"".join(rows)}</table>
      <div style="text-align:center;margin:28px 0 0;">
        <a href="{escape(profile_url)}" style="display:inline-block;background-color:#F97316;color:#FFFFFF;text-decoration:none;font-weight:600;font-size:15px;line-height:20px;padding:14px 28px;border-radius:9999px;">View profile &amp; send homework</a>
      </div>
      {preview_block}
    </div>
    <p style="margin:24px 0 0;text-align:center;font-size:12px;color:#6B6256;">Willab</p>
  </div>
</body>
</html>"""



def build_admin_homework_digest_email_html(*, rows: list[dict],
                                           date_label: str) -> dict[str, str]:
    """The founder's once-a-day "Homework" email (founder 2026-10-26, N174
    item 3): one row per student who sent a Take since the last one, with
    how many Takes and moments wait in the coach queue, and their profile.
    Same look as the one-Take email above; no machine read of any Take
    (BLIND COACH). ``{html, text}``. Pure."""
    lines = []
    for row in rows:
        takes = int(row.get("takes") or 0)
        moments = int(row.get("moments") or 0)
        what = f"{takes} {'Take' if takes == 1 else 'Takes'}"
        if moments > 0:
            what += f", {moments} {'moment' if moments == 1 else 'moments'} to review"
        lines.append((row.get("label") or "", what, row.get("url") or "#"))
    table = "".join(
        '<tr><td style="padding:12px 0;border-top:1px solid #EFE9DE;font-size:16px;'
        f'color:#1F1A14;font-weight:600;">{escape(label)}'
        f'<div style="font-size:13px;color:#6B6256;font-weight:400;margin-top:2px;">{escape(what)}</div></td>'
        '<td style="padding:12px 0;border-top:1px solid #EFE9DE;text-align:right;vertical-align:top;">'
        f'<a href="{escape(url, quote=True)}" style="color:#F97316;font-weight:600;font-size:14px;'
        'text-decoration:none;">Profile</a></td></tr>'
        for label, what, url in lines)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Homework — Willab</title>
</head>
<body style="margin:0;padding:0;background:#FAF7F2;font-family:{_FONT_STACK};color:#1F1A14;">
  <div style="max-width:600px;margin:0 auto;padding:32px 20px;">
    {wordmark_html()}
    <div style="background:#FCFAF6;border:1px solid #EFE9DE;border-radius:16px;padding:40px;">
      <p style="margin:0;font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#F97316;font-weight:600;">Homework · {escape(date_label)}</p>
      <h1 style="margin:8px 0 0 0;font-family:{_FONT_STACK};font-weight:600;font-size:28px;line-height:34px;color:#1F1A14;">Students who completed a homework lesson.</h1>
      <table width="100%" cellpadding="0" cellspacing="0" style="margin:24px 0 0;border-collapse:collapse;">{table}</table>
    </div>
    <p style="margin:24px 0 0;text-align:center;font-size:12px;color:#6B6256;">Willab</p>
  </div>
</body>
</html>"""
    text = "\n".join(
        [f"Homework · {date_label}", "", "Students who completed a homework lesson.", ""]
        + [f"{label}: {what}\n  {url}" for label, what, url in lines])
    return {"html": html, "text": text}
