"""Canonical language eligibility for blind confidence raters.

Language comprehension is a queue-routing constraint, never a confidence
answer.  A mismatch must not be collapsed into ``not_sure`` or
``audio_unclear`` because both would corrupt the five-state instrument.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any


_ISO_639_1 = re.compile(r"^[a-z]{2}$")
MAX_LANGUAGES = 20


def normalize_language(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    code = value.strip().lower()
    return code if _ISO_639_1.fullmatch(code) else None


def validate_proficient_languages(value: Any) -> tuple[list[str] | None, str | None]:
    """Validate a non-empty, unique ISO-639-1 language list."""
    if not isinstance(value, list):
        return None, "proficient_languages: must be an array"
    if not value:
        return None, "proficient_languages: choose at least one language"
    if len(value) > MAX_LANGUAGES:
        return None, f"proficient_languages: choose at most {MAX_LANGUAGES} languages"
    out: list[str] = []
    for raw in value:
        code = normalize_language(raw)
        if code is None:
            return None, "proficient_languages: use two-letter ISO language codes"
        if code not in out:
            out.append(code)
    return sorted(out), None


def session_language(
    session: Any,
    *,
    recording: Any = None,
    snippets: Any = None,
) -> str | None:
    """Resolve one declared/detected language without guessing from text."""
    row = session if isinstance(session, dict) else {}
    ctx = row.get("intake_context")
    ctx = ctx if isinstance(ctx, dict) else {}
    explicit = normalize_language(ctx.get("language"))
    if explicit:
        return explicit

    rec = recording if isinstance(recording, dict) else {}
    detected = normalize_language(rec.get("transcription_language"))
    if detected:
        return detected

    observed = [
        normalize_language(item.get("language"))
        for item in (snippets or [])
        if isinstance(item, dict)
    ]
    counts = Counter(code for code in observed if code)
    return counts.most_common(1)[0][0] if counts else None


def can_rate_language(proficient: Any, clip_language: Any) -> bool:
    """True only for an explicit, exact language match."""
    code = normalize_language(clip_language)
    if code is None or not isinstance(proficient, (list, tuple)):
        return False
    known = {normalize_language(value) for value in proficient}
    return code in known


def evaluate_rater_access(proficient: Any, clip_language: Any) -> str:
    """Return the routing outcome without turning it into a rating.

    This is deliberately a four-state queue decision rather than a boolean so
    callers can distinguish an unconfigured rater from an unclassified clip.
    Neither state is evidence about the speaker's confidence.
    """
    known = {
        code
        for value in (proficient or [])
        if (code := normalize_language(value)) is not None
    } if isinstance(proficient, (list, tuple)) else set()
    if not known:
        return "profile_required"
    code = normalize_language(clip_language)
    if code is None:
        return "language_unknown"
    return "matched" if code in known else "mismatch"
