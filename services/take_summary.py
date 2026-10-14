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

Cheeky and curious (founder 2026-10-14): the bubble now also knows the
talk's title and slide topics, what the speaker said, and their most
willfident moment. It praises through one SIGNED line (``line_bank``),
lightly varied at most, checked in code; it gives no advice (the walk
did) and ends with a question back to the speaker. If they have no
WhatsApp number yet, the Lounge's own WhatsApp offer follows the bubble.

Anything that fails (no permit, no provider, a reply that breaks the
rules or drifts from the signed lines) falls back to the signed journey
copy, so the speaker always gets the bubble. Stored once per Take (a
fixed client id).

A coach update: when a coach shares a word on a Take whose summary is
already stored (``coach_update``, called from the coach's share), or the
walk's summary step brings a coach note the stored summary was not written
with, the summary is written again with it and rewrites the bubble in place;
the earlier words stay in its metadata (``earlier``), one tap away in the
Lounge. The practice result and helper words it was first written with are
kept in its metadata, so a rewrite hears them too.
"""
from __future__ import annotations

import hashlib
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
#: A signed later-line names its Take; that is the one number allowed.
_TAKE_NUMBER = re.compile(r"\bTake \d+\b")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
#: How close a sentence must be to a signed line (shared words).
_NEAR = 0.5
_MAX_CHARS = 420

_SYSTEM = (
    "You are Will, a speaking coach and a curious, cheeky colleague. Write "
    "one short chat message to a speaker right after they reviewed a "
    "recording of their talk. 2 to 4 short sentences, like a friend at "
    "work: 'you', contractions, playful and warm. Exclamation marks are "
    "fine; at most one emoji.\n"
    "- Use exactly one of the SIGNED LINES below for the praise, word for "
    "word or with a light touch. Never write other praise.\n"
    "- Make it about their talk: name the talk or one slide topic.\n"
    "- If what they said seems to wander from the talk's title, ask about "
    "it with curiosity, never as a correction.\n"
    "- Give no feedback and no advice: their walk already did that.\n"
    "- End with one question back to them: how it went, whether they like "
    "it, another Take, or anything they want to tell you.\n"
    "- Speak only to what this Take showed about whether they can do "
    "this; never judge them as a person, their self-esteem or their worth.\n"
    "Never use numbers (a Take number inside a signed line is the one "
    "exception), scores, percentages, verdicts, the words 'cue' or "
    "'willfidence', or names of measurements. Only say what the facts "
    "support. If there is no earlier take, claim no progress."
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


def _words(text: str) -> set:
    return set(re.findall(r"[a-z']+", text.lower()))


def _near_signed(sentences: list[str], lines: list[str]) -> bool:
    """Some sentence shares most of its words with a signed line. Pure."""
    for line in lines:
        signed = _words(line)
        for sentence in sentences:
            said = _words(sentence)
            if signed and said and len(signed & said) / len(signed | said) >= _NEAR:
                return True
    return False


def _clean(text: Optional[str], lines: Optional[list[str]] = None,
           names: tuple = ()) -> Optional[str]:
    """The reply, if it keeps the rules: 2-4 short sentences, no number
    (but a signed line's Take number, or one inside the talk's own title
    or slide names) or banned word, at most one emoji and, when signed
    lines were given, one of them said near-verbatim. Else None."""
    if not text:
        return None
    body = " ".join(text.strip().strip('"').split())
    sentences = [s for s in re.split(r"(?<=[.?!])\s+", body) if s]
    if not 2 <= len(sentences) <= 4 or len(body) > _MAX_CHARS:
        return None
    checked = _TAKE_NUMBER.sub("Take", body)
    for name in sorted((n for n in names if n), key=len, reverse=True):
        checked = checked.replace(name, "")
    if _BANNED.search(checked) or len(_EMOJI.findall(body)) > 1:
        return None
    if lines and not _near_signed(sentences, lines):
        return None
    return body


def write_summary(anchor: str, facts: list[str], *, practice: Optional[str],
                  helper_words: list[str], coach_note: Optional[str],
                  session_id: str, arc_id: str, user_id: str,
                  signed: Optional[list[str]] = None,
                  names: tuple = ()) -> Optional[str]:
    from services.llm import chat_complete
    from services.llm_config import SPEC_TAKE_SUMMARY
    lines = [f"The usual message for this point (use its spirit, not its words): {anchor}"]
    if signed:
        lines += ["SIGNED LINES (use exactly one):"] + [f"- {s}" for s in signed]
    lines += ["Facts:"] + [f"- {f}" for f in facts]
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
    return _clean(getattr(result, "text", None) if result else None, signed, names)


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


def _note_key(note: Optional[str]) -> Optional[str]:
    return hashlib.sha256(note.encode("utf-8")).hexdigest()[:16] if note else None


def _heard_before(held: Optional[dict], note: Optional[str]) -> bool:
    """The stored summary already hears this note (or there is none to
    hear). A summary stored before the note key was kept counts its note
    as heard. Pure."""
    if not held or note is None:
        return bool(held)
    meta = held.get("metadata") or {}
    if meta.get("coach_note_key"):
        return meta["coach_note_key"] == _note_key(note)
    return bool(meta.get("coach_noted"))


def _written(database: Any, take: str, anchor: str, facts: list[str], practice: Optional[str],
             words: list[str], note: Optional[str], arc_id: str, user_id: str,
             signed: Optional[list[str]] = None, names: tuple = ()) -> Optional[str]:
    """GPT-4o's summary under the Take's authority; None when refused or failed."""
    try:
        return _under_authority(database, take, lambda: write_summary(
            anchor, facts, practice=practice, helper_words=words, coach_note=note,
            session_id=take, arc_id=arc_id, user_id=user_id, signed=signed,
            names=names))
    except Exception as error:  # noqa: BLE001 -- refused or failed: the signed copy
        logger.warning("take summary refused take=%s: %s", take, error, exc_info=True)
        return None


_SAID_CHARS = 1500
_MOMENT_CHARS = 300


def talk_names(takes: list[dict]) -> tuple:
    """The talk's title and slide topics, from its Takes' intake. Pure."""
    from services.chat_app_context import slide_topics, talk_title
    contexts = [t.get("intake_context") or {} for t in takes]
    return (talk_title(contexts), *slide_topics(contexts))


def talk_facts(takes: list[dict]) -> list[str]:
    """The talk's title and slide topics as facts. Pure."""
    from services.chat_app_context import slide_topics, talk_title
    contexts = [t.get("intake_context") or {} for t in takes]
    facts = []
    title = talk_title(contexts)
    if title:
        facts.append(f'The talk is called "{title}".')
    topics = slide_topics(contexts)
    if topics:
        facts.append("Its slides, in order: " + " | ".join(topics) + ".")
    return facts


def _moments(database: Any, take: str) -> list[dict]:
    """This Take's moments as text ({ref, text}); [] when unread."""
    try:
        from services.willfidence import moments_text
        frame = database.get_v4_dark_frame(take)
        if not isinstance(frame, dict):
            return []
        return moments_text(frame, database.get_snippets_by_session(take) or [])
    except Exception as error:  # noqa: BLE001 -- the summary stands without it
        logger.warning("take summary moments unread take=%s: %s", take, error, exc_info=True)
        return []


def said_facts(moments: list[dict], now: list[dict]) -> list[str]:
    """What the speaker said, and their most willfident moment. Pure."""
    said = " ".join(m["text"] for m in moments if m.get("text")).strip()
    facts = [f"What they said this Take: {said[:_SAID_CHARS]}"] if said else []
    rated = [r for r in now if isinstance(r.get("willfident"), (int, float))]
    best = max(rated, key=lambda r: r["willfident"], default=None)
    text = next((m["text"] for m in moments
                 if best and m.get("ref") == str(best.get("block_id")) and m.get("text")), "")
    if text:
        facts.append(f"Their most confident moment this Take: \"{text[:_MOMENT_CHARS]}\"")
    return facts


def signed_lines(now: list[dict], before: Optional[list[dict]], take_index: int) -> list[str]:
    """The signed praise lines this Take may use (``line_bank``): the bank
    for what carried it (the voice or the words), the gentle general bank,
    and, from Take 2 on when the voice rose, the signed later-line. Rotated
    by the Take so a speaker does not hear the same line twice. Pure."""
    from services import line_bank
    voice, words = _mean(now, "s"), _mean(now, "w")
    lead = "B07" if (words or 0) > (voice or 0) else "B01"
    picks = []
    for bank in (lead, "B09"):
        options = line_bank.BANKS[bank]
        picks += [options[(take_index + i) % len(options)] for i in range(2)]
    if before is not None and _move(voice, _mean(before, "s")) == "rose":
        picks.append(line_bank.later_line("B01", take_index - 1))
    return picks


def _whatsapp_offer(database: Any, user_id: str, client_id: str, at: str) -> list[dict]:
    """The Lounge's WhatsApp offer after the bubble, when the speaker has
    no number yet (founder 2026-10-14); [] otherwise."""
    from services.whatsapp_notify import whatsapp_state
    if whatsapp_state(database, user_id).get("phone"):
        return []
    from services.chat_app_context import OFFER_PROMPTS
    return [{"client_id": str(uuid.uuid5(_NAMESPACE, f"{client_id}:whatsapp")),
             "role": "bot", "kind": "text", "body": OFFER_PROMPTS["whatsapp"],
             "metadata": {"offer": "whatsapp"}, "client_created_at": at}]


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
    if held and _heard_before(held, note):
        return held
    if held:
        first = held.get("metadata") or {}
        practice = practice or (first.get("practice") if first.get("practice") in ("better", "not_yet") else None)
        words = words or [w for w in (first.get("helper_words") or []) if isinstance(w, str)][:2]
    anchor = _COPY.get(take_index) or _COPY[3]
    now, before = _reads(database, ids, take_index)
    facts = (talk_facts(takes) + said_facts(_moments(database, take), now)
             + progress_facts(now, before))
    text = _written(database, take, anchor, facts, practice, words,
                    note, str(arc_id), str(user_id),
                    signed=signed_lines(now, before, take_index),
                    names=talk_names(takes))
    meta = {"summary": True, "arc_id": str(arc_id), "take_index": take_index,
            "take_session_id": take, "written": bool(text), "coach_noted": note is not None,
            "coach_note_key": _note_key(note), "practice": practice, "helper_words": words}
    if held:
        if not text:
            return held  # the coach's update could not be written: keep it
        meta.update({"coach_update": True, "earlier": held.get("body")})
        return database.rewrite_lounge_message(str(user_id), client_id, text, meta) or held
    at = datetime.now(timezone.utc).isoformat()
    persisted = database.insert_lounge_messages(str(user_id), [{
        "client_id": client_id,
        "role": "bot",
        "kind": "cadence",
        "body": text or anchor,
        "metadata": meta,
        "client_created_at": at,
    }] + _whatsapp_offer(database, str(user_id), client_id, at))
    return persisted[0] if persisted else None


def _rewrite_for_coach(database: Any, take: str, note: str) -> None:
    session = database.v2_get_session_by_id(take) or {}
    user_id, arc_id = session.get("user_id"), session.get("arc_id")
    if not user_id or not arc_id:
        return
    from services.slide_selection import spoken_arc_sessions
    takes = [s for s in spoken_arc_sessions(database.takes.get_arc_sessions(str(arc_id)))
             if s.get("analysis_state") in (None, "ready")]
    ids = [str(t.get("id")) for t in takes]
    if take not in ids:
        return
    client_id = summary_client_id(user_id, arc_id, ids.index(take) + 1)
    if not database.get_lounge_message_by_client_id(str(user_id), client_id):
        return  # not reviewed yet: the walk's summary hears the note
    summary_message(database, user_id=str(user_id), arc_id=str(arc_id), takes=takes,
                    take_session_id=take, body={"coach_note": note})


def coach_update(database: Any, take_session_id: str, note: Optional[str]) -> None:
    """A coach shared a word on a Take: its stored summary is written again
    with it, in place, behind the coach's save. Best-effort, never blocks
    and never raises; a Take not reviewed yet is left to the walk."""
    note = note.strip() if isinstance(note, str) else ""
    if not note:
        return
    take = str(take_session_id)

    def run() -> None:
        try:
            _rewrite_for_coach(database, take, note)
        except Exception as error:  # noqa: BLE001 -- the word is shared either way
            logger.warning("take summary coach update failed take=%s: %s", take, error,
                           exc_info=True)

    try:
        from services.parallel import start_scoped_thread
        start_scoped_thread(run, name="take-summary-coach-update")
    except Exception as error:  # noqa: BLE001 -- the word is shared either way
        logger.warning("take summary coach update not started take=%s: %s", take, error)


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


def line_bank_lines() -> set:
    """Every signed line and later-line text, for checks. Pure."""
    from services import line_bank
    lines = {line for bank in line_bank.BANKS.values() for line in bank}
    return lines | set(line_bank.LATER.values())
