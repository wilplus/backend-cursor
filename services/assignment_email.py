"""Dedicated HTML builders for the 3 email templates."""
from html import escape

DEFAULT_COACH_MESSAGE = "Good work. It is a small step for you, but a huge step for your progress!"
DEFAULT_AI_INSIGHT = (
    "You had strong energy and clear intent. Focus next on slowing transitions between points and reducing filler words in openings."
)


def _initials(name: str | None) -> str:
    raw = (name or "").strip()
    if not raw:
        return "CO"
    parts = [p for p in raw.replace("_", " ").split(" ") if p.strip()]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return (parts[0][:2]).upper()


def _short(text: str | None, limit: int) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[:limit].rstrip() + "..."


def _logo_html(_logo_url: str | None = None) -> str:
    """Always renders the Willab text logo in Pacifico, matching the navbar WillabLogo component.
    Uses an inline <style>@import for Gmail compatibility (Gmail strips <link> tags)."""
    return (
        '<style>@import url("https://fonts.googleapis.com/css2?family=Pacifico&display=swap");</style>'
        '<span style="font-family:\'Pacifico\',cursive;'
        'font-size:24px;font-weight:400;color:#2d3748;letter-spacing:-0.5px;">'
        'Willab<span style="color:#f97316;">.</span></span>'
    )


LOGO_URL = "https://www.willpowerlab.com/willab-logo"


def _email_row(label: str, value_html: str) -> str:
    """One label/value line, styled like the student email's rows.

    `value_html` is HTML and is NOT escaped here: the student row needs a
    pre-escaped "Name (email)" built by the caller. Escape at the call site,
    never here, or the parentheses come back double-escaped. The label IS
    escaped, because every label is a literal.
    """
    return (
        '<tr><td style="padding:12px 0;border-top:1px solid #EFE9DE;'
        'font-size:13px;color:#8C8378;width:40%;vertical-align:top;">'
        f'{escape(label)}</td>'
        '<td style="padding:12px 0;border-top:1px solid #EFE9DE;'
        f'font-size:15px;color:#1F1A14;font-weight:500;">{value_html}</td></tr>'
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

    RESTYLED 2026-09-28 to the student email's design system (same ground,
    same card, same pill button, same wordmark) — founder asked for one look
    across both.

    WHAT WAS REMOVED AND WHY:

    * Pace and Filler words. The caller passed `pace_wpm=None,
      filler_count=None` as literals, so both rows could only ever render
      "n/a WPM (target 120-160)" and "n/a", for every student, forever.
      They were not missing data; they were rows with no source.
    * Strength: "Loudness (pending)". Same: a constant default that never
      became anything.
    * The performance score. It was center_hold_ratio * 100 minus three
      points per filler (services/metrics_v2.py) — loudness and filler
      count, which is the pre-V3 "good public speaker" measure the product
      stopped reasoning about. Founder deferred it 2026-09-28.

    The report preview keeps the product's own rule for an empty lane: when
    there is nothing to show it draws NO card, rather than a card saying
    there is nothing (contract 24f).
    """
    safe_name = escape((student_name or "").strip())
    student_label = (
        f"{safe_name} ({escape(student_email)})" if safe_name
        else escape(student_email)
    )
    logo = (logo_url or "").strip() or LOGO_URL
    rows = [_email_row("Student", student_label)]
    if (lesson_label or "").strip():
        rows.append(_email_row("Lesson", escape(lesson_label.strip())))
    if isinstance(moments_awaiting, int) and moments_awaiting > 0:
        rows.append(_email_row("Moments to review", str(moments_awaiting)))
    excerpt = _short(transcript_excerpt, 260)
    preview_block = ""
    if excerpt:
        preview_block = (
            '<div style="margin:24px 0 0;padding:20px 22px;background:#F6F1E8;'
            'border-radius:12px;">'
            '<p style="margin:0 0 10px;font-size:11px;color:#8C8378;'
            "text-transform:uppercase;letter-spacing:1px;\">Report preview</p>"
            '<p style="margin:0;font-size:14px;color:#5B5349;line-height:1.6;'
            f'font-style:italic;">&ldquo;{escape(excerpt)}&rdquo;</p></div>'
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Student Homework Completed — Willab</title>
</head>
<body style="margin:0;padding:0;background:#FAF7F2;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#1F1A14;">
  <div style="max-width:560px;margin:0 auto;padding:32px 20px;">
    <div style="text-align:center;margin:0 0 24px;"><img src="{escape(logo)}" alt="WillpowerLab" width="182" height="42" style="display:inline-block;width:182px;height:auto;border:0;"></div>
    <div style="background:#FCFAF6;border:1px solid #EFE9DE;border-radius:16px;padding:32px;">
      <h1 style="margin:0 0 24px;font-size:22px;line-height:1.3;font-weight:600;color:#1F1A14;">A student has completed a homework lesson.</h1>
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{"".join(rows)}</table>
      <div style="text-align:center;margin:28px 0 0;">
        <a href="{escape(profile_url)}" style="display:inline-block;background:#F97316;color:#fff;padding:14px 28px;border-radius:9999px;text-decoration:none;font-size:15px;font-weight:600;">View profile &amp; send homework</a>
      </div>
      {preview_block}
    </div>
    <p style="margin:24px 0 0;text-align:center;font-size:12px;color:#9C9488;">Willab</p>
  </div>
</body>
</html>"""


def build_student_new_homework_email_html(
    *,
    student_first_name: str,
    coach_message: str,
    coach_name: str,
    coach_role: str,
    homework_url: str,
    logo_url: str | None = None,
) -> str:
    safe_coach = escape((coach_name or "Coach").strip() or "Coach")
    safe_role = escape((coach_role or "Public Speaking Coach").strip() or "Public Speaking Coach")
    safe_message = escape((coach_message or DEFAULT_COACH_MESSAGE).strip() or DEFAULT_COACH_MESSAGE)
    initials = escape(_initials(safe_coach))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>New Homework Available — Willab</title>
</head>
<body style="margin:0;padding:0;background-color:#fafafa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background-color:#fafafa;padding:48px 16px;">
<tr><td align="center">
<table width="520" cellpadding="0" cellspacing="0" style="max-width:520px;width:100%;">
<tr><td style="padding-bottom:40px;">
  {_logo_html(logo_url)}
</td></tr>
<tr><td style="background-color:#ffffff;border-radius:8px;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td style="padding:36px 36px 0;">
  <p style="margin:0;font-size:18px;font-weight:600;color:#1e293b;line-height:1.4;">Hey! New practice available!</p>
</td></tr>
<tr><td style="padding:20px 36px 0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#fafafa;border-radius:6px;border-left:2px solid #f97316;">
    <tr><td style="padding:16px 20px;">
      <p style="margin:0;font-size:14px;color:#1e293b;line-height:1.6;font-style:italic;">"{safe_message}"</p>
    </td></tr>
  </table>
</td></tr>
<tr><td style="padding:28px 36px 0;">
  <a href="{escape(homework_url)}" style="display:inline-block;background-color:#f97316;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;padding:12px 28px;border-radius:6px;">View homework →</a>
</td></tr>
<tr><td style="padding:28px 36px 0;"><div style="border-top:1px solid #f1f5f9;"></div></td></tr>
<tr><td style="padding:24px 36px 32px;">
  <table cellpadding="0" cellspacing="0">
    <tr>
      <td style="width:36px;vertical-align:top;">
        <div style="width:32px;height:32px;border-radius:50%;background-color:#1e293b;color:#ffffff;font-size:12px;font-weight:600;text-align:center;line-height:32px;">{initials}</div>
      </td>
      <td style="padding-left:10px;">
        <p style="margin:0;font-size:14px;font-weight:600;color:#1e293b;">{safe_coach}</p>
        <p style="margin:0;font-size:12px;color:#94a3b8;">{safe_role}</p>
      </td>
    </tr>
  </table>
</td></tr>
</table>
</td></tr>
<tr><td style="padding:32px 0;text-align:center;">
  <p style="margin:0;font-size:12px;color:#cbd5e1;">Willab</p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


# Backward-compatible wrapper; keep while callers migrate.
def build_assignment_email_html(
    *,
    video_url: str | None = None,
    coach_message: str | None = None,
    homework_link: str,
    student_name: str = "there",
    meta_label: str = "Session Recap",
    homework_title: str = "Public speaking!",
    homework_subtitle: str = "Your next assignment is ready.",
    coach_name: str = "Your Coach",
    coach_role: str = "Public Speaking Coach",
    coach_image_url: str | None = None,
    unsubscribe_link: str = "#",
    preferences_link: str = "#",
    logo_url: str | None = None,
) -> str:
    _ = (video_url, meta_label, homework_title, homework_subtitle, coach_image_url, unsubscribe_link, preferences_link)
    return build_student_new_homework_email_html(
        student_first_name=student_name,
        coach_message=coach_message or DEFAULT_COACH_MESSAGE,
        coach_name=coach_name,
        coach_role=coach_role,
        homework_url=homework_link,
        logo_url=logo_url,
    )
