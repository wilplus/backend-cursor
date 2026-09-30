"""The golden set (founder 2026-09-30, L6; build plan ML-7, ML-10).

The founder judges moments on the research screen, one at a time, with
the same one question the coach answers. Each judgement is one row; a
surface's set is sealed once with the hash of its judgements, and the
evaluation reads the sealed set instead of the engineering seeds.

The pool is the moments coaches have already labelled blind, so a golden
moment always has human labels beside it; the founder never sees those
labels, nor a machine read, while judging (BLIND COACH holds for the
founder too). L3: a founder judgement is its own provenance, never a
coach label and never training data.
"""
from __future__ import annotations

import hashlib
from typing import Any, Optional

SURFACES = ("confidence",)
SET_SIZE = 50
VALUES = ("yes", "in_between", "no", "not_sure", "audio_unclear")


class GoldenRefusal(Exception):
    def __init__(self, message: str, code: str = "INVALID_INPUT", status: int = 400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def _check_surface(surface: Any) -> str:
    if surface not in SURFACES:
        raise GoldenRefusal(f"surface must be one of {', '.join(SURFACES)}")
    return str(surface)


def next_moment(database: Any, *, surface: str, judge: str) -> Optional[dict]:
    """The next unjudged moment for this judge: passage and a signed clip,
    nothing else. None when the pool is exhausted."""
    from services.snippet_audio_url import resolve_snippet_audio_url
    surface = _check_surface(surface)
    judged = {str(j.get("snippet_id")) for j in
              database.list_golden_judgements(surface=surface, judge=judge) or []}
    for row in database.get_confidence_label_corpus(limit=500) or []:
        snippet_id = str((row or {}).get("snippet_id") or "")
        if not snippet_id or snippet_id in judged:
            continue
        snippet = database.get_snippet_by_id(snippet_id, None)
        if not isinstance(snippet, dict):
            continue
        judged.add(snippet_id)
        return {
            "snippet_id": snippet_id,
            "take_session_id": snippet.get("session_id"),
            "passage": str(snippet.get("transcript") or ""),
            "audio_url": resolve_snippet_audio_url(snippet, database),
            "start_offset_ms": int(snippet.get("start_offset_ms") or 0),
            "duration_ms": int(snippet.get("duration_ms") or 0),
        }
    return None


def record(database: Any, *, surface: str, judge: str, body: Any) -> dict:
    surface = _check_surface(surface)
    fields = body if isinstance(body, dict) else {}
    snippet_id = str(fields.get("snippet_id") or "").strip()
    value = fields.get("value")
    if not snippet_id or value not in VALUES:
        raise GoldenRefusal("snippet_id and one of the five values are required")
    if database.get_golden_set(surface):
        raise GoldenRefusal("This set is sealed.", "SEALED", 409)
    database.insert_golden_judgement(
        surface=surface, snippet_id=snippet_id, judge_email=judge, value=str(value),
        take_session_id=str(fields.get("take_session_id") or "") or None)
    return {"judged": counts(database, surface=surface, judge=judge)}


def counts(database: Any, *, surface: str, judge: Optional[str] = None) -> dict:
    surface = _check_surface(surface)
    rows = database.list_golden_judgements(surface=surface, judge=judge) or []
    sealed = database.get_golden_set(surface)
    return {
        "surface": surface,
        "count": len(rows),
        "set_size": SET_SIZE,
        "sealed": (dict(sealed) if isinstance(sealed, dict) else None),
    }


def digest(rows: list[Any]) -> str:
    """sha256 over the sorted (snippet, value) lines: the same rows in any
    order seal to the same hash."""
    lines = sorted(f"{r.get('snippet_id')}:{r.get('value')}" for r in rows if isinstance(r, dict))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def seal(database: Any, *, surface: str, judge: str) -> dict:
    surface = _check_surface(surface)
    if database.get_golden_set(surface):
        raise GoldenRefusal("This set is already sealed.", "SEALED", 409)
    rows = database.list_golden_judgements(surface=surface, judge=judge) or []
    if len(rows) < SET_SIZE:
        raise GoldenRefusal(f"Judge {SET_SIZE} moments before sealing; {len(rows)} so far.",
                            "GOLDEN_SET_INCOMPLETE", 409)
    sealed = database.seal_golden_set(surface=surface, judge_email=judge,
                                      count=len(rows), sha256=digest(rows))
    return {"sealed": dict(sealed) if isinstance(sealed, dict) else None}
