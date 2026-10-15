"""Exact-span rooting phrase proposals for locked Ideal Text paragraphs."""
from __future__ import annotations

import re
from typing import Any, Optional


_WORD_RE = re.compile(r"[^\W_]+(?:[’'-][^\W_]+)*", re.UNICODE)
_MARKER_RE = re.compile(r"\{\{orange:|\}\}|\*\*|==|\[\[[^:\]]+:|\]\]")
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for",
    "from", "i", "if", "in", "is", "it", "of", "on", "or", "so",
    "that", "the", "this", "to", "was", "we", "were", "with", "you",
    "your",
}


def _alignment_mask(text: str) -> str:
    """Hide marker grammar with same-length spaces so offsets stay exact."""
    return _MARKER_RE.sub(lambda match: " " * len(match.group(0)), text)


def propose_rooting_phrase(value: Any) -> Optional[dict]:
    """Strongest short exact word window, never generated or paraphrased."""
    text = value if isinstance(value, str) else ""
    if not text.strip():
        return None
    visible = _alignment_mask(text)
    words = list(_WORD_RE.finditer(visible))
    if not words:
        return None
    best: Optional[tuple[tuple, dict]] = None
    max_width = min(7, len(words))
    for width in range(2 if len(words) >= 2 else 1, max_width + 1):
        for at in range(0, len(words) - width + 1):
            chosen = words[at:at + width]
            start, end = chosen[0].start(), chosen[-1].end()
            phrase = text[start:end]
            # Root metadata is literal visible words, never marker grammar.
            if _MARKER_RE.search(phrase):
                continue
            tokens = [match.group(0).casefold() for match in chosen]
            content = sum(1 for token in tokens
                          if token not in _STOP and len(token) >= 4)
            distinctive = sum(min(len(token), 10) for token in tokens
                              if token not in _STOP)
            sentence_edge = int(
                start == 0 or text[max(0, start - 2):start].strip(" \n")
                in (".", "!", "?")
            )
            # Prefer a meaningful compact phrase. Earlier position is only the
            # final stable tie-break, never the selection rule itself.
            rank = (-content, -distinctive, abs(width - 5), -sentence_edge,
                    start)
            row = {"text": phrase, "start": start, "end": end}
            if best is None or rank < best[0]:
                best = (rank, row)
    if best is not None:
        return best[1]
    # Marker-heavy legacy paragraph: one exact visible word is still honest.
    first = words[0]
    return {"text": text[first.start():first.end()],
            "start": first.start(), "end": first.end()}


def _scattered(text: str, phrase: str, start: Any, end: Any) -> Optional[dict]:
    """Words picked apart (founder 2026-10-15): each piece is exact words of
    the paragraph, in the order said, and there is no single span."""
    from services.slide_helper_words import phrase_in_version, within_cap
    if start is not None or end is not None or _MARKER_RE.search(phrase):
        return None
    words = phrase_in_version(phrase, [_alignment_mask(text)])
    if words is None or not within_cap(words):
        return None
    return {"text": words, "start": None, "end": None}


def validate_rooting_phrase(
    part_text: Any, phrase: Any, start: Any, end: Any,
) -> Optional[dict]:
    text = part_text if isinstance(part_text, str) else ""
    from services.slide_helper_words import PIECE_SEP
    if isinstance(phrase, str) and PIECE_SEP in phrase:
        return _scattered(text, phrase, start, end)
    if (not isinstance(phrase, str) or not phrase
            or not isinstance(start, int) or isinstance(start, bool)
            or not isinstance(end, int) or isinstance(end, bool)
            or start < 0 or end <= start or end > len(text)
            or text[start:end] != phrase
            or _MARKER_RE.search(phrase)):
        return None
    # The eight-word cap on the server (B3; F1 Repair Plan Phase 5).
    from services.slide_helper_words import within_cap
    if not within_cap(phrase):
        return None
    return {"text": phrase, "start": start, "end": end}
