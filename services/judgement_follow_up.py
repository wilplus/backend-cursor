"""What follows the speaker's judgement of a moment: the follow-up matrix
(founder 2026-09-29, contract 24f as amended, 35g-2).

A JUDGEMENT IS ALWAYS ANSWERED. The speaker's answer, crossed with how the
machine read the same clip, decides two things:

  * what shows NOW: praise or a rewrite (the Manager's anchored notes,
    where it found one), the library video matched to the clip, or nothing;
  * under which KIND the bookmark reaches the coach: an error the detectors
    named, praise, a rewrite, or an ambiguity (the speaker and the machine
    disagree). Every answer but Audio unclear goes to the coach. The coach
    records a video for errors by default and may for the rest; a shared
    video rides the moment on the next read.

The matrix, as the founder agreed it:

    answer       read confident     read weak, fired     read weak, not fired
    Yes          praise · praise    nothing · ambiguity  nothing · ambiguity
    In-between   praise · praise    video · error        rewrite · rewrite
    No           praise · ambiguity video · error        rewrite · rewrite
    Not sure     praise · ambiguity video · ambiguity    rewrite · ambiguity
    Audio unclear  nothing, no request

"video" is the library exercise matched to the clip, or the coach request
alone when the library has none (the sentence "Your coach is working on
your exercise", errors only). A read the machine could not make is treated
as weak with nothing fired for what shows, and reaches the coach as an
ambiguity. The read chooses and is never surfaced (AC-9); praise and
rewrites show only where an evidence-backed one exists (L2).

This runs when the answer is SAVED (the feedback-response route), because
the answer decides it. The request row is insert-once per moment.

PHASE 2 OF THE AFTER-PRACTICE PATHS (founder 2026-10-01, F1; dark behind
Config.JUDGEMENT_AFTER_FEEDBACK_ENABLED): "Opening a bookmark never asks for
a judgment first. The machine's read chooses the feedback. The speaker
judges themselves after it: on a confident moment right after the praise,
on a moment that needed work after each practice attempt. Helper words open
on Yes or In-between of that judgment." Under the switch the request rises
when the moment OPENS (`follow_up_for_open`, migration 0408), under the
machine's kind, and the later judgement sets its `answer_kind` from the
same matrix; a practice judgement that disagrees with the machine's read of
that attempt makes it an ambiguity (`practice_judgement`). Off, every line
above holds exactly. One switch, both flows side by side until the cutover.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

_log = logging.getLogger(__name__)

#: The trace lane written on a request raised at judgement time.
JUDGEMENT_LANE = "v3_judgement"

ANSWERS = ("yes", "in_between", "no", "not_sure", "audio_unclear")
KINDS = ("error", "praise", "rewrite", "ambiguity")


def judgement_after_feedback_enabled() -> bool:
    """Phase 2 of the after-practice paths (founder 2026-10-01, F1), dark."""
    from config import Config
    return bool(getattr(Config, "JUDGEMENT_AFTER_FEEDBACK_ENABLED", False))


def decide_at_open(read: str, fired: bool,
                   matched: bool) -> tuple[str, Optional[str]]:
    """F1: the machine's read chooses the feedback when the bookmark opens,
    before any judgement. (what shows now, the kind the request rises under)

        read confident               praise                     · praise
        read weak, a problem fired   exercise (the ladder) or
                                     the coach alone            · error
        read weak, nothing fired     rewrite (29b), where the
                                     Manager found one          · rewrite
        no read                      rewrite where one exists,
                                     else the plain moment      · nothing

    A clip the machine could not read raises nothing at the open: there is
    no read to disagree with, and poor audio is not the coach's errand.
    """
    if read == "confident":
        return "praise", "praise"
    if read == "weak" and fired:
        return ("exercise" if matched else "coach_request"), "error"
    if read == "weak":
        return "rewrite", "rewrite"
    return "rewrite", None


def answer_kind_for(answer: Any, read: str, fired: bool) -> Optional[str]:
    """The matrix's kind for a judgement given AFTER the feedback: the same
    cells as `decide`, read for the kind alone."""
    return decide(answer, read, fired, True)[1]


def practice_disagrees(answer: Any, machine_decision: Any) -> bool:
    """A practice judgement that disagrees with the machine's read of that
    same attempt reaches the coach as an ambiguity (Phase 2). The attempt's
    machine leg is its `machine_confidence_decision` (yes or no, never
    shown); a missing leg disagrees with nothing."""
    if machine_decision == "yes":
        return answer in ("no", "not_sure")
    if machine_decision == "no":
        return answer in ("yes", "in_between")
    return False


def decide(answer: Any, read: str, fired: bool,
           matched: bool) -> tuple[str, Optional[str]]:
    """The cell of the matrix: (what shows now, the kind for the coach).

    `now` is one of "praise", "rewrite", "exercise", "coach_request", "none".
    `kind` is None only for Audio unclear, which raises nothing.
    """
    if answer == "audio_unclear" or answer not in ANSWERS:
        return "none", None
    if read == "confident":
        kind = "praise" if answer in ("yes", "in_between") else "ambiguity"
        return "praise", kind
    if answer == "yes":
        return "none", "ambiguity"
    if read == "weak" and fired:
        now = "exercise" if matched else "coach_request"
        return now, "error" if answer in ("in_between", "no") else "ambiguity"
    if read == "weak":
        return "rewrite", "rewrite" if answer in ("in_between", "no") else "ambiguity"
    # The machine could not read the clip: nothing to show for it, and a
    # human ear settles it.
    return "none", "ambiguity"


def follow_up_for_judgement(
    database: Any, *, take_session_id: str, snippet_id: str,
    owner_user_id: str, answer: Any,
) -> str:
    """The matrix applied to this moment: what the sheet may show next, and
    the bookmark sent to the coach with its kind.

    Never raises: a failure to record the request is logged, and the answer
    itself was already saved.
    """
    if not take_session_id or not snippet_id:
        return "none"
    if answer == "audio_unclear" or answer not in ANSWERS:
        return "none"
    if judgement_after_feedback_enabled():
        return _answer_after_feedback(
            database, take_session_id=take_session_id, snippet_id=snippet_id,
            owner_user_id=owner_user_id, answer=answer)
    clip = _clip_read(database, take_session_id, snippet_id)
    if clip is None:
        return "none"
    matched = _exercise_on_moment(database, take_session_id, snippet_id)
    now, kind = decide(answer, clip["read"], bool(clip["observed"]), matched)
    if kind is None:
        return now
    if _request_on_moment(database, take_session_id, snippet_id) is None:
        raised = _raise_request(
            database, take_session_id=take_session_id, snippet_id=snippet_id,
            owner_user_id=owner_user_id, kind=kind, clip=clip, matched=matched)
        # The sentence is a promise: without the request it would be false.
        if now == "coach_request" and not raised:
            return "none"
    return now


def follow_up_for_open(
    database: Any, *, take_session_id: str, snippet_id: str,
    owner_user_id: str,
) -> str:
    """F1 at the open: the machine's read chooses what the sheet shows, and
    the coach request rises NOW under the machine's kind, insert-once
    (migration 0408, raised_on 'open'). Never raises."""
    if not take_session_id or not snippet_id:
        return "none"
    clip = _clip_read(database, take_session_id, snippet_id)
    if clip is None:
        return "none"
    matched = _exercise_on_moment(database, take_session_id, snippet_id)
    now, kind = decide_at_open(clip["read"], bool(clip["observed"]), matched)
    if kind is None:
        return now
    if _request_on_moment(database, take_session_id, snippet_id) is None:
        raised = _raise_request(
            database, take_session_id=take_session_id, snippet_id=snippet_id,
            owner_user_id=owner_user_id, kind=kind, clip=clip, matched=matched,
            raised_on="open")
        if now == "coach_request" and not raised:
            return "none"
    return now


def _answer_after_feedback(
    database: Any, *, take_session_id: str, snippet_id: str,
    owner_user_id: str, answer: Any,
) -> str:
    """F1: the judgement comes after the feedback. The request rose at the
    open (or rises now, under the machine's kind, if the open was never
    reported); the answer sets its `answer_kind` from the matrix. What the
    sheet shows next is the matrix's cell, as before. A clip with no read
    sends nothing: there is no read to disagree with."""
    clip = _clip_read(database, take_session_id, snippet_id)
    if clip is None:
        return "none"
    matched = _exercise_on_moment(database, take_session_id, snippet_id)
    fired = bool(clip["observed"])
    now, answer_kind = decide(answer, clip["read"], fired, matched)
    if answer_kind is None:
        return now
    if _request_on_moment(database, take_session_id, snippet_id) is None:
        _, kind = decide_at_open(clip["read"], fired, matched)
        if kind is None:
            return now
        if not _raise_request(
                database, take_session_id=take_session_id,
                snippet_id=snippet_id, owner_user_id=owner_user_id, kind=kind,
                clip=clip, matched=matched, raised_on="open"):
            return "none" if now == "coach_request" else now
    _set_answer_kind(database, take_session_id, snippet_id, answer_kind)
    return now


def practice_judgement(database: Any, practice: Any, answer: Any,
                       machine_decision: Any) -> Optional[str]:
    """Phase 2: after a practice attempt is judged, the moment's request
    learns the speaker's side. A judgement that disagrees with the machine's
    read of that attempt makes it an ambiguity (the first disagreement
    stays); one that agrees confirms the kind it rose under, once. Returns
    what was written, or None. Never raises."""
    if not judgement_after_feedback_enabled():
        return None
    if answer not in ANSWERS or answer == "audio_unclear":
        return None
    take = str((practice or {}).get("take_session_id") or "")
    snip = str((practice or {}).get("snippet_id") or "")
    request = _request_on_moment(database, take, snip)
    if request is None:
        return None
    if practice_disagrees(answer, machine_decision):
        return "ambiguity" if _set_answer_kind(
            database, take, snip, "ambiguity") else None
    if request.get("answer_kind"):
        return None
    kind = str(request.get("kind") or "error")
    return kind if _set_answer_kind(
        database, take, snip, kind, only_if_unset=True) else None


def _set_answer_kind(database: Any, take_session_id: str, snippet_id: str,
                     answer_kind: str, *, only_if_unset: bool = False) -> bool:
    writer = getattr(database, "set_exercise_coach_request_answer_kind", None)
    if writer is None:
        return False
    try:
        return writer(take_session_id=take_session_id, snippet_id=snippet_id,
                      answer_kind=answer_kind,
                      only_if_unset=only_if_unset) is not None
    except Exception as e:  # noqa: BLE001 — never lose the answer
        _log.warning("answer kind write failed take=%s snip=%s: %s",
                     take_session_id, snippet_id, e, exc_info=True)
        return False


def _clip_read(database: Any, take_session_id: str,
               snippet_id: str) -> Optional[dict]:
    """The machine's read of the clip and what fired on it, as the lane
    computes them. None when the clip cannot be read at all."""
    from services.confident_voice_practice import (
        _median_wpm, detected_problem_vocabulary, exercise_eligibility,
        machine_read, observed_problem_tags,
    )
    try:
        snippet = next(iter(
            database.get_confident_voice_practice_candidates([snippet_id])
            or []), None)
        if not isinstance(snippet, dict):
            return None
        verdict = exercise_eligibility(
            snippet, session_median_wpm=_median_wpm(
                database.get_snippets_by_session(take_session_id) or []))
        vocabulary = detected_problem_vocabulary(database)
        return {
            "snippet": snippet, "verdict": verdict, "vocabulary": vocabulary,
            "read": machine_read(verdict),
            "observed": observed_problem_tags(verdict, vocabulary=vocabulary),
        }
    except Exception as e:  # noqa: BLE001 — never lose the answer
        _log.warning("judgement clip read failed take=%s snip=%s: %s",
                     take_session_id, snippet_id, e, exc_info=True)
        return None


def clip_machine_read(database: Any, take_session_id: str,
                      snippet_id: str) -> Optional[str]:
    """The machine's read of one clip: "confident", "weak" or "unknown";
    None when the clip could not be read. The read that colours a bar
    green and chooses the follow-up; the Voice Album's Machine Yes too
    (founder 2026-10-05, Q5; N45). Internal, never surfaced (AC-9)."""
    read = _clip_read(database, take_session_id, snippet_id)
    return read["read"] if read else None


def _exercise_on_moment(database: Any, take_session_id: str,
                        snippet_id: str) -> bool:
    """A frozen 80/20 draw for this moment: the item already carries one."""
    getter = getattr(database, "get_confident_voice_exercise_assignment", None)
    if getter is None:
        return False
    try:
        return isinstance(getter(take_session_id, snippet_id), dict)
    except Exception as e:  # noqa: BLE001 — a failed read is "no exercise"
        _log.warning("assignment read failed take=%s snip=%s: %s",
                     take_session_id, snippet_id, e, exc_info=True)
        return False


def _request_on_moment(database: Any, take_session_id: str,
                       snippet_id: str) -> Any:
    getter = getattr(database, "get_exercise_coach_request", None)
    if getter is None:
        return None
    try:
        request = getter(take_session_id, snippet_id)
    except Exception as e:  # noqa: BLE001
        _log.warning("coach request read failed take=%s snip=%s: %s",
                     take_session_id, snippet_id, e, exc_info=True)
        return None
    return request if isinstance(request, dict) else None


def _raise_request(database: Any, *, take_session_id: str, snippet_id: str,
                   owner_user_id: str, kind: str, clip: dict,
                   matched: bool, raised_on: str = "judgement") -> bool:
    """Record the coach request for this moment, with its kind, what the
    detectors found, and where it rose (0408: at the judgement, or at the
    open under F1)."""
    from services.confident_voice_practice import (
        build_match_trace, offerable_exercises,
    )

    writer = getattr(database, "request_exercise_from_coach", None)
    if writer is None or not owner_user_id:
        return False
    observed = clip["observed"]
    reason = ("library_matched" if matched
              else "nothing_targets_it" if observed
              else "nothing_spotted")
    try:
        writer(
            owner_user_id=str(owner_user_id),
            take_session_id=str(take_session_id), snippet_id=str(snippet_id),
            reason=reason, kind=kind,
            **({"raised_on": raised_on} if raised_on != "judgement" else {}),
            pattern=clip["verdict"].get("pattern"),
            observed_tags=sorted(observed),
            request_trace=build_match_trace(
                lane=JUDGEMENT_LANE, verdict=clip["verdict"],
                vocabulary=clip["vocabulary"],
                exercises=offerable_exercises(database), ranked=[],
                fit=None, snippet=clip["snippet"],
                take_session_id=take_session_id, snippet_id=snippet_id))
        return True
    except Exception as e:  # noqa: BLE001 — never lose the answer
        _log.warning("judgement coach request failed take=%s snip=%s: %s",
                     take_session_id, snippet_id, e, exc_info=True)
        return False
