"""The practice loop (contract 29a, founder lock 2026-09-30, B6, D2).

Every practice attempt is judged on the same five-answer screen as the
first judgement (Q17 A). No, Not sure or Audio unclear offers another
attempt, as long as the speaker wants: there is no attempt cap (D2). Yes or
In-between is done: the helper words are tapped from that attempt's own
words and the lock follows (B6).

A PRACTICE NEVER REWRITES THE PARAGRAPH (B6: "the paragraph text on the
page is unchanged by any attempt; only a Take rewrites it"). Until the lock
an adopting answer spliced the attempt's transcript into the passage it
practised (founder 2026-09-25, Q18 A); that rule is retired with its code,
and the rows it wrote stay in `ideal_text_practice_adoptions` for the
paragraph history to read.

THREE KINDS OF PASSAGE (D1): the library exercise where one is matched to
the clip, else the Manager's rewrite as the words to say, else the plain
moment said again. The kind names what the passage is; the loop is the same
for all three.

Owner self-reports only — nothing here is a label, and Voice Album admission
still needs Machine Yes + User Yes + Coach Yes on the exact attempt (L3).
"""
from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any, Optional

from services.canonical_product import OWNER_RESPONSES

logger = logging.getLogger(__name__)

# The one vocabulary (audit D2), in the order the instrument offers it.
ANSWERS = tuple(
    answer for answer in ("yes", "in_between", "no", "not_sure", "audio_unclear")
    if answer in OWNER_RESPONSES["confident_voice"]
)
assert set(ANSWERS) == set(OWNER_RESPONSES["confident_voice"])
# The answers that end the loop and open the helper words (B2, 29a).
DONE_ANSWERS = frozenset({"yes", "in_between"})

# What the practised passage is (D1): a library exercise, the Manager's
# rewrite, or the moment's own words.
KINDS = ("exercise", "rewrite", "plain")

# The owner route stores the answer itself since F-4 closed (2026-09-28,
# `album_routing_for`). Rows written before that hold the four legacy routing
# values the Take-review route used to fold the five answers into; they are
# audit-only, receive no new writes, and are still read. A legacy `neutral`
# cannot say whether it was an in-between or a not-sure — that is the
# distinction F-4 was about — so it matches either.
LEGACY_ROUTE_OF = {"yes": "yes", "no": "no", "audio_unclear": "unrateable",
                   "in_between": "neutral", "not_sure": "neutral"}


def route_matches(stored: str, answer: str) -> bool:
    """Does a stored owner route record this answer, in either vocabulary?"""
    if answer not in ANSWERS:
        return False
    return stored == answer or stored == LEGACY_ROUTE_OF[answer]


def outcome(answer: str) -> str:
    """"done" or "again" after judging the latest attempt. No cap (D2):
    every answer but Yes and In-between is another attempt."""
    return "done" if answer in DONE_ANSWERS else "again"


def passage_for(kind: Any, transcript: Any, proposed: Any) -> Optional[str]:
    """The words to say for a practice of this kind, or None when the kind
    is unknown or the passage is missing. An exercise or the plain moment
    practises the moment's own words; a rewrite practises the Manager's
    clearer version, sent by the client from the served item."""
    if kind not in KINDS:
        return None
    if kind == "rewrite":
        words = re.sub(r"\s+", " ", str(proposed or "")).strip()
        if not words or re.search(r"[*_~`{}]", words) or len(words) > 2000:
            return None
        return words
    words = str(transcript or "").strip()
    return words or None


def judgeable_attempt(attempts: list) -> Optional[dict]:
    """The latest attempt, if it has not been judged yet."""
    if not attempts:
        return None
    latest = max(attempts, key=lambda r: int(r.get("attempt_index") or 0))
    return None if latest.get("user_answer") else latest


def practice_words(transcript: Any, language: Optional[str] = None) -> str:
    """The attempt's words as a passage: smoothed like a Take's pieces, on
    one line, so it can never introduce a paragraph break."""
    from services.transcript_smoothing import smooth_piece

    flat = re.sub(r"\s+", " ", str(transcript or "")).strip()
    return smooth_piece(flat, language) if flat else ""


def phrase_in_transcript(phrase: Any, transcript: Any) -> Optional[str]:
    """The helper words, when they are exact words of the practice attempt:
    the speaker taps them from what they said while practising (B6)."""
    if not isinstance(phrase, str):
        return None
    want = re.sub(r"\s+", " ", phrase).strip()
    have = re.sub(r"\s+", " ", practice_words(transcript))
    if not want or re.search(r"[*_~`]", want):
        return None
    return want if want in have else None


def judge_attempt(database: Any, practice: Mapping, attempt_id: str,
                  answer: Any, owner_user_id: str) -> tuple[int, dict]:
    """The five-answer judgement of the latest practice attempt (Q17 A).

    Returns (status, body). `practice_row` is the practice after the answer;
    the route turns it into the owner-safe payload."""
    from datetime import datetime, timezone

    if answer not in ANSWERS:
        return 400, {"code": "INVALID_INPUT",
                     "error": "user_answer is not one of the five answers"}
    if practice.get("status") != "open":
        return 409, {"code": "PRACTICE_CLOSED",
                     "error": "This practice is already closed."}
    attempts = database.list_confident_voice_practice_attempts(
        str(practice.get("id")))
    target = judgeable_attempt(attempts)
    if target is None or str(target.get("id")) != str(attempt_id):
        return 409, {"code": "NOT_JUDGEABLE",
                     "error": "Judge your latest attempt."}
    if not database.keep_confident_voice_practice_attempt(
            str(practice.get("id")), str(attempt_id), str(answer)):
        return 500, {"code": "V2_ERROR", "error": "Could not save."}
    from services.judgement_follow_up import practice_judgement
    # Phase 2 (founder 2026-10-01, F1): the moment's coach request learns
    # the speaker's side of this attempt; off, this writes nothing.
    practice_judgement(database, practice, str(answer),
                       target.get("machine_confidence_decision"))
    step = outcome(str(answer))
    # `adopted` and `paragraph` stay on the wire, always False and None: a
    # practice never rewrites the paragraph (B6). `attempt_transcript` is
    # what the helper-words picker taps from.
    result: dict = {"outcome": step, "adopted": False, "paragraph": None,
                    "attempt_transcript": None, "practice_row": practice}
    if step == "again":
        return 200, result
    now = datetime.now(timezone.utc).isoformat()
    result["practice_row"] = database.update_confident_voice_practice(
        str(practice.get("id")), owner_user_id, {
            "status": "completed",
            "selected_attempt_id": str(attempt_id),
            "final_user_answer": str(answer),
            # F7 (founder 2026-10-01): where the speaker landed, for reading
            # only. The scorekeeper reads the first valid attempt instead.
            "landed_attempt_index": target.get("attempt_index"),
            "closed_at": now,
        }) or practice
    result["attempt_transcript"] = practice_words(target.get("transcript"))
    from services.after_practice import after_landing
    # Phase 3 (founder 2026-10-01, F5): one sentence about the attempt the
    # speaker LANDED on; the scorekeeper reads the first valid one (F7) and
    # the two may disagree by design. Off, nothing is said.
    said = after_landing(database, result["practice_row"], attempts,
                         attempt_id, str(answer))
    if said:
        result["practice_row"] = {**result["practice_row"], "after_practice": said}
    # Phase 5: the closed practice's pair for the delayed measure (off,
    # nothing). The endpoint is the first valid attempt, not the landing.
    from services.delayed_measure import enrol
    enrol(database, result["practice_row"])
    return 200, result


def helper_words_from_practice(database: Any, practice: Mapping,
                               part_id: Any, phrase: Any,
                               owner_user_id: str) -> tuple[int, dict]:
    """Tap helper words from the judged practice attempt (B6).

    The attempt's words are not in the paragraph, so the paragraph-level
    endpoint cannot take them. They are stored on the Slide, unlocked; the
    lock that follows locks them like any other pick."""
    from services.intervention_spend import latest_spoken_take_sid
    from services.slide_helper_words import record_pick

    from services.practice_check import machine_closed
    if practice.get("status") != "completed" or not (
            practice.get("final_user_answer") in DONE_ANSWERS
            or machine_closed(practice)):
        return 409, {"code": "NOT_ADOPTED",
                     "error": "Judge a practice attempt first."}
    if not isinstance(part_id, str) or not part_id:
        return 400, {"code": "INVALID_INPUT", "error": "part_id is required"}
    attempt = next((r for r in database.list_confident_voice_practice_attempts(
        str(practice.get("id")))
        if str(r.get("id")) == str(practice.get("selected_attempt_id"))), None)
    words = phrase_in_transcript(phrase, (attempt or {}).get("transcript"))
    from services.slide_helper_words import within_cap
    if words is None or not within_cap(words):
        return 400, {"code": "INVALID_ROOT_PHRASE",
                     "error": "Choose exact words from your practice."}
    arc_id = str(practice.get("project_id"))
    take_id = latest_spoken_take_sid(database.takes.get_arc_sessions(arc_id))
    record_pick(database, arc_id, owner_user_id, part_id, take_id, words)
    return 200, {"saved": True, "phrase": words}
