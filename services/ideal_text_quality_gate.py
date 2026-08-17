"""Deterministic final structural gate for a composed ideal text."""
from __future__ import annotations

from typing import Any


_MARKERS = ("[[moment:", "[[/moment]]", "{{orange:", "}}")


def prior_parts_text(parts: Any) -> str:
    rows = [r for r in (parts or []) if isinstance(r, dict)]
    rows.sort(key=lambda r: int(r.get("ord") or 0))
    return "\n\n".join((r.get("text") or "").strip() for r in rows
                         if (r.get("text") or "").strip())


def validate_composed_text(candidate: Any, prior_parts: Any) -> dict:
    """Return ``{ok, reasons}``; never repair or rewrite the candidate."""
    text = candidate if isinstance(candidate, str) else ""
    reasons = []
    if not text.strip():
        return {"ok": False, "reasons": ["empty"]}

    paragraphs = [p.strip() for p in text.split("\n\n")]
    if any(not p for p in paragraphs):
        reasons.append("empty_paragraph")
    if any(token in text for token in _MARKERS):
        reasons.append("marker_leak")
    if any(a.casefold() == b.casefold()
           for a, b in zip(paragraphs, paragraphs[1:])):
        reasons.append("adjacent_duplicate")

    rows = [r for r in (prior_parts or []) if isinstance(r, dict)]
    locked = [(r.get("text") or "").strip() for r in rows
              if r.get("locked") or r.get("locked_at")]
    cursor = 0
    for paragraph in locked:
        if not paragraph:
            continue
        at = text.find(paragraph, cursor)
        if at < 0:
            reasons.append("locked_text_changed")
            break
        cursor = at + len(paragraph)

    prior = prior_parts_text(rows)
    if prior:
        ratio = len(text.strip()) / max(1, len(prior.strip()))
        if ratio < 0.5:
            reasons.append("document_too_short")
        elif ratio > 1.75:
            reasons.append("document_too_long")

    locked_set = {p for p in locked if p}
    if any(len(p.split()) < 2 and p not in locked_set for p in paragraphs):
        reasons.append("orphan_paragraph")
    return {"ok": not reasons, "reasons": reasons}
