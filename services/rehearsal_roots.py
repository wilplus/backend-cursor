"""Deterministic rehearsal roots for the complete Ideal Text roadmap.

Every paragraph contributes exactly one root.  An accepted orange span owns
the root; otherwise the paragraph's first five visible words are a neutral
navigation cue.  The fallback is deliberately never promoted to praise.
"""
from __future__ import annotations

import re
from typing import Any

from services.ideal_text_annotations import strip_for_diff


_ORANGE_RE = re.compile(r"\{\{orange:(.*?)\}\}", re.DOTALL)
_WORD_RE = re.compile(r"[^\W_]+(?:[’'-][^\W_]+)*", re.UNICODE)


def _first_words(value: Any, limit: int = 5) -> str:
    visible = strip_for_diff(value)
    words = _WORD_RE.findall(visible)
    return " ".join(words[:limit])


def rehearsal_root(paragraph: Any) -> dict[str, str]:
    """Return one honest root phrase and its visual provenance.

    ``flagship`` means the user accepted an orange anchor. ``neutral`` means
    navigation only.  The function never infers quality from ordinary text.
    """
    text = paragraph if isinstance(paragraph, str) else ""
    accepted = _ORANGE_RE.search(text)
    if accepted:
        phrase = _first_words(accepted.group(1))
        if phrase:
            return {"text": phrase, "type": "flagship"}
    return {"text": _first_words(text), "type": "neutral"}
