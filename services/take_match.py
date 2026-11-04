"""Matching people after a Take (founder, the Claude Code chat, 4 November
2026, N477, N478 and N481; drawn on the prototype
https://claude.ai/artifact/FtJL4G1VGm1MTNMKWujZ6W). Table: take_matches
(migration a_take_can_reach_someone_new_after_it).

People are matched in one place only: after a Take, when someone new fits
it (N477). This module finds that one person, keeps what came of it, and
makes the chat between the two only when that person answers (N478):

  * ``suggest``  for the speaker, after the walk: one person who shares one
    of their communities, is a member (N471), has no chat with them and was
    never suggested to them before, and who fits the Take best (N481 item
    2). Knowledge first, by its words, both ways: what the candidate knows
    (their profile) and practises (their Takes' topics) against what the
    Take needs, and what the speaker knows against what the candidate
    practises; then, once skills are on (``take_match_signals``), speaking
    skills by the experiment's arm (a similar level, or further along,
    N481 item 3) and progress alike. A pseudonym and a description, never
    a name. One per Take; none when nobody knows enough.
  * ``send`` / ``close``  Send puts Will's card in the candidate's chat with
    Will; Not now ends it, and nobody is told.
  * ``view`` / ``recording``  the candidate opens the Take: the speaker's
    pseudonym and description, what it is about, its words slide by slide,
    its voice. Never the Ideal Text, never the feedback.
  * ``answer``  the candidate's answer: a Take of theirs, recorded in the
    official recorder after the suggestion reached them and analysed like
    any Take (N481 item 1). Only now is the chat between the two made: the
    speaker's Take as a Take message (kind ``take``, as a Take sent to a
    list is, services/take_sends.py), then the answer, under their names.
    No answer: nothing happens, and nothing reminds anyone.

Behind the ring row ``take_match``: with no row it is off for everyone, the
founder included (services/rings.py); and it lives in the page that sends a
Take (N477), so it is off while sending is (``TAKE_SEND_ENABLED``). The
ranking reads only what is kept: word overlap (``speaker_lookup.key_terms``)
and Willfidence's reads; no provider call, nothing leaves the backend. The
fit and what made it are kept for WillpowerLab's review and never shown to
anyone (Never 1). Every suggestion is in the arm "topics" while skills are
off (N481 item 4).
"""
from __future__ import annotations

import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from services.chats import (
    MEMBERS, MESSAGES, SESSIONS, ChatsError, _not_found, _rows, _table, _take_of,
    _UNIQUE_VIOLATION, _uuid, post_answer,
)
from services import take_match_signals as signals
from services.rings import TAKE_MATCH as FEATURE

logger = logging.getLogger(__name__)

MATCHES = "take_matches"
COMMUNITY_MEMBERS = "community_members"
PROFILES = "people_profiles"
#: The card's key in Will's chat (lounge_messages.metadata.card).
CARD = "take_match"
#: The least fit worth a suggestion: two words of what the Take is about
#: that the candidate knows, or as much from what they practise. Proposed,
#: for the founder's review of the first weeks.
MIN_FIT = 2.0
#: How many rows any one read takes, at most.
MAX_ROWS = 500
#: The card's words, Will's line to the candidate: the founder's own (N478
#: item 6), not signed yet; the ring keeps them off every screen until then.
COPY = {"card": "{pseudonym} might benefit from your knowledge immensely."}
#: The experiment's arms on speaking skills (N481 item 3): someone at a
#: similar level, or someone further along. "topics" is every suggestion
#: made while skills are off.
SKILL_ARMS = ("similar_level", "further_along")
#: Proposed, for the founder's review of the first weeks: what skills and
#: progress weigh beside knowledge (a word the candidate knows weighs 1),
#: how far ahead "further along" aims, and how big a gap is no fit at all,
#: in willfidence (0 to 1) and in its change per Take.
SKILL_WEIGHT, PACE_WEIGHT = 2.0, 2.0
FURTHER_BY, SKILL_SPAN, PACE_SPAN = 0.15, 0.5, 0.05
_NAMESPACE = uuid.UUID("6f1d3b8e-3c0a-4d55-9a7e-2b9c1f4e8a10")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_on(database: Any, user_id: Any) -> bool:
    """Is matching on for this speaker? The ring row ``take_match``, and
    sending a Take on, since the match is made on its page (N477); a
    failure is a closed door."""
    from services import rings, take_sends
    return bool(user_id) and take_sends.is_on() and rings.feature_is_on_for_user(
        FEATURE, str(user_id), database=database)


def chat_name(database: Any, user_id: Any, token_payload: Any) -> str:
    """The name a person goes by in the chats: the one on their profile if
    they set one (N366), else the account's (``chat_links.name_of``)."""
    from services.chat_links import name_of
    profile = _profiles(database, [str(user_id)]).get(str(user_id), {}) if user_id else {}
    return str(profile.get("name") or "").strip() or name_of(token_payload)


def _pseudonym(user_id: str) -> str:
    from services.coach_pseudonym import coach_pseudonym
    return coach_pseudonym(user_id)


# ── Who could it be ──────────────────────────────────────────────────────

def pool(database: Any, speaker_id: str) -> list[str]:
    """Everyone who shares a community with the speaker (a private one: the
    general community has no member rows), minus whoever already has a chat
    with them and whoever was suggested to them before; sorted, so a tie
    always goes the same way."""
    communities = [str(r["community_id"]) for r in _rows(
        _table(database, COMMUNITY_MEMBERS).select("community_id")
        .eq("user_id", speaker_id).limit(MAX_ROWS))]
    if not communities:
        return []
    people = {str(r["user_id"]) for r in _rows(
        _table(database, COMMUNITY_MEMBERS).select("user_id")
        .in_("community_id", communities).limit(MAX_ROWS)) if r.get("user_id")}
    return sorted(people - _in_chats_with(database, speaker_id)
                  - _suggested_before(database, speaker_id) - {speaker_id})


def _in_chats_with(database: Any, user_id: str) -> set[str]:
    threads = [str(r["thread_id"]) for r in _rows(
        _table(database, MEMBERS).select("thread_id").eq("user_id", user_id).limit(MAX_ROWS))]
    if not threads:
        return set()
    return {str(r["user_id"]) for r in _rows(
        _table(database, MEMBERS).select("user_id").in_("thread_id", threads))
        if r.get("user_id")}


def _suggested_before(database: Any, user_id: str) -> set[str]:
    return {str(r["candidate_id"]) for r in _rows(
        _table(database, MATCHES).select("candidate_id").eq("speaker_id", user_id)
        .limit(MAX_ROWS))}


# ── What fits ────────────────────────────────────────────────────────────

def _take(database: Any, speaker_id: str, session: str) -> Optional[dict]:
    rows = _rows(_table(database, SESSIONS).select("id,user_id,intake_context,slide_transcripts")
                 .eq("id", session).eq("user_id", speaker_id).limit(1))
    return rows[0] if rows else None


def topic_of(take: dict) -> str:
    """What the Take is about, as the speaker set it (intake_context.topic)."""
    context = take.get("intake_context")
    return str((context or {}).get("topic") or "").strip() if isinstance(context, dict) else ""


def _parts(take: dict) -> list[dict]:
    parts = take.get("slide_transcripts")
    if not isinstance(parts, list):
        return []
    return sorted((p for p in parts if isinstance(p, dict)), key=lambda p: int(p.get("index") or 0))


def said(take: dict) -> str:
    """The Take's words, slide by slide."""
    return "\n\n".join(t for t in (str(p.get("transcript") or "").strip()
                                   for p in _parts(take)) if t)


def _profiles(database: Any, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    return {str(r["user_id"]): r for r in _rows(
        _table(database, PROFILES).select("user_id,name,role,about").in_("user_id", ids))}


def _topics(database: Any, ids: list[str]) -> dict[str, list[str]]:
    """What each person practises: the topics of their own Takes, newest first."""
    if not ids:
        return {}
    out: dict[str, list[str]] = {}
    for row in _rows(_table(database, SESSIONS).select("user_id,intake_context")
                     .in_("user_id", ids).order("created_at", desc=True).limit(MAX_ROWS)):
        topic = topic_of(row)
        if topic and topic not in out.get(str(row["user_id"]), []):
            out.setdefault(str(row["user_id"]), []).append(topic)
    return out


def _knows(profile: dict) -> str:
    return f"{profile.get('role') or ''} {profile.get('about') or ''}"


def fit(wanted: set[str], knows: set[str], practises: set[str],
        speaker_knows: set[str]) -> tuple[float, list[str]]:
    """How well a candidate fits a Take, both ways, and the words that made
    it: what the Take is about against what they know (1 a word) and what
    they practise (half), and what the speaker knows against what they
    practise (half). Pure."""
    know, practise, back = wanted & knows, wanted & practises, speaker_knows & practises
    return (len(know) + 0.5 * len(practise) + 0.5 * len(back),
            sorted(know | practise | back))


def draw_arm() -> str:
    """The experiment's arm for one suggestion, at random (N481 item 3)."""
    return random.choice(SKILL_ARMS)


def closeness(gap: Optional[float], target: float, span: float) -> float:
    """1 when ``gap`` is ``target``, down to 0 at ``span`` away; a half when
    it is not known yet. Pure."""
    if gap is None:
        return 0.5
    return max(0.0, 1.0 - abs(gap - target) / span)


def weigh(arm: str, knowledge: float, speaker: dict, candidate: dict) -> tuple[float, dict]:
    """A candidate's whole fit in ``arm`` and what made it (N481 item 2):
    knowledge, speaking skills by the arm, progress alike; the profiles'
    distance is kept beside it for the style arms. Never shown. Pure."""
    def gap(key: str) -> Optional[float]:
        a, b = speaker.get(key), candidate.get(key)
        return None if a is None or b is None else round(b - a, 4)
    skill = closeness(gap("skill"), FURTHER_BY if arm == "further_along" else 0.0, SKILL_SPAN)
    pace = closeness(gap("pace"), 0.0, PACE_SPAN)
    made = {"knowledge": knowledge, "skill": round(skill, 4), "pace": round(pace, 4),
            "skill_gap": gap("skill"), "pace_gap": gap("pace"),
            "profile_distance": signals.profile_distance(speaker.get("profile") or {},
                                                         candidate.get("profile") or {})}
    return round(knowledge + SKILL_WEIGHT * skill + PACE_WEIGHT * pace, 4), made


def _with_skills(database: Any, speaker_id: str, fits: list[dict[str, Any]]) -> None:
    """Weigh skills and progress into each fit, all in one arm."""
    arm = draw_arm()
    reads = signals.of(database, [speaker_id] + [f["candidate_id"] for f in fits])
    for f in fits:
        f["fit"], f["signals"] = weigh(arm, f["fit"], reads[speaker_id], reads[f["candidate_id"]])
        f["arm"] = arm


def best(database: Any, speaker_id: str, take: dict) -> Optional[dict]:
    """The one person who fits the Take best, or None: {"candidate_id",
    "fit", "terms", "arm", "signals"}. Only someone who knows enough of what
    it needs (``MIN_FIT``); then, once skills are on, skills and progress
    too. Only a member (N471): a waiting account cannot record, so could
    never answer."""
    from services import membership
    from services.speaker_lookup import key_terms
    people = pool(database, speaker_id)
    topic = topic_of(take)
    wanted = key_terms(f"{topic} {topic} {topic} {said(take)}")
    if not people or not wanted:
        return None
    profiles = _profiles(database, people + [speaker_id])
    topics = _topics(database, people)
    speaker_knows = key_terms(_knows(profiles.get(speaker_id, {})))
    fits: list[dict[str, Any]] = []
    for uid in people:
        score, terms = fit(wanted, key_terms(_knows(profiles.get(uid, {}))),
                           key_terms(" ".join(topics.get(uid, []))), speaker_knows)
        if score >= MIN_FIT:
            fits.append({"candidate_id": uid, "fit": score, "terms": terms,
                         "arm": "topics", "signals": {"knowledge": score}})
    if fits and signals.is_on():
        _with_skills(database, speaker_id, fits)
    # Highest fit first; a tie keeps the pool's sorted order (a stable sort).
    fits.sort(key=lambda f: f["fit"], reverse=True)
    return next((f for f in fits if membership.is_member(database, f["candidate_id"])), None)


# ── The speaker's side ───────────────────────────────────────────────────

def _offer(database: Any, row: dict) -> dict:
    """A suggestion as the speaker sees it: a pseudonym and a description."""
    candidate = str(row["candidate_id"])
    profile = _profiles(database, [candidate]).get(candidate, {})
    topics = _topics(database, [candidate]).get(candidate) or []
    return {"id": str(row["id"]), "pseudonym": _pseudonym(candidate),
            "role": profile.get("role") or None, "practises": topics[0] if topics else None}


def _match_of_take(database: Any, session: str) -> Optional[dict]:
    rows = _rows(_table(database, MATCHES).select("*").eq("session_id", session).limit(1))
    return rows[0] if rows else None


def suggest(database: Any, speaker_id: Any, session_id: Any) -> dict:
    """GET /v2/takes/<session_id>/match: {"match": {id, pseudonym, role,
    practises} | null}. The page after the Take comes back only with one;
    once sent or closed there is none. 404 when matching is off for the
    speaker or the Take is not theirs."""
    if not is_on(database, speaker_id):
        raise _not_found()
    speaker, session = str(speaker_id), _uuid(session_id)
    if not session:
        raise _not_found()
    held = _match_of_take(database, session)
    if held:
        mine = str(held["speaker_id"]) == speaker and held["status"] == "offered"
        return {"match": _offer(database, held) if mine else None}
    take = _take(database, speaker, session)
    if not take:
        raise _not_found()
    found = best(database, speaker, take)
    if not found:
        return {"match": None}
    row = _keep(database, speaker, session, found)
    return {"match": _offer(database, row) if row else None}


def _keep(database: Any, speaker: str, session: str, found: dict) -> Optional[dict]:
    try:
        rows = _rows(_table(database, MATCHES).insert({
            "session_id": session, "speaker_id": speaker,
            "candidate_id": found["candidate_id"], "arm": found["arm"],
            "fit": found["fit"], "shared_terms": found["terms"],
            "signals": found["signals"], "status": "offered"}))
    except Exception as e:
        if _UNIQUE_VIOLATION not in str(e):
            raise
        return _match_of_take(database, session)
    return rows[0] if rows else None


def _speakers(database: Any, speaker_id: Any, match_id: Any) -> dict:
    match = _uuid(match_id)
    rows = _rows(_table(database, MATCHES).select("*").eq("id", match)
                 .eq("speaker_id", str(speaker_id)).limit(1)) if match else []
    if not rows or not is_on(database, speaker_id):
        raise _not_found()
    return rows[0]


def send(database: Any, speaker_id: Any, match_id: Any, speaker_name: str) -> dict:
    """POST /v2/take-matches/<id>/send: the speaker sends the Take to the one
    suggested. Will's card reaches them; nothing else does. Sent again: the
    same answer. Closed or answered: 409."""
    row = _speakers(database, speaker_id, match_id)
    if row["status"] == "sent":
        return {"match": {"id": str(row["id"]), "status": "sent"}}
    if row["status"] != "offered":
        raise ChatsError("NOT_ALLOWED", "This suggestion is closed.", 409)
    _table(database, MATCHES).update({
        "status": "sent", "sent_at": _now(),
        "speaker_name": (speaker_name or "")[:120] or None}).eq("id", str(row["id"])).execute()
    _card(database, row)
    return {"match": {"id": str(row["id"]), "status": "sent"}}


def close(database: Any, speaker_id: Any, match_id: Any) -> dict:
    """POST /v2/take-matches/<id>/close: Not now. Nobody is told."""
    row = _speakers(database, speaker_id, match_id)
    if row["status"] == "offered":
        _table(database, MATCHES).update({"status": "closed", "closed_at": _now()}) \
            .eq("id", str(row["id"])).execute()
    return {"match": {"id": str(row["id"]), "status": "closed"
                      if row["status"] in ("offered", "closed") else row["status"]}}


def _from(database: Any, row: dict) -> dict:
    """The speaker as the candidate sees them: a pseudonym and a description."""
    speaker = str(row["speaker_id"])
    profile = _profiles(database, [speaker]).get(speaker, {})
    take = _take(database, speaker, str(row["session_id"])) or {}
    return {"pseudonym": _pseudonym(speaker), "role": profile.get("role") or None,
            "about": topic_of(take) or None}


def _card(database: Any, row: dict) -> None:
    """Will's card in the candidate's chat with Will (N478): the speaker's
    pseudonym, their description and what the Take is about; the app shows
    "Open Take" under it. Kept with the speaker (about_user_id), so it goes
    with either account."""
    who = _from(database, row)
    database.insert_lounge_messages(str(row["candidate_id"]), [{
        "client_id": str(uuid.uuid5(_NAMESPACE, f"card:{row['id']}")),
        "role": "bot", "kind": "text",
        "body": COPY["card"].format(pseudonym=who["pseudonym"]),
        "metadata": {"card": CARD, "match": str(row["id"]), **who},
        "client_created_at": _now(), "about_user_id": str(row["speaker_id"])}])


# ── The candidate's side ─────────────────────────────────────────────────

def _candidates(database: Any, candidate_id: Any, match_id: Any) -> dict:
    """The candidate's own suggestion once it was sent to them; else 404."""
    match = _uuid(match_id)
    rows = _rows(_table(database, MATCHES).select("*").eq("id", match)
                 .eq("candidate_id", str(candidate_id)).limit(1)) if match and candidate_id else []
    if not rows or rows[0]["status"] not in ("sent", "answered"):
        raise _not_found()
    return rows[0]


def view(database: Any, candidate_id: Any, match_id: Any) -> dict:
    """GET /v2/take-matches/<id>: the Take as the candidate opens it: who it
    is from (pseudonym, description), what it is about, its words slide by
    slide and each slide's start, its length; whether they answered."""
    row = _candidates(database, candidate_id, match_id)
    take = _take(database, str(row["speaker_id"]), str(row["session_id"])) or {}
    parts = _parts(take)
    starts = []
    for p in parts:
        try:
            starts.append(max(0, int(p.get("start_offset_ms") or 0)))
        except (TypeError, ValueError):
            starts.append(0)
    return {"match": {"id": str(row["id"]), "status": row["status"], **_from(database, row),
                      "words": said(take) or None, "slides": starts,
                      "duration_ms": _length(database, row)}}


def _recording_row(database: Any, row: dict) -> Optional[dict]:
    return _take_of(database, str(row["speaker_id"]), str(row["session_id"]))


def _length(database: Any, row: dict) -> Optional[int]:
    try:
        return int((_recording_row(database, row) or {}).get("duration") or 0) * 1000 or None
    except (TypeError, ValueError):
        return None


def recording(database: Any, candidate_id: Any, match_id: Any) -> dict:
    """GET /v2/take-matches/<id>/recording: the Take's voice, for the
    candidate; 404 once its owner deleted it."""
    row = _candidates(database, candidate_id, match_id)
    key = str((_recording_row(database, row) or {}).get("storage_path") or "")
    if not key:
        raise _not_found()
    from services.lab_audio_storage import get_lab_audio_bytes
    from services.training_import import content_type_for
    try:
        audio = get_lab_audio_bytes(key)
    except Exception:
        logger.warning("take_match: the Take's recording could not be read (match %s)", row["id"])
        raise _not_found()
    return {"content_type": content_type_for(key), "audio": audio}


def answer(database: Any, candidate_id: Any, match_id: Any, take: Any,
           duration_ms: Any, candidate_name: str) -> dict:
    """POST /v2/take-matches/<id>/answer: the candidate's answer, a Take of
    theirs recorded in the official recorder after the suggestion reached
    them (N481 item 1). Only now is the chat between the two made (N478):
    the speaker's Take as the speaker's own Take message, then the answer,
    under their names; {"chat": {"id"}}. Answered again: the same chat."""
    row = _candidates(database, candidate_id, match_id)
    if row["status"] == "answered" and row.get("thread_id"):
        return {"chat": {"id": str(row["thread_id"])}}
    session = _uuid(take)
    if not session or not _take_of(database, str(candidate_id), session):
        raise _not_found()
    if not _recorded_after(database, session, row.get("sent_at")):
        raise ChatsError("NOT_ALLOWED", "An answer is a Take recorded after it reached you.")
    from services.chat_links import open_pair
    speaker = str(row["speaker_id"])
    thread = open_pair(database, [
        {"user_id": speaker, "display_name": row.get("speaker_name") or _pseudonym(speaker)},
        {"user_id": str(candidate_id), "display_name": candidate_name or "WillpowerLab"}],
        row.get("speaker_name") or _pseudonym(speaker))
    _post_take(database, row, thread)
    post_answer(database, candidate_id, thread, session, duration_ms, 0)
    _table(database, MATCHES).update({
        "status": "answered", "answered_at": _now(), "answer_session_id": session,
        "thread_id": thread}).eq("id", str(row["id"])).execute()
    return {"chat": {"id": thread}}


def _recorded_after(database: Any, session: str, sent_at: Any) -> bool:
    """Whether the Take ``session`` was recorded once the suggestion was
    sent: an older Take is not an answer to it."""
    rows = _rows(_table(database, SESSIONS).select("created_at").eq("id", session).limit(1))
    made = _when(rows[0].get("created_at")) if rows else None
    sent = _when(sent_at)
    return bool(made and sent and made >= sent)


def _when(value: Any) -> Optional[datetime]:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _post_take(database: Any, row: dict, thread: str) -> None:
    """The speaker's Take in the new chat, as their own Take message (kind
    ``take``, the same message a Take sent to a list is, so both open it the
    same way: services/take_sends.py), once: its id is uuid5 of the Take and
    the chat, as there. No push: the one who answered is the only other."""
    from services import take_sends
    speaker = str(row["speaker_id"])
    seat = _rows(_table(database, MEMBERS).select("id").eq("thread_id", thread)
                 .eq("user_id", speaker).limit(1))
    if not seat:
        raise ChatsError("NOT_SAVED", "Could not open the chat.", 503)
    take = take_sends._the_take(database, speaker, str(row["session_id"]))
    message = str(uuid.uuid5(uuid.UUID(take["session"]), thread))
    if _rows(_table(database, MESSAGES).select("id").eq("id", message).limit(1)):
        return
    try:
        _rows(_table(database, MESSAGES).insert({
            "id": message, "thread_id": thread, "author_member_id": str(seat[0]["id"]),
            "kind": "take", "body": "",
            "meta": {"take_session_id": take["session"], "take_index": take["index"],
                     "project_title": take["project_title"],
                     "duration_ms": take["duration_ms"], "match": str(row["id"])}}))
    except Exception as e:
        if _UNIQUE_VIOLATION not in str(e):
            raise
