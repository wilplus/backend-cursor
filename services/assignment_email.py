"""
Assignment email HTML builder (Willab design).
Video block: with video_url → dark area + orange play button linking to URL;
without → orange gradient block. Coach message from video_description or default.
Assigned exercise line when has_assigned_exercise is True.
"""
import re
from html import escape

DEFAULT_COACH_MESSAGE = (
    "Good work. It is a small step for you, but a huge step for your progress!"
)

PRIMARY = "#f97316"
FOREGROUND = "#1b2236"
BACKGROUND = "#ffffff"
MUTED_FG = "#6b7280"
SECONDARY_BG = "#f3f4f6"
BORDER = "#e5e7eb"
EMAIL_BG = "#f3f4f6"
GRADIENT_START = "#f97316"
GRADIENT_END = "#ea580c"


def _paragraphs(text: str) -> list:
    """Split into paragraphs (double newline), escape HTML."""
    if not (text and text.strip()):
        return []
    return [
        escape(p.strip()).replace("\n", "<br>\n")
        for p in re.split(r"\n\n+", text.strip())
        if p.strip()
    ]


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
) -> str:
    """Build the full HTML for the assignment email."""
    has_video = bool(video_url and video_url.strip())
    body_paragraphs = _paragraphs(coach_message) if coach_message and coach_message.strip() else []
    if not body_paragraphs:
        body_paragraphs = [escape(DEFAULT_COACH_MESSAGE)]

    if student_name and student_name.strip() and student_name != "there":
        title = f"Great progress, {escape(student_name)}!"
    else:
        title = "Great progress this week!"

    if has_video:
        video_block = f"""
        <tr>
          <td style="background: #1b2236; padding: 80px 24px; text-align: center;">
            <a href="{escape(video_url)}" style="display: inline-block; text-decoration: none;">
              <table role="presentation" cellpadding="0" cellspacing="0" align="center">
                <tr>
                  <td style="width: 80px; height: 80px; border-radius: 50%; background: {PRIMARY}; text-align: center; vertical-align: middle;">
                    <span style="display: inline-block; width: 0; height: 0; margin-left: 8px; border-style: solid; border-width: 14px 0 14px 24px; border-color: transparent transparent transparent #fff;"></span>
                  </td>
                </tr>
              </table>
            </a>
          </td>
        </tr>
        """
    else:
        video_block = f"""
        <tr>
          <td style="padding: 80px 24px; background: {PRIMARY}; background: linear-gradient(135deg, {GRADIENT_START} 0%, #ea580c 50%, #d97706 100%);"></td>
        </tr>
        """

    body_html = "".join(
        f'<p style="margin: 0 0 1rem; font-size: 15px; line-height: 1.6; color: {FOREGROUND}; opacity: 0.9;">{p}</p>'
        for p in body_paragraphs
    )

    exercise_line = ""
    if has_assigned_exercise:
        exercise_line = f"""
        <p style="margin: 0.5rem 0 0; font-size: 14px; color: {MUTED_FG};">
          You have an exercise assigned — it will appear on the main screen after you follow the link below.
        </p>
        """

    has_coach_image = bool(coach_image_url and coach_image_url.strip())
    if has_coach_image:
        coach_avatar_html = f'<img src="{escape(coach_image_url)}" width="36" height="36" style="border-radius: 50%; display: block; object-fit: cover;" alt="{escape(coach_name)}" />'
    else:
        initials = escape(coach_name[:2].upper() if len(coach_name) >= 2 else (coach_name.upper() if coach_name else ""))
        coach_avatar_html = f'<span style="display: inline-block; font-size: 12px; font-weight: 600; color: {PRIMARY};">{initials}</span>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Public speaking!</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Serif+Display&display=swap" rel="stylesheet">
</head>
<body style="margin: 0; padding: 2rem 1rem; font-family: 'DM Sans', sans-serif; background: {EMAIL_BG}; -webkit-font-smoothing: antialiased;">
  <div style="max-width: 600px; margin: 0 auto;">
    <div style="text-align: center; margin-bottom: 1.5rem;">
      <p style="margin: 0; font-size: 18px; font-weight: 700; color: {FOREGROUND};">
        Willab<span style="color: {PRIMARY};"></span>
      </p>
      <p style="margin: 0.25rem 0 0; font-size: 14px; color: {MUTED_FG};">
        Homework tool for public speaking
      </p>
    </div>

    <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background: {BACKGROUND}; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 16px -4px rgba(27, 34, 54, 0.07);">
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
        {video_block}
      </table>
      <tr>
        <td style="padding: 2.5rem 2.5rem 0;">
          <p style="margin: 0; font-size: 14px; font-weight: 500; color: {MUTED_FG};">{escape(meta_label)}</p>
          <h1 style="margin: 0.25rem 0 1.5rem; font-family: 'DM Serif Display', serif; font-size: 28px; font-weight: 400; color: {FOREGROUND};">{title}</h1>
          {body_html}
        </td>
      </tr>
      <tr>
        <td style="padding: 0 2.5rem; height: 1px; background: {BORDER};"></td>
      </tr>
      <tr>
        <td style="padding: 2rem 2.5rem;">
          <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background: {SECONDARY_BG}; border-radius: 8px;">
            <tr>
              <td style="padding: 1.5rem; vertical-align: top;">
                <table role="presentation" cellpadding="0" cellspacing="0">
                  <tr>
                    <td style="width: 40px; height: 40px; border-radius: 8px; background: rgba(249, 115, 22, 0.1); vertical-align: top; padding-top: 8px; padding-left: 8px;">
                      <span style="color: {PRIMARY}; font-size: 20px;">📖</span>
                    </td>
                    <td style="padding-left: 1rem;">
                      <h2 style="margin: 0; font-family: 'DM Serif Display', serif; font-size: 18px; font-weight: 600; color: {FOREGROUND};">{escape(homework_title)}</h2>
                      <p style="margin: 0.25rem 0 0; font-size: 14px; color: {MUTED_FG};">{escape(homework_subtitle)}</p>
                      {exercise_line}
                      <a href="{escape(homework_link)}" style="display: inline-flex; align-items: center; gap: 0.5rem; margin-top: 0.75rem; padding: 0.625rem 1.5rem; font-size: 14px; font-weight: 500; color: #fff; background: {PRIMARY}; border-radius: 6px; text-decoration: none;">View Homework →</a>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>

          <table role="presentation" cellpadding="0" cellspacing="0" style="margin-top: 2rem; padding-top: 2rem; border-top: 1px solid {BORDER};">
            <tr>
              <td style="width: 36px; height: 36px; border-radius: 50%; background: rgba(249, 115, 22, 0.15); text-align: center; vertical-align: middle; overflow: hidden;">
                {coach_avatar_html}
              </td>
              <td style="padding-left: 0.75rem;">
                <p style="margin: 0; font-size: 14px; font-weight: 600; color: {FOREGROUND};">{escape(coach_name)}</p>
                <p style="margin: 0; font-size: 12px; color: {MUTED_FG};">{escape(coach_role)}</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>

    <p style="text-align: center; font-size: 12px; color: {MUTED_FG}; margin-top: 1.5rem;">
      You received this because you're enrolled in a coaching program.
    </p>
    <p style="text-align: center; font-size: 12px; color: {MUTED_FG}; margin-top: 0.25rem;">
      <a href="{escape(unsubscribe_link)}" style="color: {MUTED_FG}; text-decoration: underline;">Unsubscribe</a>
      &nbsp;·&nbsp;
      <a href="{escape(preferences_link)}" style="color: {MUTED_FG}; text-decoration: underline;">Preferences</a>
    </p>
  </div>
</body>
</html>
"""
    return html
