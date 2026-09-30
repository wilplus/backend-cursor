"""The WillpowerLab logo for email headers, as text rather than a picture.

Founder 2026-09-30: the coach's email showed a broken image where the logo
should be ("make it a font not a picture pasted"). The header was an <img> of
/willab-logo, and a mail client that holds back remote images (Proton's
tracker protection, Outlook, Gmail with images off) draws an empty box there.

This is the same mark as the app's Logo.tsx and the /willab-logo PNG: three
black dots in a voice rhythm, the middle one larger, beside "WillpowerLab" in
a black semibold sans. It is plain HTML with inline styles and no web font, so
every client shows it without loading anything. Clients that ignore
border-radius (older Outlook) draw the dots as small squares; the word is the
same everywhere.
"""
from __future__ import annotations

INK = "#121212"
FONT_STACK = (
    "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "
    "'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
)


def _dot(size: int) -> str:
    return (
        f'<span style="display:inline-block;width:{size}px;height:{size}px;'
        f'border-radius:{size}px;background:{INK};vertical-align:middle;'
        'margin:0 3px;"></span>'
    )


def wordmark_html() -> str:
    """The centred header row: the three dots, then the word."""
    return (
        '<div style="text-align:center;margin:0 0 24px;" role="img" '
        'aria-label="WillpowerLab">'
        f'{_dot(8)}{_dot(12)}{_dot(8)}'
        f'<span style="display:inline-block;vertical-align:middle;margin-left:10px;'
        f'font-family:{FONT_STACK};font-size:22px;line-height:28px;'
        f'font-weight:600;letter-spacing:-0.3px;color:{INK};">WillpowerLab</span>'
        '</div>'
    )
