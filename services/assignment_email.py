"""Dedicated HTML builders for the 3 email templates."""
from html import escape

DEFAULT_COACH_MESSAGE = "Good work. It is a small step for you, but a huge step for your progress!"
DEFAULT_AI_INSIGHT = (
    "You had strong energy and clear intent. Focus next on slowing transitions between points and reducing filler words in openings."
)


def _first_name(name_or_email: str | None) -> str:
    raw = (name_or_email or "").strip()
    if not raw:
        return "there"
    if "@" in raw:
        raw = raw.split("@", 1)[0]
    first = raw.replace("_", " ").replace(".", " ").split(" ")[0].strip()
    return first.capitalize() if first else "there"


def _initials(name: str | None) -> str:
    raw = (name or "").strip()
    if not raw:
        return "CO"
    parts = [p for p in raw.replace("_", " ").split(" ") if p.strip()]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return (parts[0][:2]).upper()


def _score_percent(score: float | int | None) -> int:
    if score is None:
        return 0
    try:
        v = float(score)
    except (TypeError, ValueError):
        return 0
    if v <= 1.0:
        v *= 100.0
    return max(0, min(100, round(v)))


def _short(text: str | None, limit: int) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[:limit].rstrip() + "..."


def _logo_html(logo_url: str | None) -> str:
    url = (logo_url or "").strip()
    if url:
        return (
            f'<img src="{escape(url)}" alt="Willab" '
            'style="display:block;height:28px;width:auto;max-width:180px;">'
        )
    return (
        '<style>@import url(\'https://fonts.googleapis.com/css2?family=Pacifico&display=swap\');</style>'
        '<span style="font-family:\'Pacifico\',Georgia,\'Times New Roman\',serif;font-size:22px;'
        'font-weight:400;color:#1e293b;letter-spacing:-0.3px;">'
        'Willab<span style="color:#f97316;">.</span></span>'
    )


def build_admin_homework_completed_email_html(
    *,
    student_email: str,
    score: float | int | None,
    profile_url: str,
    transcript_excerpt: str = "",
    pace_wpm: int | None = None,
    filler_count: int | None = None,
    strength: str = "Loudness (pending)",
    logo_url: str | None = None,
    student_name: str = "",
) -> str:
    pct = _score_percent(score)
    pace_text = f"{pace_wpm} WPM" if pace_wpm is not None else "n/a WPM"
    fillers_text = str(filler_count) if filler_count is not None else "n/a"
    excerpt = _short(transcript_excerpt, 260) or "No transcript preview available yet."
    safe_name = escape((student_name or "").strip())
    student_label = f"{safe_name} ({escape(student_email)})" if safe_name else escape(student_email)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Student Homework Completed — Willab</title>
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
  <p style="margin:0 0 24px;font-size:18px;font-weight:600;color:#1e293b;line-height:1.4;">A student has completed a homework lesson.</p>
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td style="padding:14px 0;border-top:1px solid #f1f5f9;font-size:14px;color:#94a3b8;width:100px;">Student</td>
      <td style="padding:14px 0;border-top:1px solid #f1f5f9;font-size:14px;color:#1e293b;">{student_label}</td>
    </tr>
    <tr>
      <td style="padding:14px 0;border-top:1px solid #f1f5f9;font-size:14px;color:#94a3b8;">Score</td>
      <td style="padding:14px 0;border-top:1px solid #f1f5f9;font-size:24px;font-weight:600;color:#f97316;">{pct}%</td>
    </tr>
  </table>
</td></tr>
<tr><td style="padding:28px 36px;">
  <a href="{escape(profile_url)}" style="display:inline-block;background-color:#1e293b;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;padding:12px 28px;border-radius:6px;">View profile &amp; send homework</a>
</td></tr>
<tr><td style="padding:0 36px 36px;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#fafafa;border-radius:6px;">
    <tr><td style="padding:20px 24px;">
      <p style="margin:0 0 12px;font-size:12px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.8px;">Report preview</p>
      <p style="margin:0 0 16px;font-size:14px;color:#64748b;line-height:1.6;font-style:italic;">"{escape(excerpt)}"</p>
      <table cellpadding="0" cellspacing="0" style="font-size:14px;color:#64748b;line-height:2;">
        <tr><td>Pace: {escape(pace_text)} <span style="color:#cbd5e1;">(target 120–160)</span></td></tr>
        <tr><td>Filler words: {escape(fillers_text)}</td></tr>
        <tr><td>Strength: {escape(strength)}</td></tr>
      </table>
    </td></tr>
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


def build_student_new_homework_email_html(
    *,
    student_first_name: str,
    coach_message: str,
    coach_name: str,
    coach_role: str,
    homework_url: str,
    logo_url: str | None = None,
) -> str:
    safe_first = escape(_first_name(student_first_name))
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


def build_student_homework_submitted_email_html(
    *,
    student_first_name: str,
    score: float | int | None,
    recording_url: str,
    transcript_excerpt: str,
    filler_total: int | None,
    filler_breakdown: str,
    ai_insight: str,
    report_url: str,
    coach_name: str,
    coach_role: str,
    logo_url: str | None = None,
) -> str:
    safe_first = escape(_first_name(student_first_name))
    safe_coach = escape((coach_name or "Coach").strip() or "Coach")
    safe_role = escape((coach_role or "Public Speaking Coach").strip() or "Public Speaking Coach")
    pct = _score_percent(score)
    transcript = _short(transcript_excerpt, 80) or "No transcript yet."
    filler_total_text = str(filler_total) if filler_total is not None else "0"
    filler_breakdown_text = escape((filler_breakdown or "none").strip() or "none")
    insight = escape((ai_insight or DEFAULT_AI_INSIGHT).strip() or DEFAULT_AI_INSIGHT)
    initials = escape(_initials(safe_coach))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Homework Complete — Willab</title>
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
  <p style="margin:0 0 6px;font-size:18px;font-weight:600;color:#1e293b;line-height:1.4;">Great work, {safe_first}!</p>
  <p style="margin:0;font-size:14px;color:#64748b;line-height:1.6;">I will contact you soon with the feedback.</p>
</td></tr>
<tr><td style="padding:28px 36px 0;">
  <table cellpadding="0" cellspacing="0" style="background-color:#fafafa;border-radius:6px;width:100%;">
    <tr><td style="padding:20px 24px;text-align:center;">
      <p style="margin:0 0 4px;font-size:12px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.8px;">Performance score</p>
      <p style="margin:0;font-size:32px;font-weight:600;color:#f97316;">{pct}%</p>
    </td></tr>
  </table>
</td></tr>
<tr><td style="padding:28px 36px 0;"><div style="border-top:1px solid #f1f5f9;"></div></td></tr>
<tr><td style="padding:24px 36px 0;">
  <p style="margin:0 0 16px;font-size:14px;font-weight:600;color:#1e293b;">Your report</p>
  <table width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;color:#64748b;">
    <tr>
      <td style="padding:10px 0;border-bottom:1px solid #f1f5f9;">Playback</td>
      <td style="padding:10px 0;border-bottom:1px solid #f1f5f9;text-align:right;">
        <a href="{escape(recording_url)}" style="color:#f97316;text-decoration:none;">Open recording →</a>
      </td>
    </tr>
    <tr>
      <td style="padding:10px 0;border-bottom:1px solid #f1f5f9;">Transcript</td>
      <td style="padding:10px 0;border-bottom:1px solid #f1f5f9;text-align:right;font-style:italic;color:#94a3b8;">"{escape(transcript)}"</td>
    </tr>
    <tr>
      <td style="padding:10px 0;">Filler words</td>
      <td style="padding:10px 0;text-align:right;">{escape(filler_total_text)} <span style="color:#cbd5e1;">· {filler_breakdown_text}</span></td>
    </tr>
  </table>
</td></tr>
<tr><td style="padding:24px 36px 0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#fafafa;border-radius:6px;border-left:2px solid #f97316;">
    <tr><td style="padding:16px 20px;">
      <p style="margin:0 0 6px;font-size:12px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.8px;">AI Coach Insight</p>
      <p style="margin:0;font-size:14px;color:#64748b;line-height:1.6;">"{insight}"</p>
    </td></tr>
  </table>
</td></tr>
<tr><td style="padding:28px 36px;">
  <a href="{escape(report_url)}" style="display:inline-block;background-color:#1e293b;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;padding:12px 28px;border-radius:6px;">View full report</a>
</td></tr>
<tr><td style="padding:0 36px;"><div style="border-top:1px solid #f1f5f9;"></div></td></tr>
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
  <p style="margin:0 0 4px;font-size:12px;color:#cbd5e1;">Willab</p>
  <p style="margin:0;font-size:11px;color:#e2e8f0;">You received this because you're enrolled in coaching.</p>
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
    has_assigned_exercise: bool = False,
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
    _ = (video_url, has_assigned_exercise, meta_label, homework_title, homework_subtitle, coach_image_url, unsubscribe_link, preferences_link)
    return build_student_new_homework_email_html(
        student_first_name=student_name,
        coach_message=coach_message or DEFAULT_COACH_MESSAGE,
        coach_name=coach_name,
        coach_role=coach_role,
        homework_url=homework_link,
        logo_url=logo_url,
    )
