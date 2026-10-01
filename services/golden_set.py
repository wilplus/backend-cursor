"""The golden set (founder 2026-09-30, L6; build plan ML-7, ML-10).

The founder judges moments on the research screen, one at a time. Each
judgement is one row; a surface's set is sealed once with the hash of its
judgements, and the evaluation reads the sealed set instead of the
engineering seeds (ML-10: it refuses an unsealed set).

Two kinds of surface, one instrument each:

  * ``confidence``: the pool is the moments coaches have already labelled
    blind, judged with the same one question the coach answers. The
    founder never sees those labels, nor a machine read (BLIND COACH holds
    for the founder too).
  * the three coach-answer surfaces (``praise_line``, ``clearer_version``,
    ``exercise_script``; ML-10): the pool is the (draft, final) pairs that
    still carry their passage. The founder sees the passage and the coach's
    final — never the machine's draft — and answers one question: is this
    the right answer for this passage? Yes, no, not sure. A "yes" makes the
    coach's final the reference the evaluation scores against; the row
    keeps the passage and the final so the set stays what was sealed, and
    names the owner so erasure reaches it.

L3: a founder judgement is its own provenance, never a coach label and
never training data.
"""
from __future__ import annotations

import hashlib
from typing import Any, Optional

#: The confidence surface judges clips; the pair surfaces judge texts.
CLIP_SURFACES = ("confidence",)
PAIR_SURFACES = ("praise_line", "clearer_version", "exercise_script")
SURFACES = CLIP_SURFACES + PAIR_SURFACES
SET_SIZE = 50
VALUES = ("yes", "in_between", "no", "not_sure", "audio_unclear")
#: The pair surfaces' one question takes three of the five answers.
PAIR_VALUES = ("yes", "no", "not_sure")


class GoldenRefusal(Exception):
    def __init__(self, message: str, code: str = "INVALID_INPUT", status: int = 400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def _check_surface(surface: Any) -> str:
    if surface not in SURFACES:
        raise GoldenRefusal(f"surface must be one of {', '.join(SURFACES)}")
    return str(surface)


def is_pair_surface(surface: Any) -> bool:
    return surface in PAIR_SURFACES


def _judged_ids(database: Any, *, surface: str, judge: str) -> set[str]:
    return {str(j.get("snippet_id")) for j in
            database.list_golden_judgements(surface=surface, judge=judge) or []}


def _next_clip(database: Any, *, surface: str, judged: set[str]) -> Optional[dict]:
    from services.snippet_audio_url import resolve_snippet_audio_url
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


def _next_pair(database: Any, *, surface: str, judged: set[str]) -> Optional[dict]:
    """The next pair with a passage. The draft never leaves this function:
    the founder judges the coach's answer, not the machine's."""
    lister = getattr(database, "list_golden_pair_pool", None)
    if lister is None:
        return None
    for pair in lister(surface, limit=500) or []:
        pair_id = str((pair or {}).get("id") or "")
        passage = " ".join(str((pair or {}).get("passage_text") or "").split())
        final = str((pair or {}).get("final_text") or "").strip()
        if not pair_id or pair_id in judged or not passage or not final:
            continue
        judged.add(pair_id)
        return {
            "snippet_id": pair_id,
            "take_session_id": pair.get("take_session_id"),
            "passage": passage,
            "final": final,
            "prompt_context": pair.get("prompt_context") or {},
            "owner_principal_id": pair.get("owner_principal_id"),
            "audio_url": None, "start_offset_ms": 0, "duration_ms": 0,
        }
    return None


def next_moment(database: Any, *, surface: str, judge: str) -> Optional[dict]:
    """The next unjudged moment for this judge: a passage and a signed clip
    (confidence) or a passage and the coach's final (a pair surface),
    nothing else. None when the pool is exhausted."""
    surface = _check_surface(surface)
    judged = _judged_ids(database, surface=surface, judge=judge)
    if is_pair_surface(surface):
        return _next_pair(database, surface=surface, judged=judged)
    return _next_clip(database, surface=surface, judged=judged)


def record(database: Any, *, surface: str, judge: str, body: Any) -> dict:
    surface = _check_surface(surface)
    fields = body if isinstance(body, dict) else {}
    snippet_id = str(fields.get("snippet_id") or "").strip()
    value = fields.get("value")
    allowed = PAIR_VALUES if is_pair_surface(surface) else VALUES
    if not snippet_id or value not in allowed:
        raise GoldenRefusal(f"snippet_id and one of {', '.join(allowed)} are required")
    sealed = database.get_golden_set(surface)
    if sealed and _still_sealed(database, surface=surface, judge=judge, sealed=sealed):
        raise GoldenRefusal("This set is sealed.", "SEALED", 409)
    extra: dict[str, Any] = {}
    if is_pair_surface(surface):
        # The text the founder judged, kept with the judgement: the sealed
        # set must be what was sealed even after the pair's Take is gone.
        moment = _pair_moment(database, surface=surface, pair_id=snippet_id)
        if moment is None:
            raise GoldenRefusal("That pair no longer has a passage to judge.", "NOT_FOUND", 404)
        extra = {"passage": moment["passage"], "reference": moment["final"],
                 "prompt_context": moment.get("prompt_context") or {},
                 "owner_principal_id": moment.get("owner_principal_id")}
    database.insert_golden_judgement(
        surface=surface, snippet_id=snippet_id, judge_email=judge, value=str(value),
        take_session_id=str(fields.get("take_session_id") or "") or None, **extra)
    return {"judged": counts(database, surface=surface, judge=judge)}


def _pair_moment(database: Any, *, surface: str, pair_id: str) -> Optional[dict]:
    reader = getattr(database, "get_feedback_pair", None)
    pair = reader(pair_id) if reader else None
    if not isinstance(pair, dict) or str(pair.get("surface")) != surface:
        return None
    passage = " ".join(str(pair.get("passage_text") or "").split())
    final = str(pair.get("final_text") or "").strip()
    if not passage or not final:
        return None
    return {"passage": passage, "final": final,
            "prompt_context": pair.get("prompt_context") or {},
            "owner_principal_id": pair.get("owner_principal_id")}


def counts(database: Any, *, surface: str, judge: Optional[str] = None) -> dict:
    surface = _check_surface(surface)
    rows = database.list_golden_judgements(surface=surface, judge=judge) or []
    sealed = database.get_golden_set(surface)
    out = {
        "surface": surface,
        "kind": "pair" if is_pair_surface(surface) else "clip",
        "count": len(rows),
        "set_size": SET_SIZE,
        "sealed": (dict(sealed) if isinstance(sealed, dict) else None),
    }
    if isinstance(sealed, dict) and rows:
        # Erasure can take a moment out of a sealed set; the evaluation
        # refuses such a set and the founder re-seals it.
        out["sealed_intact"] = digest(rows) == str(sealed.get("sha256") or "")
    return out


def digest(rows: list[Any]) -> str:
    """sha256 over the sorted (snippet, value) lines: the same rows in any
    order seal to the same hash."""
    lines = sorted(f"{r.get('snippet_id')}:{r.get('value')}" for r in rows if isinstance(r, dict))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _still_sealed(database: Any, *, surface: str, judge: Optional[str], sealed: dict) -> bool:
    rows = database.list_golden_judgements(surface=surface, judge=None) or []
    return digest(rows) == str(sealed.get("sha256") or "")


def seal(database: Any, *, surface: str, judge: str) -> dict:
    surface = _check_surface(surface)
    sealed = database.get_golden_set(surface)
    if sealed and _still_sealed(database, surface=surface, judge=judge, sealed=sealed):
        raise GoldenRefusal("This set is already sealed.", "SEALED", 409)
    rows = database.list_golden_judgements(surface=surface, judge=judge) or []
    if len(rows) < SET_SIZE:
        raise GoldenRefusal(f"Judge {SET_SIZE} moments before sealing; {len(rows)} so far.",
                            "GOLDEN_SET_INCOMPLETE", 409)
    sealed_row = database.seal_golden_set(surface=surface, judge_email=judge,
                                          count=len(rows), sha256=digest(rows))
    return {"sealed": dict(sealed_row) if isinstance(sealed_row, dict) else None}


def sealed_rows(database: Any, *, surface: str) -> list[dict]:
    """The sealed set's rows, verified against its hash: what the
    evaluation reads (ML-10). Raises GoldenRefusal when the set is
    unsealed or no longer what was sealed."""
    surface = _check_surface(surface)
    sealed = database.get_golden_set(surface)
    if not isinstance(sealed, dict):
        raise GoldenRefusal(f"The golden set for {surface} is not sealed.",
                            "GOLDEN_SET_UNSEALED", 409)
    rows = [r for r in (database.list_golden_judgements(surface=surface, judge=None) or [])
            if isinstance(r, dict)]
    if digest(rows) != str(sealed.get("sha256") or ""):
        raise GoldenRefusal(f"The golden set for {surface} is no longer what was sealed; "
                            "re-seal it.", "GOLDEN_SET_CHANGED", 409)
    return rows
