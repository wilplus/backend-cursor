"""Matching people after a Take (founder, the Claude Code chat, 4 November
2026, N477, N478 and N481; drawn on the prototype
https://claude.ai/artifact/FtJL4G1VGm1MTNMKWujZ6W). Table: take_matches
(migration a_take_can_reach_someone_new_after_it).

People are matched in one place only: after a Take, when someone new fits
it (N477). This module finds that one person, keeps what came of it, and
makes the chat between the two only when that person answers (N478):

  * ``suggest``  for the speaker, after the walk: one person who shares one
    of their communities, is a member (N471), has no chat with them, was
    never suggested to them before, recorded a Take lately and is not
    already asked enough; who fits the Take best (N481 item 2). Knowledge
    first, by its words, both ways, rare words weighing most
    (``take_match_knowledge``): what the candidate knows (their profile)
    and practises (their Takes' topics, never shown) against what the Take
    needs, and what the speaker knows against what the candidate
    practises; then, once skills are on (``take_match_signals``), speaking
    skills by the experiment's arm (a similar level, or further along,
    N481 item 3) and progress alike. Mostly the best, now and then the
    second or third, each pick's chance kept. A pseudonym made for this
    match and their role, never a name. One per Take; none when nobody
    knows enough.
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

import hashlib
import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
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
#: The spans used until enough people are read to measure how far apart
#: they are (``SPREAD_FROM``); then twice that spread, within bounds.
FURTHER_BY, SKILL_SPAN, PACE_SPAN = 0.15, 0.3, 0.05
SPREAD_FROM = 8
#: How many Takes' worth a person's skills are pulled toward everyone's
#: average, so a person with one or two Takes is not judged on them alone.
SKILL_PRIOR = 3
#: Proposed, for the founder (audit, 4 November 2026): only someone who
#: recorded a Take in the last ``ACTIVE_DAYS``; at most ``OPEN_CAP`` Takes
#: waiting for their answer and ``WEEK_CAP`` suggestions in seven days.
ACTIVE_DAYS, OPEN_CAP, WEEK_CAP = 14, 3, 5
#: The pick: the best, or now and then the second or third, with these
#: chances, each kept with the suggestion (its propensity).
EXPLORE = (0.8, 0.1, 0.1)
#: Ids per read, as ``db._chunks``; the most community members read; how
#: many topics are kept per person.
CHUNK, MAX_POOL, TOPICS_EACH = 100, 2000, 10
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


def _pseudonym(user_id: str, match_id: Any) -> str:
    """A name for this person in this one match only: never the name the
    blind coach queue or an email gives them, and another in the next match,
    so a pseudonym cannot be followed from one place to another (audit,
    4 November 2026)."""
    from services.coach_pseudonym import coach_pseudonym
    return coach_pseudonym(f"take_match:{match_id}:{user_id}")


# ── Who could it be ──────────────────────────────────────────────────────

def _chunks(ids: list[str]) -> list[list[str]]:
    """Lists of ids at most ``CHUNK`` long: a longer one makes a read's
    address too long (``db._chunks``, the same size)."""
    return [ids[i:i + CHUNK] for i in range(0, len(ids), CHUNK)]


def pool(database: Any, speaker_id: str) -> list[str]:
    """Everyone who shares a community with the speaker (a private one: the
    general community has no member rows), minus whoever already has a chat
    with them and whoever was suggested to them before; read in id order, so
    a very large community is cut the same way every time, and sorted."""
    communities = [str(r["community_id"]) for r in _rows(
        _table(database, COMMUNITY_MEMBERS).select("community_id")
        .eq("user_id", speaker_id).limit(MAX_ROWS))]
    people: set[str] = set()
    for part in _chunks(sorted(set(communities))):
        people |= {str(r["user_id"]) for r in _rows(
            _table(database, COMMUNITY_MEMBERS).select("user_id")
            .in_("community_id", part).order("user_id").limit(MAX_POOL)) if r.get("user_id")}
    if len(people) >= MAX_POOL:
        logger.warning("take_match: the pool of %s is cut at %s people", speaker_id, MAX_POOL)
    return sorted(people - _in_chats_with(database, speaker_id)
                  - _suggested_before(database, speaker_id) - {speaker_id})


def _in_chats_with(database: Any, user_id: str) -> set[str]:
    threads = [str(r["thread_id"]) for r in _rows(
        _table(database, MEMBERS).select("thread_id").eq("user_id", user_id).limit(MAX_ROWS))]
    out: set[str] = set()
    for part in _chunks(threads):
        out |= {str(r["user_id"]) for r in _rows(
            _table(database, MEMBERS).select("user_id").in_("thread_id", part)) if r.get("user_id")}
    return out


def _suggested_before(database: Any, user_id: str) -> set[str]:
    return {str(r["candidate_id"]) for r in _rows(
        _table(database, MATCHES).select("candidate_id").eq("speaker_id", user_id)
        .limit(MAX_ROWS))}


def _since(days: int) -> str:
    moment = _when(_now()) or datetime.now(timezone.utc)
    return (moment - timedelta(days=days)).isoformat()


def _busy(database: Any, ids: list[str]) -> set[str]:
    """Who has enough already (audit, 4 November 2026): ``OPEN_CAP`` Takes
    sent to them and not yet answered, or ``WEEK_CAP`` suggestions in the
    last seven days, from anyone."""
    week = _since(7)
    open_now: dict[str, int] = {}
    recent: dict[str, int] = {}
    for part in _chunks(ids):
        for r in _rows(_table(database, MATCHES).select("candidate_id,status,offered_at")
                       .in_("candidate_id", part).in_("status", ["offered", "sent"])
                       .limit(CHUNK * (WEEK_CAP + OPEN_CAP))):
            who = str(r["candidate_id"])
            if r.get("status") == "sent":
                open_now[who] = open_now.get(who, 0) + 1
            if str(r.get("offered_at") or "") >= week:
                recent[who] = recent.get(who, 0) + 1
    return ({w for w, n in open_now.items() if n >= OPEN_CAP}
            | {w for w, n in recent.items() if n >= WEEK_CAP})


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
    out: dict[str, dict] = {}
    for part in _chunks(ids):
        out.update({str(r["user_id"]): r for r in _rows(
            _table(database, PROFILES).select("user_id,name,role,about").in_("user_id", part))})
    return out


def _activity(database: Any, ids: list[str]) -> tuple[dict[str, list[str]], dict[str, str]]:
    """What each person practises (the topics of their newest Takes, never
    shown to anyone) and when they last recorded one. Read in parts, a fair
    share of rows for each part, so the busiest people cannot crowd out the
    quiet ones."""
    topics: dict[str, list[str]] = {}
    last: dict[str, str] = {}
    for part in _chunks(ids):
        for row in _rows(_table(database, SESSIONS).select("user_id,intake_context,created_at")
                         .in_("user_id", part).order("created_at", desc=True)
                         .limit(CHUNK * TOPICS_EACH)):
            who = str(row["user_id"])
            last.setdefault(who, str(row.get("created_at") or ""))
            topic = topic_of(row)
            mine = topics.setdefault(who, [])
            if topic and topic not in mine and len(mine) < TOPICS_EACH:
                mine.append(topic)
    return topics, last


def _knows(profile: dict) -> str:
    return f"{profile.get('role') or ''} {profile.get('about') or ''}"


def draw_arm() -> str:
    """The experiment's arm for one suggestion, at random (N481 item 3)."""
    return random.choice(SKILL_ARMS)


def closeness(gap: Optional[float], target: float, span: float) -> float:
    """1 when ``gap`` is ``target``, down to 0 at ``span`` away; a half when
    it is not known yet. Pure."""
    if gap is None:
        return 0.5
    return max(0.0, 1.0 - abs(gap - target) / span)


def weigh(arm: str, knowledge: float, speaker: dict, candidate: dict,
          spans: tuple[float, float] = (0.0, 0.0)) -> tuple[float, dict]:
    """A candidate's whole fit in ``arm`` and what made it (N481 item 2):
    knowledge, speaking skills by the arm, progress alike; the profiles'
    distance is kept beside it for the style arms. Never shown. Pure."""
    skill_span, pace_span = spans[0] or SKILL_SPAN, spans[1] or PACE_SPAN

    def gap(key: str) -> Optional[float]:
        a, b = speaker.get(key), candidate.get(key)
        return None if a is None or b is None else round(b - a, 4)
    skill = closeness(gap("skill"), FURTHER_BY if arm == "further_along" else 0.0, skill_span)
    pace = closeness(gap("pace"), 0.0, pace_span)
    made = {"knowledge": knowledge, "skill": round(skill, 4), "pace": round(pace, 4),
            "skill_gap": gap("skill"), "pace_gap": gap("pace"),
            "profile_distance": signals.profile_distance(speaker.get("profile") or {},
                                                         candidate.get("profile") or {})}
    return round(knowledge + SKILL_WEIGHT * skill + PACE_WEIGHT * pace, 4), made


def _spread(values: list[float], low: float, high: float, default: float) -> float:
    """A span from how far apart people are (twice the spread), held between
    ``low`` and ``high``; ``default`` with fewer than ``SPREAD_FROM`` people."""
    if len(values) < SPREAD_FROM:
        return default
    mean = sum(values) / len(values)
    sd = (sum((v - mean) ** 2 for v in values) / (len(values) - 1)) ** 0.5
    return max(low, min(high, 2 * sd))


def _steady(reads: dict[str, dict]) -> tuple[dict[str, dict], tuple[float, float]]:
    """Each person's skills pulled toward everyone's average by how few Takes
    they have (``SKILL_PRIOR`` Takes' worth), and the two spans from the
    people read. The progress is already steadied (``signals.of``)."""
    known = [r for r in reads.values() if r.get("skill") is not None]
    mean = (sum(r["skill"] for r in known) / len(known)) if known else None
    out = {}
    for who, r in reads.items():
        n = int(r.get("takes") or 0)
        skill = r.get("skill")
        if skill is not None and mean is not None:
            skill = (n * skill + SKILL_PRIOR * mean) / (n + SKILL_PRIOR)
        out[who] = {**r, "skill": skill}
    spans = (_spread([r["skill"] for r in out.values() if r.get("skill") is not None],
                     0.1, 0.5, SKILL_SPAN),
             _spread([r["pace"] for r in out.values() if r.get("pace") is not None],
                     0.02, 0.1, PACE_SPAN))
    return out, spans


def _ranked(fits: list[dict[str, Any]], session: str, key: str = "fit") -> list[dict[str, Any]]:
    """Highest first; a tie goes the same way for the same Take, but not
    always to the same person (audit, 4 November 2026)."""
    def tie(f: dict) -> str:
        return hashlib.sha256(f"{session}:{f['candidate_id']}".encode()).hexdigest()
    return sorted(fits, key=lambda f: (-f[key], tie(f)))


def _with_skills(database: Any, speaker_id: str, fits: list[dict[str, Any]],
                 session: str) -> None:
    """Weigh skills and progress into each fit, in the arm drawn for this
    Take, and note whether the other arm would have chosen someone else
    (only those Takes tell the arms apart)."""
    arm = draw_arm()
    other = SKILL_ARMS[1 - SKILL_ARMS.index(arm)]
    reads, spans = _steady(signals.of(database, [speaker_id] + [f["candidate_id"] for f in fits]))
    for f in fits:
        f["other_fit"], _made = weigh(other, f["fit"], reads[speaker_id],
                                      reads[f["candidate_id"]], spans)
        f["fit"], f["signals"] = weigh(arm, f["fit"], reads[speaker_id],
                                       reads[f["candidate_id"]], spans)
        f["arm"] = arm
    first, first_other = _ranked(fits, session)[0], _ranked(fits, session, "other_fit")[0]
    for f in fits:
        f["signals"]["other_arm_differs"] = first is not first_other
        f["signals"]["spans"] = [round(spans[0], 4), round(spans[1], 4)]


def _pick(fits: list[dict[str, Any]], session: str) -> dict[str, Any]:
    """One of the best few, mostly the best (``EXPLORE``), by a draw seeded
    with the Take, and how likely that pick was: so later another way of
    matching can be judged on what this one did (audit, 4 November 2026)."""
    top = _ranked(fits, session)[:len(EXPLORE)]
    chances = [p / sum(EXPLORE[:len(top)]) for p in EXPLORE[:len(top)]]
    roll = random.Random(int(hashlib.sha256(session.encode()).hexdigest(), 16)).random()
    at = 0
    while at < len(top) - 1 and roll >= sum(chances[:at + 1]):
        at += 1
    chosen = top[at]
    chosen["signals"] = {**chosen.get("signals", {}), "rank": at + 1,
                         "propensity": round(chances[at], 4),
                         "top_fits": [f["fit"] for f in top]}
    return chosen


def best(database: Any, speaker_id: str, take: dict) -> Optional[dict]:
    """The one person suggested for the Take, or None: {"candidate_id",
    "fit", "terms", "arm", "signals"}. Only a member (N471) who recorded a
    Take in the last ``ACTIVE_DAYS`` and is not already asked enough
    (``_busy``), and who knows enough of what it needs (``MIN_FIT``, rare
    words weighing most: services/take_match_knowledge.py); then, once
    skills are on, skills and progress too."""
    from services import membership
    from services import take_match_knowledge as knowledge
    session = str(take.get("id") or "")
    wanted = knowledge.take_words(topic_of(take), said(take))
    people = pool(database, speaker_id) if wanted else []
    if not people:
        return None
    topics, last = _activity(database, people)
    profiles = _profiles(database, people + [speaker_id])
    # Every word's weight is read among everyone the speaker shares a
    # community with, so a word is rare or common there, not just among
    # the few who may be asked today.
    knows = {p: knowledge.counts(_knows(profiles.get(p, {}))) for p in people}
    practises = {p: knowledge.counts(" ".join(topics.get(p, []))) for p in people}
    weight, _n = knowledge.weights(set(knows[p]) | set(practises[p]) for p in people)
    average_know = sum(sum(c.values()) for c in knows.values()) / len(people)
    average_practise = sum(sum(c.values()) for c in practises.values()) / len(people)
    speaker_knows = set(knowledge.counts(_knows(profiles.get(speaker_id, {}))))
    active = _since(ACTIVE_DAYS)
    people = [p for p in people if last.get(p, "") >= active]
    busy = _busy(database, people)
    people = [p for p in people if p not in busy]
    fits: list[dict[str, Any]] = []
    for uid in people:
        score, terms = knowledge.score(wanted, knows[uid], practises[uid], speaker_knows,
                                       weight, average_know, average_practise)
        if score >= MIN_FIT and membership.is_member(database, uid):
            fits.append({"candidate_id": uid, "fit": score, "terms": terms,
                         "arm": "topics", "signals": {"knowledge": score}})
    if not fits:
        return None
    if signals.is_on():
        _with_skills(database, speaker_id, fits, session)
    return _pick(fits, session)


# ── The speaker's side ───────────────────────────────────────────────────

def _offer(database: Any, row: dict) -> dict:
    """A suggestion as the speaker sees it: a pseudonym and the role from
    their profile. Never what their own Takes are about: those are their
    private practice (audit, 4 November 2026)."""
    candidate = str(row["candidate_id"])
    profile = _profiles(database, [candidate]).get(candidate, {})
    return {"id": str(row["id"]), "pseudonym": _pseudonym(candidate, row["id"]),
            "role": profile.get("role") or None}


def _match_of_take(database: Any, session: str) -> Optional[dict]:
    rows = _rows(_table(database, MATCHES).select("*").eq("session_id", session).limit(1))
    return rows[0] if rows else None


def suggest(database: Any, speaker_id: Any, session_id: Any) -> dict:
    """GET /v2/takes/<session_id>/match: {"match": {id, pseudonym, role} |
    null}. The page after the Take comes back only with one;
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
    return {"pseudonym": _pseudonym(speaker, row["id"]), "role": profile.get("role") or None,
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
        {"user_id": speaker, "display_name": row.get("speaker_name") or _pseudonym(speaker, row["id"])},
        {"user_id": str(candidate_id), "display_name": candidate_name or "WillpowerLab"}],
        row.get("speaker_name") or _pseudonym(speaker, row["id"]))
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
