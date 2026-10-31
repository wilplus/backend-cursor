"""The closing summary after a Take's review (founder lock 2026-10-12,
moment and feedback chat, section 3).

One plain bubble, one or two short sentences (founder 2026-10-21, N94:
"make it shorter and only a cheeky summary of the take"), written by GPT-4o
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

Cheeky (founder 2026-10-14; only cheeky since 2026-10-21, N94): the bubble
knows the talk's title and slide topics, what the speaker said, and their
most willfident moment. It praises through one SIGNED line of one sentence
(``line_bank``), lightly varied at most, checked in code; it gives no
advice (the walk did), no greeting and asks nothing, not even about the
content: Will's own question comes after it in the chat, behind a bridge
line (``after_take.BRIDGE``). It never names the next step (N89).

The chain after it (``after_take``): the asks one at a time, then the
closing message. Will's question is planned before the summary is written
(``_will_plan``), its heard call running beside the summary's own; when this
Take says the clearer line practised on the last one, the summary is told.

Anything that fails (no permit, no provider, a reply that breaks the
rules or drifts from the signed lines) falls back to the signed journey
copy, so the speaker always gets the bubble. Stored once per Take (a
fixed client id).

A coach update: when a coach shares a word on a Take whose summary is
already stored (``coach_update``, called from the coach's share), or the
walk's summary step brings a coach note the stored summary was not written
with, the summary is written again with it and rewrites the bubble in place;
the summary as first written stays in its metadata (``earlier``), one tap
away in the Lounge, however many coach notes follow (founder 2026-10-19,
N80). The practice result and helper words it was first written with are
kept in its metadata, so a rewrite hears them too. A new or removed video
with the same words rewrites nothing: the rewrite is keyed on the note.
"""
from __future__ import annotations

import hashlib
import logging
import re
import uuid
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
#: What may follow the last mark besides an emoji: spaces, the arrow.
_TAIL = " \u2b07\ufe0f\u200d"
#: How close a sentence must be to a signed line (shared words).
_NEAR = 0.5
#: A last sentence that names the next step (N89: the chain brings it).
_NEXT_STEP = re.compile(r"\brecord(ing)?\b|\bnext (take|one)\b|\bkeep practi[sc]ing\b", re.I)
#: One or two short sentences, "at most about 140 characters" (founder
#: 2026-10-21, N94): the prompt asks for 140, the check allows a little more.
_MAX_CHARS = 160
_MAX_SENTENCES = 2
#: No greeting: the summary is the Take's, not a hello (founder 2026-10-21).
_GREETING = re.compile(r"^\W*(hey|hi|hello|hiya)\b", re.I)

_SYSTEM = (
    "You are Will, a speaking coach and a cheeky colleague. Write one short, "
    "cheeky chat message that sums up this take, right after the speaker "
    "reviewed it: one or two short sentences, at most 140 characters, like a "
    "friend at work: 'you', contractions, playful and warm. No greeting. "
    "Exclamation marks are fine; at most one emoji.\n"
    "- Use exactly one of the SIGNED LINES below for the praise, word for "
    "word or with a light touch. Never write other praise, and no pep talk.\n"
    "- Make it about this take of their talk: you may name the talk or one "
    "slide topic.\n"
    "- Only sum up the take. Ask nothing: no question at all, not about the "
    "content and not about the title (Will asks his own question after this "
    "message).\n"
    "- Give no feedback and no advice: their walk already did that.\n"
    "- Do not tell them what to do next and never mention recording the "
    "next take: Will brings that himself, after this message.\n"
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


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.?!])\s+", text.strip()) if s]


def _clean(text: Optional[str], lines: Optional[list[str]] = None,
           names: tuple = ()) -> Optional[str]:
    """The reply, if it keeps the rules: one or two short sentences (N94),
    no greeting, no question anywhere (Will asks his own after it), no
    number (but a signed line's Take number, or one inside the talk's own
    title or slide names) or banned word, at most one emoji, no next step
    and, when signed lines were given, one of them said near-verbatim.
    Else None."""
    if not text:
        return None
    body = " ".join(text.strip().strip('"').split())
    sentences = _sentences(body)
    if not 1 <= len(sentences) <= _MAX_SENTENCES or len(body) > _MAX_CHARS:
        return None
    if "?" in body or _GREETING.match(body):
        return None
    # The next step is Will's, after the chain of asks (founder 2026-10-20,
    # N89): a summary that sends them to record is the signed copy instead.
    if _NEXT_STEP.search(sentences[-1]):
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


def memory_facts(database: Any, user_id: str) -> list[str]:
    """What helps this speaker, from Will's private note
    (services.speaker_memory). Guidance only: never quoted. [] without one."""
    from services import speaker_memory
    note = speaker_memory.note_for(database, user_id)
    if not note:
        return []
    return ["What helps this speaker (a private note; let it shape what you focus "
            "on and ask, never quote it or repeat their answers): "
            + note.replace("\n", " ")]


def goal_facts(database: Any, user_id: str) -> list[str]:
    """The speaker's goal, in their own words (founder 2026-10-20: every
    summary says one thing about it, never a grade). [] without one."""
    try:
        goal = ((database.get_user_profile(user_id) or {}).get("goal") or "").strip()
    except Exception as error:  # noqa: BLE001 -- no goal: nothing to say about it
        logger.warning("take summary goal unread user=%s: %s", user_id, error, exc_info=True)
        return []
    if not goal:
        return []
    return [f"Their own goal, in their words (private, to steer by; never a grade): "
            f"\"{goal[:200]}\""]


#: How long the summary waits for the earlier Takes, at most (seconds).
_EARLIER_BUDGET = 1.0


def _query(moments: list[dict], words: list[str], takes: list[dict]) -> str:
    """The lookup's query (a summary has no question): the helper words,
    the talk's title and slides, then what they said this Take. Pure."""
    said = " ".join(str(m.get("text") or "") for m in moments)
    return " ".join([*words, *(n for n in talk_names(takes) if n), said])


def _when(take: dict) -> Optional[Any]:
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(take.get("created_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _older(takes: list[dict], take_index: int):
    """Which of the speaker's Takes are older than this one: the arc's Takes
    before it, and another project's Take recorded before it. Never this
    Take, never one after it. Pure."""
    ids = [str(t.get("id")) for t in takes]
    before, after = set(ids[:take_index - 1]), set(ids[take_index - 1:])
    at = _when(takes[take_index - 1])

    def older(take: dict) -> bool:
        tid = str(take.get("id"))
        if tid in before or tid in after:
            return tid in before
        then = _when(take)
        try:
            return bool(at and then and then < at)
        except TypeError:  # one carries a zone, the other not: leave it out
            return False
    return older


def _take_name(label: str) -> str:
    """The "Take 2" of "Take 2 transcript, slide 3": a slide number would
    trip the no-number rule, a Take number does not. Pure."""
    found = _TAKE_NUMBER.match(label or "")
    return found.group(0) if found else "an earlier Take"


def earlier_facts(snippets: list) -> list[str]:
    """What they said in older Takes (``speaker_lookup.earlier_takes``), as
    one private fact: guidance only. [] without any. The wording is
    drift-locked (services/prompts/pending.py)."""
    if not snippets:
        return []
    said = "; ".join(f'{_take_name(s.label)}: "{s.text}"' for s in snippets)
    return ["What they said in earlier Takes (private, to steer by; you may point "
            "back to one moment in a few of their own words, never more): " + said]


def earlier_lookup(database: Any, *, user_id: str, arc_id: str, takes: list[dict],
                   take_index: int, query: str):
    """Starts the lookup of the speaker's older Takes off the request and
    returns the call that collects it as facts, waiting at most
    ``_EARLIER_BUDGET``. Past that, or on any failure, the call gives []
    and the summary is written as before. Never raises."""
    try:
        from concurrent.futures import ThreadPoolExecutor
        from contextvars import copy_context
        from services.speaker_lookup import earlier_takes, key_terms
        older, wanted = _older(takes, take_index), key_terms(query)
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="take-summary-earlier")
        future = pool.submit(copy_context().run, lambda: earlier_takes(
            database, user_id, wanted, older=older,
            first=lambda take: str(take.get("arc_id") or "") == arc_id))
        pool.shutdown(wait=False)
    except Exception as error:  # noqa: BLE001 -- the summary is written as before
        logger.warning("take summary earlier takes not started user=%s: %s", user_id, error)
        return lambda: []

    def collect() -> list[str]:
        try:
            return earlier_facts(future.result(timeout=_EARLIER_BUDGET))
        except Exception as error:  # noqa: BLE001 -- too slow or failed: as before
            logger.warning("take summary earlier takes unread user=%s: %r", user_id, error)
            return []
    return collect


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
    """What the speaker said, and their most confident moment: the strongest
    voice, then the most willfident (founder 2026-10-21, N108). Pure."""
    said = " ".join(m["text"] for m in moments if m.get("text")).strip()
    facts = [f"What they said this Take: {said[:_SAID_CHARS]}"] if said else []
    rated = [r for r in now if isinstance(r.get("willfident"), (int, float))]
    best = max(rated, key=lambda r: (r.get("s") or 0, r["willfident"]), default=None)
    text = next((m["text"] for m in moments
                 if best and m.get("ref") == str(best.get("block_id")) and m.get("text")), "")
    if text:
        facts.append(f"Their most confident moment this Take: \"{text[:_MOMENT_CHARS]}\"")
    return facts


def _one_sentence(bank: str) -> list[str]:
    """A bank's lines of one sentence: the summary is one or two short
    sentences (N94), so a three-sentence line cannot fit. Pure."""
    from services import line_bank
    return [line for line in line_bank.BANKS[bank] if len(_sentences(line)) == 1]


def signed_lines(now: list[dict], before: Optional[list[dict]], take_index: int) -> list[str]:
    """The signed praise lines this Take may use (``line_bank``): the bank
    for what carried it (the voice or the words), the gentle general bank,
    and, from Take 2 on when the voice rose, the signed later-line; only
    lines of one sentence. Rotated by the Take so a speaker does not hear
    the same line twice. Pure."""
    from services import line_bank
    voice, words = _mean(now, "s"), _mean(now, "w")
    lead = "B07" if (words or 0) > (voice or 0) else "B01"
    picks: list[str] = []
    for bank in (lead, "B09"):
        options = _one_sentence(bank)
        for i in range(2):
            line = options[(take_index + i) % len(options)]
            if line not in picks:
                picks.append(line)
    if before is not None and _move(voice, _mean(before, "s")) == "rose":
        picks.append(line_bank.later_line("B01", take_index - 1))
    return picks


def fallback(take_index: int) -> str:
    """The bubble when the model's is refused: the signed journey copy's
    first line for Takes 1 to 3, what happened; from Take 4, where that copy
    has no line, the gentle signed praise line for the Take, so a fourth
    Take is never called the third (founder 2026-10-21). Pure."""
    from services.journey_messages import _COPY
    if take_index in _COPY:
        return _COPY[take_index].split("\n\n")[0]
    gentle = _one_sentence("B09")
    return gentle[take_index % len(gentle)]


def summary_message(database: Any, *, user_id: str, arc_id: str, takes: list[dict],
                    take_session_id: str, body: dict) -> Optional[dict]:
    """The summary bubble for one Take of the arc (``takes``: its spoken
    Takes in order), stored once; rewritten in place by each new coach
    note. ``earlier`` is the summary as first written, kept through every
    rewrite (N80: when the first one already heard the coach, it is that
    one). None when the Take is not the arc's."""
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
    # The usual message's first line only (N89): what happened, not what to
    # do next; the chain and the closing message bring the next step.
    anchor = fallback(take_index)
    moments = _moments(database, take)
    earlier = earlier_lookup(database, user_id=str(user_id), arc_id=str(arc_id), takes=takes,
                             take_index=take_index, query=_query(moments, words, takes))
    now, before = _reads(database, ids, take_index)
    rest = (progress_facts(now, before) + goal_facts(database, str(user_id))
            + memory_facts(database, str(user_id)))
    moved = _move(_mean(now, "s"), _mean(before, "s")) if before is not None else None
    will, carried = (None, []) if held else _will_plan(
        database, user_id=str(user_id), arc_id=str(arc_id), takes=takes, take=take,
        take_index=take_index, now=(practice, moved), moments=moments)
    facts = talk_facts(takes) + said_facts(moments, now) + earlier() + carried + rest
    asks, lead_ins = _chain_plan(database, user_id=str(user_id), arc_id=str(arc_id), take=take,
                                 take_index=take_index, practice=practice, moved=moved,
                                 can_install=body.get("can_install") is True, will=will,
                                 facts=facts, held=held is not None)
    text = _written(database, take, anchor, facts, practice, words,
                    note, str(arc_id), str(user_id),
                    signed=signed_lines(now, before, take_index),
                    names=talk_names(takes))
    meta = {"summary": True, "arc_id": str(arc_id), "take_index": take_index,
            "take_session_id": take, "written": bool(text), "coach_noted": note is not None,
            "coach_note_key": _note_key(note), "practice": practice, "helper_words": words,
            "moved": moved}
    if held:
        return _rewritten(database, str(user_id), client_id, held, text, meta)
    return _first_written(database, str(user_id), client_id, text or anchor, meta,
                          asks=asks, lead_ins=lead_ins(), will=will)


def _before_outcome(database: Any, user_id: str, arc_id: str, take_index: int) -> Optional[tuple]:
    """The Take before's (practice, moved), as its summary kept them; None
    on Take 1 or when it has no summary."""
    if take_index < 2:
        return None
    row = database.get_lounge_message_by_client_id(
        user_id, summary_client_id(user_id, arc_id, take_index - 1))
    meta = (row or {}).get("metadata") or {}
    return (meta.get("practice"), meta.get("moved")) if row else None


def _will_plan(database: Any, *, user_id: str, arc_id: str, takes: list[dict], take: str,
               take_index: int, now: tuple, moments: list[dict]) -> tuple:
    """Will's question after this Take (``will_question``), its heard call
    and its light touch started beside the summary's own; and, for the
    summary, the line practised last Take when this Take said it. Never
    raises."""
    from services import will_question
    try:
        snippets = database.get_snippets_by_session(take) or []
        carried = will_question.carried_over(database, user_id=user_id, takes=takes,
                                             take_index=take_index, snippets=snippets)
        found = will_question.plan(
            database, user_id=user_id, arc_id=arc_id, take=take, take_index=take_index,
            now=now, before=_before_outcome(database, user_id, arc_id, take_index),
            takes=takes, carried=carried, heard_call=lambda: {})
        if found and found.key in ("audience", "goal"):
            from services.chat_app_context import talk_title
            found.heard = will_question.start_heard(
                database, user_id=user_id, arc_id=arc_id, take=take,
                title=talk_title([t.get("intake_context") or {} for t in takes]),
                said=" ".join(m["text"] for m in moments if m.get("text")))
        if found:
            keys = [found.key] + (["audience_check"] if found.key == "audience" else [])
            found.varied = will_question.start_vary(
                database, user_id=user_id, arc_id=arc_id, take=take, keys=keys,
                words=found.words)
        return found, will_question.carried_fact(carried)
    except Exception as error:  # noqa: BLE001 -- the summary and its other asks go on
        logger.warning("take summary: no will question take=%s: %s", take, error, exc_info=True)
        return None, []


def _rewritten(database: Any, user_id: str, client_id: str, held: dict,
               text: Optional[str], meta: dict) -> dict:
    """A coach's note rewrites the stored summary in place; the first words
    stay one tap away (``earlier``)."""
    if not text:
        return held  # the coach's update could not be written: keep it
    from services import after_take
    first = held.get("metadata") or {}
    earlier = (first["earlier"] if first.get("coach_update") and first.get("earlier")
               else held.get("body"))
    meta.update({"coach_update": True, "earlier": earlier})
    # Still held back, or let go after "Yes": the rewrite keeps that.
    meta.update({k: first[k] for k in ("held_for", "glad") if first.get(k)})
    if first.get("glad"):
        text = after_take.glad_body(text)
    return database.rewrite_lounge_message(user_id, client_id, text, meta) or held


def _chain_plan(database: Any, *, user_id: str, arc_id: str, take: str, take_index: int,
                practice: Optional[str], moved: Optional[str], can_install: bool,
                will: Any, facts: list[str], held: bool) -> tuple:
    """The asks after this Take (``after_take.chain``) and Will's lead-ins
    for them, started beside the summary's own call so they cost no extra
    wait; nothing for a summary being rewritten. Never raises."""
    if held:
        return [], (lambda: {})
    from services import after_take
    from services.feedback_check import looks_off
    try:
        asks = after_take.chain(database, user_id, take_index=take_index,
                                off=looks_off(practice, moved), can_install=can_install,
                                will=will is not None)
        return asks, after_take.start_lead_ins(database, user_id=user_id, arc_id=arc_id,
                                               take=take, asks=asks, facts=facts)
    except Exception as error:  # noqa: BLE001 -- the summary is written either way
        logger.warning("take summary: no chain take=%s: %s", take, error, exc_info=True)
        return [], (lambda: {})


def _first_written(database: Any, user_id: str, client_id: str, text: str, meta: dict,
                   *, asks: list[str], lead_ins: dict, will: Any = None) -> Optional[dict]:
    """The summary's batch, once per Take (founder 2026-10-20, N89): the
    summary, drawn at once; the closing message, held back behind the chain
    of asks (``after_take``) when there is one; then the first ask."""
    from services import after_take
    from services.lounge_messages import stamp_after, thread_stamp
    take, practice, moved = meta["take_session_id"], meta["practice"], meta["moved"]
    after_take.release_older(database, user_id)
    # Under the walk it closes: the walk's steps carry the browser's time.
    at = thread_stamp(database, user_id)
    # Will's question is put together now, from his plan, and written when
    # its turn in the chain comes.
    queued = ({"will_question": after_take.ask_rows(
        database, "will_question", user_id=user_id, arc_id=meta["arc_id"], take=take,
        at=at, will=will, take_index=meta["take_index"])} if "will_question" in asks else {})
    closing = after_take.closing_row(user_id=user_id, arc_id=meta["arc_id"],
                                     take_index=meta["take_index"], take=take,
                                     at=stamp_after(at), asks=asks, lead_ins=lead_ins,
                                     queued=queued)
    first = after_take.rows_for(database, user_id, closing["metadata"], asks[0],
                                stamp_after(at, gap_ms=2)) if asks else []
    batch = [{
        "client_id": client_id,
        "role": "bot",
        "kind": "cadence",
        "body": text,
        "metadata": meta,
        "client_created_at": at,
    }, closing] + first
    persisted = database.insert_lounge_messages(user_id, batch)
    from services import speaker_memory
    speaker_memory.record(database, user_id, "take",
                          {"practice": practice, "moved": moved,
                           "helper_words": meta["helper_words"]}, take)
    from services.feedback_digest import post_later
    post_later(database)
    # The plan's lines after a practice (frontend the-plan.md G13, D1, A2);
    # best-effort, never in the way of the summary. With an ask in front of
    # the speaker they wait for the chain (``after_take.release``).
    if not asks:
        from services.plan_flow import after_take as plan_after_take
        plan_after_take(database, user_id)
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
    """A coach's word shared on a Take: its own Lounge bubble under "Later ·
    from your coach", as the coach wrote it (lock 2026-10-12, section 3), at
    the bottom of the thread the moment it is shared, like a new message
    (founder 2026-10-21), whether or not the review has ended; a changed
    word takes that bubble's place, marked edited (N192): the walk
    still shows the word as its first step, and writes no second copy into
    the chat while this one is there (frontend `coachNoteToChat`). Until
    2026-10-21 the bubble waited for the review to end, so a word shared
    during it reached the chat only as the walk's copy, among the Take's
    steps. Stored once per word. None when anything is missing."""
    from services.lounge_messages import thread_stamp
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
    video_url = None
    if video_ref:
        from services.coach_video_storage import refreshed_media_url
        video_url = refreshed_media_url(video_ref)
    body = f"{COACH_TITLE}\n{text}" if text else COACH_TITLE
    client_id = str(uuid.uuid5(_NAMESPACE, f"{take}:coach-update:{text or ''}:{video_ref or ''}"))
    earlier = _earlier_coach_bubble(database, str(user_id), take)
    # A changed word is an edit, not a new message (founder 2026-10-26,
    # N192): it takes the place of the Take's first bubble, marked edited,
    # and the Lounge read hides the version it replaces. Until then it
    # landed at the bottom (N80).
    edited = earlier is not None and earlier.get("client_id") != client_id
    persisted = database.insert_lounge_messages(str(user_id), [{
        "client_id": client_id,
        "role": "bot",
        "kind": "walk_step",
        "body": body,
        "metadata": {"step": "coachnote", "author": "coach", "coach_update": True,
                     "heading": COACH_UPDATE_LABEL, "arc_id": str(arc_id),
                     "take_session_id": take, "take_index": take_index,
                     "video": video_url, **({"edited": True} if edited else {})},
        "client_created_at": (earlier.get("client_created_at") if earlier is not None and edited else None)
        or thread_stamp(database, user_id),
    }])
    return persisted[0] if persisted else None


def _earlier_coach_bubble(database: Any, user_id: str, take: str) -> Optional[dict]:
    """The Take's first "Later · from your coach" bubble, or None. A failed
    read is None: the word still reaches the chat, at the bottom."""
    reader = getattr(database, "first_coach_update_bubble", None)
    if reader is None:
        return None
    try:
        row = reader(user_id, take)
    except Exception as e:  # noqa: BLE001 -- the word is written either way
        logger.info("earlier coach bubble unread take=%s: %s", take, e)
        return None
    return row if isinstance(row, dict) else None


def line_bank_lines() -> set:
    """Every signed line and later-line text, for checks. Pure."""
    from services import line_bank
    lines = {line for bank in line_bank.BANKS.values() for line in bank}
    return lines | set(line_bank.LATER.values())
