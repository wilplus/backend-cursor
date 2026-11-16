"""The language contract shared by the AI-voice generation and check lanes.

The recording's persisted ``transcription_language`` is the authority.  The
AI-voice lane currently has an explicit provider contract for English and
Polish only; an absent or different value is a configuration failure, never a
reason to guess English.
"""
from __future__ import annotations

import re
from typing import Any

from services.rater_languages import normalize_provider_language

SUPPORTED_LANGUAGES = frozenset(("en", "pl"))
TOKEN_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)


class LanguageConfigurationError(ValueError):
    """The persisted recording language cannot drive the AI-voice lane."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
        self.kind = "configuration"


def normalize(value: Any) -> str | None:
    code = normalize_provider_language(value)
    return code if code in SUPPORTED_LANGUAGES else None


def require(value: Any) -> str:
    code = normalize(value)
    if code is None:
        raw = str(value or "").strip().lower()
        raise LanguageConfigurationError(
            "recording_language_missing" if not raw else "recording_language_unsupported"
        )
    return code


def tokens(text: Any) -> list[str]:
    """Unicode-aware, punctuation-insensitive word tokens."""
    return [match.group(0).casefold() for match in TOKEN_RE.finditer(str(text or ""))]
