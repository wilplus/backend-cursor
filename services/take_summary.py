"""The closing summary after a Take's review (founder lock 2026-10-12,
moment and feedback chat, section 3).

One plain Lounge bubble, 2-3 sentences, written by GPT-4o
(``SPEC_TAKE_SUMMARY``) through the processing-authorization path (a
protected provider scope for the Take, as ``services.willfidence`` does).

- It starts from the spirit of the signed journey copy for that Take
  (``journey_messages``): anchors, not a script.
- It adds this Take's real progress against the last one, from the
  willfidence reads (S, the voice; W, the words), the practice result, the
  coach's note and at most two helper words.
- It sounds like a coach talking: "you", contractions, plain words; never
  "cue" or a metric name; no number, score or verdict (AC-9); no
  cheerleading. After Take 1 it claims no progress.

Anything that fails (no permit, no provider, a reply that breaks the
rules) falls back to the signed journey copy, so the speaker always gets
the bubble. Stored once per Take (a fixed client id).

A coach update: when the Take's review ends with a coach note and the
stored summary was written without one, the summary is written again with
it and rewrites the bubble in place; the earlier words stay in its
metadata (``earlier``), one tap away in the Lounge.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_NAMESPACE = uuid.UUID("3d7c1f0e-8a52-4c1b-9b8e-0e1f2a3b4c5d")
_SURFACE = "take_summary"
#: A move smaller than this between two Takes is "held" (internal only).
_MOVE = 0.03
_BANNED = re.compile(r"\d|%|\bcue\b|\bscore\b|\bmetric|\bwillfidence\b|\bpercent", re.I)

_SYSTEM = (
    "You are a speaking coach writing one short chat message to a speaker "
    "after they reviewed a recording of their talk. Write 2 or 3 plain "
    "sentences, like a coach talking to a friend: use 'you' and "
    "contractions. Never use numbers, scores, percentages, verdicts, the "
    "word 'cue', or names of measurements. No cheerleading, no exclamation "
    "marks, no emoji. Only say what the facts support. If the facts say "
    "there is no earlier take, do not claim any progress."
)


def summary_client_id(user_id: Any, arc_id: Any, take_index: int) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{user_id}:{arc_id}:take:{take_index}:summary"))


def _mean(rows: list[dict], key: str) -> Optional[float]:
    values = [float(r[key]) for r in rows if isinstance(r.get(key), (int, float))]
    return sum(values) / len(values) if values else None


def _move(now: Optional[float], before: Optional[float]) -> Optional[str]:
    if now is None or before is None:
        return None
    if now - before > _MOVE:
        return "rose"
    if before - now > _MOVE:
        return "dipped"
    return "held"


def progress_facts(now: list[dict], before: Optional[list[dict]]) -> list[str]:
    """Plain-word facts on this Take against the last one. Pure."""
    if before is None:
        return ["This is the speaker's first take: there is no earlier take."]
    facts = []
    voice = _move(_mean(now, "s"), _mean(before, "s"))
    words = _move(_mean(now, "w"), _mean(before, "w"))
    if voice:
        facts.append(f"How sure the voice sounded {voice} compared with the last take.")
    if words:
        facts.append(f"How clear and direct the words were {words} compared with the last take.")
    return facts or ["There is not enough to compare this take with the last one."]


def _clean(text: Optional[str]) -> Optional[str]:
    """The reply, if it keeps the rules: 2-3 sentences, no number or banned
    word, no exclamation. Else None."""
    if not text:
        return None
    body = " ".join(text.strip().strip('"').split())
    sentences = [s for s in re.split(r"(?<=[.?])\s+", body) if s]
    if not 2 <= len(sentences) <= 3 or _BANNED.search(body) or "!" in body:
        return None
    return body


def write_summary(anchor: str, facts: list[str], *, practice: Optional[str],
                  helper_words: list[str], coach_note: Optional[str],
                  session_id: str, arc_id: str, user_id: str) -> Optional[str]:
    from services.llm import chat_complete
    from services.llm_config import SPEC_TAKE_SUMMARY
    lines = [f"The usual message for this point (use its spirit, not its words): {anchor}",
             "Facts:"] + [f"- {f}" for f in facts]
    if practice == "better":
        lines.append("- In practice, their last try sounded more assured than the first.")
    elif practice == "not_yet":
        lines.append("- They practised one sentence; it is not there yet.")
    if helper_words:
        lines.append("- Helper words they chose: " + ", ".join(f'"{w}"' for w in helper_words[:2]))
    if coach_note:
        lines.append(f"- Their coach asked: {coach_note[:400]}")
    result = chat_complete(spec=SPEC_TAKE_SUMMARY, system=_SYSTEM, user="\n".join(lines),
                           surface=_SURFACE, user_id=user_id, session_id=session_id,
                           arc_id=arc_id)
    return _clean(getattr(result, "text", None) if result else None)


def _under_authority(database: Any, take: str, write) -> Optional[str]:
    """Run ``write`` inside the Take's protected provider scope when the
    processing-authorization mode enforces (``services.willfidence``)."""
    from services.processing_authorization import ProcessingAuthorizationService
    authorization = ProcessingAuthorizationService(database)
    if not authorization.enforced:
        return write()
    from services.authorized_provider import (
        AuthorizedProviderAdapter, ProviderCoordinates, protected_provider_scope)
    session = database.v2_get_session_by_id(take) or {}
    principal = authorization.resolve_acquisition_principal(
        str(session.get("owner_principal_id") or ""),
        user_id=str(session.get("user_id") or "") or None)
    if not principal:
        return None
    adapter = AuthorizedProviderAdapter(
        database, ProviderCoordinates(principal, take, None), authorization=authorization)
    with protected_provider_scope(adapter, idempotency_prefix=f"take-summary:{take}:{uuid.uuid4()}"):
        return write()


def _reads(database: Any, ids: list[str], take_index: int) -> tuple[list[dict], Optional[list[dict]]]:
    """This Take's willfidence reads and the last Take's (None for Take 1)."""
    try:
        now = database.list_v4_willfidence_reads(ids[take_index - 1]) or []
        before = (database.list_v4_willfidence_reads(ids[take_index - 2]) or []
                  if take_index > 1 else None)
        return now, before
    except Exception as error:  # noqa: BLE001 -- no reads: nothing to compare
        logger.warning("take summary reads failed take=%s: %s", ids[take_index - 1], error,
                       exc_info=True)
        return [], ([] if take_index > 1 else None)


def _ask(body: dict) -> tuple[Optional[str], list[str], Optional[str]]:
    """The practice result, at most two helper words and the coach's note,
    as the walk sent them; anything else is dropped. Pure."""
    practice = body.get("practice") if body.get("practice") in ("better", "not_yet") else None
    words = [w for w in (body.get("helper_words") or []) if isinstance(w, str) and w.strip()][:2]
    note = body.get("coach_note") if isinstance(body.get("coach_note"), str) else None
    return practice, words, (note.strip() if note and note.strip() else None)


def _written(database: Any, take: str, anchor: str, facts: list[str], practice: Optional[str],
             words: list[str], note: Optional[str], arc_id: str, user_id: str) -> Optional[str]:
    """GPT-4o's summary under the Take's authority; None when refused or failed."""
    try:
        return _under_authority(database, take, lambda: write_summary(
            anchor, facts, practice=practice, helper_words=words, coach_note=note,
            session_id=take, arc_id=arc_id, user_id=user_id))
    except Exception as error:  # noqa: BLE001 -- refused or failed: the signed copy
        logger.warning("take summary refused take=%s: %s", take, error, exc_info=True)
        return None


def summary_message(database: Any, *, user_id: str, arc_id: str, takes: list[dict],
                    take_session_id: str, body: dict) -> Optional[dict]:
    """The summary bubble for one Take of the arc (``takes``: its spoken
    Takes in order), stored once; rewritten once by a coach update. None
    when the Take is not the arc's."""
    from services.journey_messages import _COPY
    ids = [str(t.get("id")) for t in takes]
    take = str(take_session_id)
    if take not in ids:
        return None
    take_index = ids.index(take) + 1
    client_id = summary_client_id(user_id, arc_id, take_index)
    practice, words, note = _ask(body)
    held = database.get_lounge_message_by_client_id(str(user_id), client_id)
    if held and (note is None or ((held.get("metadata") or {}).get("coach_noted"))):
        return held
    anchor = _COPY.get(take_index) or _COPY[3]
    now, before = _reads(database, ids, take_index)
    text = _written(database, take, anchor, progress_facts(now, before), practice, words,
                    note, str(arc_id), str(user_id))
    meta = {"summary": True, "arc_id": str(arc_id), "take_index": take_index,
            "take_session_id": take, "written": bool(text), "coach_noted": note is not None}
    if held:
        if not text:
            return held  # the coach's update could not be written: keep it
        meta.update({"coach_update": True, "earlier": held.get("body")})
        return database.rewrite_lounge_message(str(user_id), client_id, text, meta) or held
    persisted = database.insert_lounge_messages(str(user_id), [{
        "client_id": client_id,
        "role": "bot",
        "kind": "cadence",
        "body": text or anchor,
        "metadata": meta,
        "client_created_at": datetime.now(timezone.utc).isoformat(),
    }])
    return persisted[0] if persisted else None


#: The coach update's label and first line (lock 2026-10-12, sections 3 and 8).
COACH_UPDATE_LABEL = "Later · from your coach"
COACH_TITLE = "Your coach"


def coach_update_message(database: Any, *, take_session_id: str, text: Optional[str],
                         video_ref: Optional[str]) -> Optional[dict]:
    """A coach's word shared after the Take's review ended (its summary is
    stored): its own Lounge bubble under "Later · from your coach", as the
    coach wrote it (lock 2026-10-12, section 3). Stored once per word.
    None when the review has not ended (the walk shows the word as its
    first step) or anything is missing."""
    from services.slide_selection import spoken_arc_sessions
    take = str(take_session_id)
    session = database.v2_get_session_by_id(take) or {}
    user_id, arc_id = session.get("user_id"), session.get("arc_id")
    if not user_id or not arc_id or not (text or video_ref):
        return None
    takes = [s for s in spoken_arc_sessions(database.takes.get_arc_sessions(str(arc_id)))
             if s.get("analysis_state") in (None, "ready")]
    ids = [str(s.get("id")) for s in takes]
    if take not in ids:
        return None
    take_index = ids.index(take) + 1
    if not database.get_lounge_message_by_client_id(
            str(user_id), summary_client_id(user_id, arc_id, take_index)):
        return None
    video_url = None
    if video_ref:
        from services.coach_video_storage import refreshed_media_url
        video_url = refreshed_media_url(video_ref)
    body = f"{COACH_TITLE}\n{text}" if text else COACH_TITLE
    persisted = database.insert_lounge_messages(str(user_id), [{
        "client_id": str(uuid.uuid5(_NAMESPACE, f"{take}:coach-update:{text or ''}:{video_ref or ''}")),
        "role": "bot",
        "kind": "walk_step",
        "body": body,
        "metadata": {"step": "coachnote", "author": "coach", "coach_update": True,
                     "heading": COACH_UPDATE_LABEL, "arc_id": str(arc_id),
                     "take_session_id": take, "take_index": take_index,
                     "video": video_url},
        "client_created_at": datetime.now(timezone.utc).isoformat(),
    }])
    return persisted[0] if persisted else None
