"""Each answer keeps what the coach saw (0481; founder 2026-10-19, decisions
log N79).

When a coach answers a speaker's moment (a first answer, a changed one, or
a new video on an answer already given) or saves their word for a Take,
this module freezes the situation they answered in, once per answer, in
``coach_answer_situations``:

  * the answer's own time: the resolver's ``resolved_at``, passed through
    untouched, so a replaced answer finds its history row (0446); for a
    Take word, the word row's ``updated_at`` (one row per save; the words
    it describes are the live row's, or the lowest-numbered
    coach_take_word_versions row of that word whose ``updated_at`` is at or
    after it, 0478: a re-draft bumps ``updated_at`` too, so it is no
    equality key);
  * the moment's kind (``answer_kind``, else ``kind``) and the pattern the
    coach named on the Home screen, when they named one;
  * the passage: the clip's transcript, uncut, and its slide (the coach's
    slide correction first, as the document reads it, else the cutter's);
    for a Take word, every clip of the Take and of its mid-take re-reads,
    in the order the coach's packet folds them, joined;
  * the coach's current diagnosis (0445), by id and copied (the error id or
    the coach-named error, and the label the coach picked), so the error
    type stays with the answer when the coach's account goes (N79); for a
    Take word, every moment of the Take and its re-reads this coach
    diagnosed;
  * the Ideal Text pinned to the answered Take: the newest snapshot made
    from it (for a moment from a re-read, from the spoken Take it is folded
    into, the only Take a snapshot is ever made from), never the speaker's
    current head, which may already be a later Take's (CLAUDE.md rule 5).

Never for a coach answering their own Take (L3). It copies what the
database already holds and calls no provider. It runs off the coach's
request in a daemon thread, so its reads never hold the save or the
speaker's message. Best effort and never in the coach's way: a read that
fails leaves its field empty, a write that fails is logged, and the answer
stands either way.

CAPTURE ONLY. No training, release, golden or promotion reader reads the
table, and it is in no speaker or coach payload. A diagnosis is still
"never a training label" (0445, services/coach_diagnosis.py) until the
founder's single privacy update names this table among the new training
uses. Every row is purged with its Take (services/data_purge_registry.py).
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Optional

_log = logging.getLogger(__name__)

#: A row frozen when the answer was given (a reviewed catch-up of past
#: answers would write 'reconstructed'; nothing here does).
AT_ANSWER = "at_answer"

#: The thread a situation is frozen on, off the coach's request.
THREAD_NAME = "coach-answer-situation"


def freeze_answer_in_background(database: Any, *, request: Any, resolved: Any,
                                coach_id: Any, chosen_pattern_key: Any = None) -> None:
    """``freeze_answer``, off the coach's request: its reads never hold the
    save or the speaker's message. The rows are copied first, so nothing the
    save does next changes what is kept. Never raises."""
    _in_background(freeze_answer, database,
                   request=dict(request) if isinstance(request, dict) else request,
                   resolved=dict(resolved) if isinstance(resolved, dict) else resolved,
                   coach_id=coach_id, chosen_pattern_key=chosen_pattern_key)


def freeze_take_word_in_background(database: Any, *, word_row: Any, coach_id: Any) -> None:
    """``freeze_take_word``, off the coach's request. Never raises."""
    _in_background(freeze_take_word, database,
                   word_row=dict(word_row) if isinstance(word_row, dict) else word_row,
                   coach_id=coach_id)


def _in_background(target: Any, database: Any, **kwargs: Any) -> None:
    try:
        threading.Thread(target=target, args=(database,), kwargs=kwargs,
                         name=THREAD_NAME, daemon=True).start()
    except Exception as e:  # noqa: BLE001 -- the answer stands
        _log.warning("answer situation not started: %s", e, exc_info=True)


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
    """The situation of one Take-word save: every clip of the Take and its
    re-reads, the coach's diagnoses on their moments and the Take's Ideal
    Text. No row on the coach's own Take. The written row, or None. Never
    raises."""
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
        "passage_text": clip.get("passage"),
        "slide_index": _slide(database, take, snippet, clip.get("slide_index")),
        **_diagnosis_fields(_diagnoses(database, take, coach, snippet), clips),
        **_ideal_text(database, take, _session(database, take)),
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
    # Unguarded: when the owner cannot be read, nothing is kept (L3).
    session = database.v2_get_session_by_id(take) or {}
    if coach == str(session.get("user_id") or "").strip():
        return None  # an owner's word on their own Take is never kept (L3)
    # The coach's packet is the Take with its re-reads folded in (founder
    # 2026-07-16), so the word is about all of it, in that order.
    takes = [take] + _re_reads(database, take, session)
    clips = [c for sid in takes for c in _clips(database, sid)]
    passage = " ".join(c["passage"] for c in clips if c.get("passage"))
    diagnoses = [d for sid in takes for d in _diagnoses(database, sid, coach)]
    return {
        "take_session_id": take, "snippet_id": None, "request_id": None,
        "take_word_id": str(word_row["id"]), "answered_at": answered_at,
        "kind": None, "pattern_key": None,
        "passage_text": passage or None, "slide_index": None,
        **_diagnosis_fields(diagnoses, clips),
        **_ideal_text(database, take, session),
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


def _session(database: Any, take: str) -> dict:
    """The answered session's row; {} when unreadable (its Ideal Text then
    stays empty)."""
    reader = getattr(database, "v2_get_session_by_id", None)
    if reader is None:
        return {}
    try:
        session = reader(take)
    except Exception as e:  # noqa: BLE001 -- the Ideal Text stays empty
        _log.info("situation session unread take=%s: %s", take, e)
        return {}
    return session if isinstance(session, dict) else {}


def _is_re_read(session: dict) -> bool:
    return session.get("recording_kind") == "read" or bool(session.get("paired_session_id"))


def _re_reads(database: Any, take: str, session: dict) -> list[str]:
    """A spoken Take's mid-take re-reads, oldest first (the fold order of
    the coach's packet); [] for a re-read itself or when unreadable."""
    reader = getattr(getattr(database, "takes", None), "get_read_sessions_for", None)
    if reader is None or _is_re_read(session):
        return []
    try:
        rows = reader(take)
    except Exception as e:  # noqa: BLE001 -- the Take alone is kept
        _log.info("situation re-reads unread take=%s: %s", take, e)
        return []
    return [str(r["id"]) for r in rows if isinstance(r, dict) and r.get("id")] \
        if isinstance(rows, list) else []


def _slide(database: Any, take: str, snippet: str, cut: Any) -> Optional[int]:
    """The clip's slide as the document reads it (transcript_document.
    _slide_of): the coach's latest correction when it is a slide, else (none,
    or one withdrawn as None) the cutter's own."""
    reader = getattr(database, "get_snippet_slide_corrections", None)
    fixes: Any = {}
    if reader is not None:
        try:
            fixes = reader(take)
        except Exception as e:  # noqa: BLE001 -- the cutter's slide stands
            _log.info("situation slide corrections unread take=%s: %s", take, e)
    fix = fixes.get(snippet) if isinstance(fixes, dict) else None
    if isinstance(fix, int) and not isinstance(fix, bool):
        return fix
    return cut if isinstance(cut, int) and not isinstance(cut, bool) else None


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


def _ideal_text(database: Any, take: str, session: dict) -> dict:
    """The Ideal Text snapshot made from the answered Take, by id and
    version. A re-read is never a snapshot's source (ideal_text_core_snapshot.
    _completed_spoken), so a moment from one is pinned to the spoken Take it
    is folded into. Looked up within the Take's arc, which the snapshot
    table's index serves. Both None when there is none or it is unreadable."""
    empty = {"ideal_text_snapshot_id": None, "ideal_text_version": None}
    reader = getattr(database, "get_take_ideal_text_snapshot", None)
    if reader is None:
        return empty
    spoken, arc = take, session.get("arc_id")
    if _is_re_read(session):
        spoken = str(session.get("paired_session_id") or "")
        if spoken and not arc:
            arc = _session(database, spoken).get("arc_id")
    if not spoken or not arc:
        return empty
    try:
        snapshot = reader(spoken, arc_id=str(arc))
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
