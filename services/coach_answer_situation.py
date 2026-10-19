"""Each answer keeps what the coach saw (0481; founder 2026-10-19, decisions
log N79).

When a coach answers a speaker's moment (a first answer, a changed one, or
a new video on an answer already given) or saves their word for a Take,
this module freezes the situation they answered in, once per answer, in
``coach_answer_situations``:

  * the answer's own time: the resolver's ``resolved_at``, passed through
    untouched, so a replaced answer finds its history row (0446); for a
    Take word, the word row's ``updated_at``;
  * the moment's kind (``answer_kind``, else ``kind``) and the pattern the
    coach named on the Home screen, when they named one;
  * the passage: the clip's transcript, uncut, and its slide; for a Take
    word, every clip of the Take joined in order;
  * the coach's current diagnosis (0445), by id and copied (the error id or
    the coach-named error, and the label the coach picked), so the error
    type stays with the answer when the coach's account goes (N79); for a
    Take word, every moment of the Take this coach diagnosed;
  * the Ideal Text pinned to the answered Take: the newest snapshot made
    from it, never the speaker's current head, which may already be a
    later Take's (CLAUDE.md rule 5).

Never for a coach answering their own Take (L3). It copies what the
database already holds and calls no provider. Best effort and never in the
coach's way: a read that fails leaves its field empty, a write that fails
is logged, and the answer stands either way.

CAPTURE ONLY. No training, release, golden or promotion reader reads the
table, and it is in no speaker or coach payload. A diagnosis is still
"never a training label" (0445, services/coach_diagnosis.py) until the
founder's single privacy update names this table among the new training
uses. Every row is purged with its Take (services/data_purge_registry.py).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

_log = logging.getLogger(__name__)

#: A row frozen when the answer was given (a reviewed catch-up of past
#: answers would write 'reconstructed'; nothing here does).
AT_ANSWER = "at_answer"


def freeze_answer(database: Any, *, request: Any, resolved: Any, coach_id: Any,
                  chosen_pattern_key: Any = None) -> Optional[dict]:
    """The situation of one moment's answer. ``request`` is the row as it
    was before this save and ``resolved`` the resolver's row after it. No
    row when this save gave no new answer (the same answer again, or only
    its share: the resolver kept ``resolved_at``) or the coach owns the
    Take. The written row, or None. Never raises."""
    try:
        row = _answer_row(database, request, resolved, coach_id, chosen_pattern_key)
        return _write(database, row) if row else None
    except Exception as e:  # noqa: BLE001 -- the answer stands
        _log.warning("answer situation not kept request=%s: %s",
                     (resolved or {}).get("id") if isinstance(resolved, dict) else None,
                     e, exc_info=True)
        return None


def freeze_take_word(database: Any, *, word_row: Any, coach_id: Any) -> Optional[dict]:
    """The situation of one Take-word save: every clip of the Take, the
    coach's diagnoses on its moments and the Take's Ideal Text. No row on
    the coach's own Take. The written row, or None. Never raises."""
    try:
        row = _take_word_row(database, word_row, coach_id)
        return _write(database, row) if row else None
    except Exception as e:  # noqa: BLE001 -- the word is saved either way
        _log.warning("take word situation not kept take=%s: %s",
                     (word_row or {}).get("take_session_id") if isinstance(word_row, dict)
                     else None, e, exc_info=True)
        return None


def _answer_row(database: Any, request: Any, resolved: Any, coach_id: Any,
                chosen: Any) -> Optional[dict]:
    if not isinstance(request, dict) or not isinstance(resolved, dict):
        return None
    if getattr(database, "insert_coach_answer_situation", None) is None:
        return None
    answered_at = resolved.get("resolved_at")
    if not resolved.get("id") or not resolved.get("resolution") or not answered_at:
        return None
    if str(answered_at) == str(request.get("resolved_at") or ""):
        return None  # no new answer: the same again, or only its share
    row = {**request, **resolved}
    coach = str(coach_id or "").strip()
    if not coach or coach == str(row.get("owner_user_id") or "").strip():
        return None  # an owner's answer is never kept (L3)
    take = str(row.get("take_session_id") or "")
    snippet = str(row.get("snippet_id") or "")
    if not take or not snippet:
        return None
    clips = _clips(database, take, snippet)
    clip = clips[0] if clips else {}
    return {
        "take_session_id": take, "snippet_id": snippet,
        "request_id": str(resolved["id"]), "take_word_id": None,
        "answered_at": answered_at,
        "kind": str(row.get("answer_kind") or row.get("kind") or "") or None,
        "pattern_key": _named(chosen),
        "passage_text": clip.get("passage"), "slide_index": clip.get("slide_index"),
        **_diagnosis_fields(_diagnoses(database, take, coach, snippet), clips),
        **_ideal_text(database, take),
        "captured": AT_ANSWER,
    }


def _take_word_row(database: Any, word_row: Any, coach_id: Any) -> Optional[dict]:
    if not isinstance(word_row, dict) or not word_row.get("id"):
        return None
    if getattr(database, "insert_coach_answer_situation", None) is None:
        return None
    take = str(word_row.get("take_session_id") or "")
    coach = str(coach_id or "").strip()
    answered_at = word_row.get("updated_at")
    if not take or not coach or not answered_at:
        return None
    session = database.v2_get_session_by_id(take) or {}
    if coach == str(session.get("user_id") or "").strip():
        return None  # an owner's word on their own Take is never kept (L3)
    clips = _clips(database, take)
    passage = " ".join(c["passage"] for c in clips if c.get("passage"))
    return {
        "take_session_id": take, "snippet_id": None, "request_id": None,
        "take_word_id": str(word_row["id"]), "answered_at": answered_at,
        "kind": None, "pattern_key": None,
        "passage_text": passage or None, "slide_index": None,
        **_diagnosis_fields(_diagnoses(database, take, coach), clips),
        **_ideal_text(database, take),
        "captured": AT_ANSWER,
    }


def _named(chosen: Any) -> Optional[str]:
    """The pattern the coach named on the Home screen: one token, as the
    filing reads it (exercise_coach_requests._pattern_key); None when they
    named none. Never the fallback the filing derives from what was spotted:
    that is on the request row already, and it is not the coach's choice."""
    if isinstance(chosen, str) and chosen.strip() and not any(c.isspace() for c in chosen.strip()):
        return chosen.strip()
    return None


def _clips(database: Any, take: str, snippet: Optional[str] = None) -> list[dict]:
    """The Take's clips (or the one clip) in start order, as
    {id, passage, slide_index}; the passage is the transcript with its
    whitespace collapsed, never cut. [] when unreadable."""
    reader = getattr(database, "get_snippet_passages", None)
    if reader is None:
        return []
    try:
        rows = reader(take, snippet_id=snippet) if snippet else reader(take)
    except Exception as e:  # noqa: BLE001 -- the passage stays empty
        _log.info("situation passage unread take=%s: %s", take, e)
        return []
    out: list[dict] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or (snippet and str(row.get("id")) != snippet):
            continue
        out.append({"id": str(row.get("id") or ""),
                    "passage": " ".join(str(row.get("transcript") or "").split()) or None,
                    "slide_index": row.get("slide_index")})
    return out


def _diagnoses(database: Any, take: str, coach: str,
               snippet: Optional[str] = None) -> list[dict]:
    """This coach's current diagnoses (one moment's, or the Take's), with
    their labels. [] when unreadable."""
    reader = getattr(database, "list_current_coach_moment_diagnoses", None)
    if reader is None:
        return []
    try:
        rows = reader(take_session_id=take, coach_id=coach, snippet_id=snippet)
    except Exception as e:  # noqa: BLE001 -- the diagnosis stays empty
        _log.info("situation diagnosis unread take=%s: %s", take, e)
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("id")] \
        if isinstance(rows, list) else []


def _diagnosis_fields(rows: list[dict], clips: list[dict]) -> dict:
    """{diagnosis_ids, diagnoses}: by reference, and copied so the error
    type outlives the coach's account (N79). In the Take's clip order."""
    order = {c["id"]: i for i, c in enumerate(clips)}
    rows = sorted(rows, key=lambda r: (order.get(str(r.get("snippet_id")), len(order)),
                                       str(r.get("snippet_id") or "")))
    copies = [{"diagnosis_id": str(r["id"]),
               "snippet_id": str(r.get("snippet_id") or "") or None,
               "kind": r.get("kind"),
               "error_id": r.get("error_id") or None,
               "named_error_id": str(r["named_error_id"]) if r.get("named_error_id") else None,
               "label": r.get("label") or None} for r in rows]
    return {"diagnosis_ids": [c["diagnosis_id"] for c in copies], "diagnoses": copies}


def _ideal_text(database: Any, take: str) -> dict:
    """The Ideal Text snapshot made from the answered Take, by id and
    version; both None when it has none or it is unreadable."""
    empty = {"ideal_text_snapshot_id": None, "ideal_text_version": None}
    reader = getattr(database, "get_take_ideal_text_snapshot", None)
    if reader is None:
        return empty
    try:
        snapshot = reader(take)
    except Exception as e:  # noqa: BLE001 -- the Ideal Text stays empty
        _log.info("situation ideal text unread take=%s: %s", take, e)
        return empty
    if not isinstance(snapshot, dict) or not snapshot.get("id"):
        return empty
    version = snapshot.get("version")
    return {"ideal_text_snapshot_id": str(snapshot["id"]),
            "ideal_text_version": version if isinstance(version, int)
            and not isinstance(version, bool) else None}


def _write(database: Any, row: dict) -> Optional[dict]:
    """One insert; an answer already kept is ignored by its key."""
    written = database.insert_coach_answer_situation(**row)
    return written if isinstance(written, dict) else None
