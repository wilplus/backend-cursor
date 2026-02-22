"""Validation for optional video_url (send-assignment). No Flask dependency so tests can run without the app."""
from typing import Optional

VIDEO_URL_MAX_LENGTH = 2048


def validate_video_url(video_url) -> Optional[str]:
    """
    Validate optional video URL: non-empty string, max 2048 chars, must start with http:// or https://.
    Returns the stripped URL if valid, else None.
    """
    if video_url is None:
        return None
    if not isinstance(video_url, str):
        return None
    s = video_url.strip()
    if not s or len(s) > VIDEO_URL_MAX_LENGTH:
        return None
    if not (s.startswith("http://") or s.startswith("https://")):
        return None
    return s
