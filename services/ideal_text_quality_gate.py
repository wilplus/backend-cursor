"""Deterministic final structural gate for a composed ideal text."""
from __future__ import annotations

from typing import Any


_MARKERS = ("[[moment:", "[[/moment]]", "{{orange:", "}}")


def prior_parts_text(parts: Any) -> str:
    rows = [r for r in (parts or []) if isinstance(r, dict)]
    rows.sort(key=lambda r: int(r.get("ord") or 0))
    return "\n\n".join((r.get("text") or "").strip() for r in rows
                         if (r.get("text") or "").strip())


def _paragraph_reasons(text: str, paragraphs: list) -> list:
    """Blank paragraphs, leaked markers, and a paragraph repeated back to
    back (case-insensitively)."""
    reasons = []
    if any(not p for p in paragraphs):
        reasons.append("empty_paragraph")
    if any(token in text for token in _MARKERS):
        reasons.append("marker_leak")
    if any(a.casefold() == b.casefold()
           for a, b in zip(paragraphs, paragraphs[1:])):
        reasons.append("adjacent_duplicate")
    return reasons


def _locked_texts(rows: list) -> list:
    return [(r.get("text") or "").strip() for r in rows
            if r.get("locked") or r.get("locked_at")]


def _locks_in_order(text: str, locked: list) -> bool:
    """Every locked paragraph still appears verbatim, in its order."""
    cursor = 0
    for paragraph in locked:
        if not paragraph:
            continue
        at = text.find(paragraph, cursor)
        if at < 0:
            return False
        cursor = at + len(paragraph)
    return True


def _length_reason(text: str, rows: list) -> str | None:
    """The composed text may not shrink below half, or grow past 1.75×, of
    the stored parts."""
    prior = prior_parts_text(rows)
    if not prior:
        return None
    ratio = len(text.strip()) / max(1, len(prior.strip()))
    if ratio < 0.5:
        return "document_too_short"
    if ratio > 1.75:
        return "document_too_long"
    return None


def validate_composed_text(candidate: Any, prior_parts: Any) -> dict:
    """Return ``{ok, reasons}``; never repair or rewrite the candidate."""
    text = candidate if isinstance(candidate, str) else ""
    if not text.strip():
        return {"ok": False, "reasons": ["empty"]}

    paragraphs = [p.strip() for p in text.split("\n\n")]
    reasons = _paragraph_reasons(text, paragraphs)

    rows = [r for r in (prior_parts or []) if isinstance(r, dict)]
    locked = _locked_texts(rows)
    if not _locks_in_order(text, locked):
        reasons.append("locked_text_changed")

    length = _length_reason(text, rows)
    if length:
        reasons.append(length)

    locked_set = {p for p in locked if p}
    if any(len(p.split()) < 2 and p not in locked_set for p in paragraphs):
        reasons.append("orphan_paragraph")
    return {"ok": not reasons, "reasons": reasons}
