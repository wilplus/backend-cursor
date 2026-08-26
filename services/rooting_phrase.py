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


def validate_rooting_phrase(
    part_text: Any, phrase: Any, start: Any, end: Any,
) -> Optional[dict]:
    text = part_text if isinstance(part_text, str) else ""
    if (not isinstance(phrase, str) or not phrase
            or not isinstance(start, int) or isinstance(start, bool)
            or not isinstance(end, int) or isinstance(end, bool)
            or start < 0 or end <= start or end > len(text)
            or text[start:end] != phrase
            or _MARKER_RE.search(phrase)):
        return None
    return {"text": phrase, "start": start, "end": end}
