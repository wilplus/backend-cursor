"""A judged practice attempt feeds the paragraph (contract 29a / 35d, founder
2026-09-25).

Q17 A: every practice attempt is judged on the same five-answer screen as the
first judgement. No or Audio unclear offers another attempt, up to three.
Yes, In-between or Not sure ADOPTS that attempt:

Q18 A: the attempt's words replace only the passage that was practised, inside
its paragraph; the rest stays as the Take said it. The passage is found by its
recording piece in the document (`snippet_id`), never by fuzzy text matching.
If that piece is no longer in the document (a later Take rebuilt the Slide),
nothing is replaced — the speaker still taps helper words from the practice.

The replacement is one atomic RPC that refuses a document that moved since it
was read. The previous words stay in `ideal_text_practice_adoptions`, which
the paragraph history reads. The next Take rewrites the paragraph again
(contract 8).

Owner self-reports only — nothing here is a label, and Voice Album admission
still needs Machine Yes + User Yes + Coach Yes on the exact attempt (L3).
"""
from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any, Optional

logger = logging.getLogger(__name__)

ANSWERS = ("yes", "in_between", "no", "not_sure", "audio_unclear")
ADOPTING = frozenset({"yes", "in_between", "not_sure"})
MAX_ATTEMPTS = 3

# The owner route stores the five answers in four routing values (the
# feedback-response route's mapping). Starting a practice compares against it.
ROUTE_OF = {"yes": "yes", "no": "no", "audio_unclear": "unrateable",
            "in_between": "neutral", "not_sure": "neutral"}


def outcome(answer: str, attempts: int) -> str:
    """"adopt", "again" or "closed" after judging the latest attempt."""
    if answer in ADOPTING:
        return "adopt"
    return "again" if attempts < MAX_ATTEMPTS else "closed"


def judgeable_attempt(attempts: list) -> Optional[dict]:
    """The latest attempt, if it has not been judged yet."""
    if not attempts:
        return None
    latest = max(attempts, key=lambda r: int(r.get("attempt_index") or 0))
    return None if latest.get("user_answer") else latest


def passage_span(document: Any, text: str,
                 snippet_id: str) -> Optional[tuple[int, int]]:
    """Where the practised passage sits in the current text, by its piece."""
    if not isinstance(document, Mapping):
        return None
    for piece in document.get("pieces") or []:
        if not isinstance(piece, Mapping):
            continue
        if str(piece.get("snippet_id") or "") != str(snippet_id):
            continue
        a, b = piece.get("start"), piece.get("end")
        if (isinstance(a, int) and isinstance(b, int) and 0 <= a < b <= len(text)
                and text[a:b] == piece.get("text")):
            return a, b
    return None


def practice_words(transcript: Any, language: Optional[str] = None) -> str:
    """The attempt's words as a passage: smoothed like a Take's pieces, on
    one line, so it can never introduce a paragraph break."""
    from services.transcript_smoothing import smooth_piece

    flat = re.sub(r"\s+", " ", str(transcript or "")).strip()
    return smooth_piece(flat, language) if flat else ""


def splice(text: str, document: Mapping, start: int, end: int,
           words: str) -> tuple[str, dict]:
    """Replace [start, end) with `words`; every offset after it moves."""
    delta = len(words) - (end - start)
    new_text = text[:start] + words + text[end:]

    def _moved(row: Mapping) -> dict:
        a, b = row.get("start"), row.get("end")
        out = dict(row)
        if isinstance(a, int) and a >= end:
            out["start"] = a + delta
        if isinstance(b, int) and b >= end:
            out["end"] = b + delta
        return out

    pieces = []
    for piece in document.get("pieces") or []:
        if not isinstance(piece, Mapping):
            continue
        if piece.get("start") == start and piece.get("end") == end:
            pieces.append(dict(piece, end=start + len(words), text=words))
        else:
            pieces.append(_moved(piece))
    paragraphs = [_moved(p) for p in document.get("paragraphs") or []
                  if isinstance(p, Mapping)]
    return new_text, dict(document, pieces=pieces, paragraphs=paragraphs)


def _paragraph_at(text: str, at: int) -> tuple[int, str]:
    blocks = text.split("\n\n")
    cursor = 0
    for i, block in enumerate(blocks):
        if cursor <= at <= cursor + len(block):
            return i, block
        cursor += len(block) + 2
    return len(blocks) - 1, blocks[-1]


def adopt(database: Any, practice: Mapping, attempt: Mapping,
          owner_user_id: str) -> dict:
    """Replace the practised passage with the attempt's words, if provable.

    Returns {"adopted": bool, "reason": str}. Never raises: the answer is
    already stored, and a paragraph that cannot be changed is not an error
    the speaker can act on."""
    arc_id = str(practice.get("project_id") or "")
    try:
        row = database.ideal_text.get_coach_arc_ideal_text(arc_id) or {}
        text = str(row.get("auto_text") or "")
        document = row.get("document")
        span = passage_span(document, text, str(practice.get("snippet_id")))
        if span is None or not isinstance(document, Mapping):
            return {"adopted": False, "reason": "passage_not_in_document"}
        words = practice_words(attempt.get("transcript"))
        if not words:
            return {"adopted": False, "reason": "empty_transcript"}
        new_text, new_document = splice(text, document, span[0], span[1],
                                        words)
        index, before = _paragraph_at(text, span[0])
        after = new_text.split("\n\n")[index]
        paragraphs = new_document.get("paragraphs") or []
        slide = (paragraphs[index].get("slide_index")
                 if index < len(paragraphs) else None)
        receipt = database.adopt_practice_passage(
            arc_id=arc_id, owner_user_id=owner_user_id,
            expected_text=text, new_text=new_text, new_document=new_document,
            slide_index=slide, practice_id=str(practice.get("id")),
            attempt_id=str(attempt.get("id")), before=before, after=after)
        if not isinstance(receipt, Mapping) or receipt.get("adopted") is not True:
            return {"adopted": False, "reason": "document_moved"}
        _rename_part(database, arc_id, owner_user_id, text, index, after)
        from services.ideal_text_core_snapshot import publish_for_arc
        publish_for_arc(database, arc_id, owner_user_id)
        return {"adopted": True, "reason": "", "paragraph": after}
    except Exception as error:
        logger.warning("practice adoption failed practice=%s: %s",
                       practice.get("id"), error)
        return {"adopted": False, "reason": "error"}


def _rename_part(database: Any, arc_id: str, user_id: str, old_text: str,
                 index: int, after: str) -> None:
    """The adopted paragraph keeps its id; only its words change."""
    from services.ideal_text_parts import agrees_with_text, serve

    rows = database.get_ideal_text_parts(arc_id, user_id, with_lock=True) or []
    served = serve(rows)
    if not served or not agrees_with_text(served, old_text) \
            or index >= len(served):
        return
    by_id = {str(r.get("id")): r for r in rows}
    database.replace_ideal_text_parts(arc_id, user_id, [
        {"id": p["id"], "ord": i,
         "text": after if i == index else p["text"],
         "locked_at": (by_id.get(str(p["id"])) or {}).get("locked_at")}
        for i, p in enumerate(served)])


def phrase_in_transcript(phrase: Any, transcript: Any) -> Optional[str]:
    """The helper words, when they are exact words of the practice attempt.

    Used when the passage could not be adopted: the speaker still taps their
    helper words from what they said while practising (Q10 B / Q18 A)."""
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
    step = outcome(str(answer), len(attempts))
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
            "closed_at": now,
        }) or practice
    if step == "adopt":
        adoption = adopt(database, practice, target, owner_user_id)
        # `paragraph`: the adopted paragraph's words, so the sheet shows them
        # at once and locks against the text the server now holds.
        result.update(adopted=adoption["adopted"],
                      paragraph=adoption.get("paragraph"),
                      attempt_transcript=practice_words(
                          target.get("transcript")))
    return 200, result


def helper_words_from_practice(database: Any, practice: Mapping,
                               part_id: Any, phrase: Any,
                               owner_user_id: str) -> tuple[int, dict]:
    """Tap helper words from the adopted practice attempt (Q10 B).

    For when the passage could not be adopted into the paragraph: the words
    are then not in the paragraph, so the paragraph-level endpoint cannot
    take them. They are stored on the Slide, unlocked; the Lock step that
    follows locks them like any other pick."""
    from services.intervention_spend import latest_spoken_take_sid
    from services.slide_helper_words import record_pick

    if practice.get("status") != "completed" \
            or practice.get("final_user_answer") not in ADOPTING:
        return 409, {"code": "NOT_ADOPTED",
                     "error": "Judge a practice attempt first."}
    if not isinstance(part_id, str) or not part_id:
        return 400, {"code": "INVALID_INPUT", "error": "part_id is required"}
    attempt = next((r for r in database.list_confident_voice_practice_attempts(
        str(practice.get("id")))
        if str(r.get("id")) == str(practice.get("selected_attempt_id"))), None)
    words = phrase_in_transcript(phrase, (attempt or {}).get("transcript"))
    if words is None:
        return 400, {"code": "INVALID_ROOT_PHRASE",
                     "error": "Choose exact words from your practice."}
    arc_id = str(practice.get("project_id"))
    take_id = latest_spoken_take_sid(database.takes.get_arc_sessions(arc_id))
    record_pick(database, arc_id, owner_user_id, part_id, take_id, words)
    return 200, {"saved": True, "phrase": words}
