"""Why a green moment landed (founder 2026-10-18).

The walk's green moment showed the speaker's clip, the signed level line and
"It was your confident moment." and, most of the time, nothing more: the
signed catalogue lines are still unsigned and the cue sentences need a
speaker baseline. The founder, in a Claude Code session on 2026-10-18: "on
that screen we need to explain why it was a good take; not only it was a good
take ... every confident moment should have smth like this ... use gpt to
write it". Prototype approved the same day ("ok; dev it"):
https://claude.ai/artifact/Wdaznuffm9SJEkkjPEuSaR (version 4), three short
paragraphs of at most three lines each, in their own bubble after the praise.

WHAT IS WRITTEN. Up to three short paragraphs from one clip's own evidence,
told to GPT as words, never as numbers:
  - what the speaker said (the clip's transcript) and the slide it was on;
  - the voice cues that clearly moved toward confident against the speaker's
    OWN usual (``delivery_cues.cue_keys_for_piece``, the praise lane's own
    vocabulary), or that it sounded assured overall when the sound read is
    over the green floor (``moment_pick.FLOOR``);
  - the word signals that are clean: no filler, no hedge, makes the slide's
    point (``willfidence``, the same reads that picked the moment).

WHAT IS CHECKED, in code, before anything is kept: one to three paragraphs,
each short enough for three lines on a phone; a quote that really is the
speaker's words; no number, percentage, score or measurement name outside
that quote (AC-9); no comparison with anyone else; no emoji; nothing about
the voice when the facts say nothing about it. A reply that fails is asked
for once more, then kept EMPTY: the walk then shows the cue lines it showed
before, and nobody pays to ask again for that version.

WHEN. Never on the request path (LIVE LOOP). The serve path
(``ideal_text_changes``) attaches a stored reason to its green row and, for a
green row without one, queues ``run`` for the Take. The walk asks
``GET /v2/explore/arc/<arc>/praise-reasons`` while one is still being
written. Every provider call runs under the Take's processing authorization.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

REASON_VERSION = "green-reason-v1"
TASK_PATH = "services.praise_reason.run"
_SURFACE = "green_moment_reason"
MAX_PARAGRAPHS = 3
#: About three lines in the walk's bubble on a phone (18.5 px type).
MAX_PARAGRAPH_CHARS = 95
_MAX_QUOTE_CHARS = 80
_SAID_CHARS = 900
#: How long a queued job holds its Take's clips against a second enqueue.
_ENQUEUE_HOLD_SECONDS = 120

#: The praise lane's cue keys as facts about the speaker. Each is relative
#: to their own usual, which is what the cue measures (delivery_cues).
_CUE_FACTS = {
    "wide_range": "Their pitch moved up and down more than it usually does.",
    "full_volume": "They let their volume move more than they usually do.",
    "no_hesitation": "They paused less, and more briefly, than they usually do.",
    "settled_pitch": "Their voice sat lower than it usually does.",
    "kept_moving": "They kept their pace up instead of slowing down.",
    "landed_ending": "They brought the end of the sentence down and landed it.",
    "opened_strong": "They led with the energy at the start and eased off after.",
}
_REGION_FACTS = {
    "opening": "The strongest part was the start of the moment.",
    "closing": "The strongest part was the end of the moment.",
}
_ASSURED = "Overall, it sounded assured."
_NO_SOUND = "There is no read of how this clip sounded, only of the words."

_BANNED = re.compile(
    r"\d|%|\bcues?\b|\bscor(e|es|ed|ing)\b|\bmetrics?\b|\bwillfidence\b"
    r"|\bpercent|\bbaseline\b|\bdata\b|\balgorithm|\bmachine\b"
    r"|\bother (people|speakers)\b|\beveryone\b|\bmost people\b"
    r"|\bthan others\b|\bmost speakers\b",
    re.I,
)
_VOICE = re.compile(
    r"\b(voice|pitch|volume|loud\w*|quiet\w*|pause[sd]?|pausing|pace|tone"
    r"|energy|intonation)\b", re.I)
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")

_SYSTEM = (
    "You are Will, a speaking coach. A speaker just heard back one moment "
    "of their talk that sounded confident. Tell them WHY it landed, so they "
    "can do it again.\n"
    "Write two or three very short paragraphs, each one or two sentences "
    f"and at most {MAX_PARAGRAPH_CHARS} characters:\n"
    "1. What they said: quote a short phrase of theirs, copied word for "
    "word from WHAT THEY SAID, in curly quotes.\n"
    "2. What they did: the FACTS in plain words, about them ('your voice "
    "sat lower than usual').\n"
    "3. Why it works for the listener, in one short sentence.\n"
    "Rules:\n"
    "- Use only the FACTS. Never add a fact, a feeling or a guess.\n"
    "- Compare them only with how they usually sound, never with other "
    "people.\n"
    "- Say nothing about the voice unless a FACT is about the voice.\n"
    "- No numbers, percentages, scores or names of measurements; never the "
    "words 'cue', 'score', 'data' or 'baseline'.\n"
    "- No advice and nothing to improve: this is praise.\n"
    "- Plain, warm words, 'you', contractions. No emoji, no exclamation "
    "marks.\n"
    "Example, for a moment whose facts were a lower voice, fewer pauses, a "
    "landed ending, no fillers and fitting the slide:\n"
    '{"quote": "A full week. That is one person doing nothing else.", '
    '"paragraphs": ["When you said “A full week. That is one person '
    'doing nothing else.”", "Your voice sat lower than usual and you '
    'went straight through, no pauses.", "You landed the ending as a fact, '
    'not a question. No fillers, right on the slide."]}\n'
    'Reply only with JSON: {"quote": "...", "paragraphs": ["...", "..."]}'
)


def _norm(text: Any) -> str:
    """Words only, lower case, for comparing a quote with what was said."""
    raw = str(text or "").lower().replace("’", "'").replace("‘", "'")
    return " ".join(re.findall(r"[a-z0-9']+", raw))


def _slide_title(snippet: dict, slides: list, fixes: dict) -> Optional[str]:
    """The title of the slide this clip was spoken on, or None. The slide
    is read exactly as the Take's document reads it (coach correction
    first, then the cutter's bucket), so the two never disagree."""
    from services.transcript_document import _slide_of
    index = _slide_of(snippet, fixes)
    if index is None or not 0 <= index < len(slides):
        return None
    slide = slides[index]
    if not isinstance(slide, dict):
        return None
    title = (slide.get("title") or (slide.get("body") or "").split("\n")[0]).strip()
    return title[:120] or None


def moment_facts(snippet: dict, baseline: Optional[dict]) -> dict:
    """What is true about one clip, in words: ``{said, voice, words}``.
    ``voice`` is empty when nothing about the voice can be said, and holds
    ``_NO_SOUND`` when the clip has no sound read at all. Pure."""
    from services import willfidence
    from services.delivery_cues import accent_region, cue_keys_for_piece
    from services.moment_pick import FLOOR
    from services.voice_confidence import stamped_score

    metrics = snippet.get("metrics") if isinstance(snippet.get("metrics"), dict) else {}
    said = " ".join(str(snippet.get("transcript") or "").split())[:_SAID_CHARS]
    score = stamped_score(metrics)
    voice: list[str] = []
    if score is None:
        voice.append(_NO_SOUND)
    else:
        cues = cue_keys_for_piece(metrics, baseline) if baseline else []
        voice += [_CUE_FACTS[k] for k in cues if k in _CUE_FACTS]
        region = accent_region(metrics, baseline) if baseline and cues else None
        if region in _REGION_FACTS:
            voice.append(_REGION_FACTS[region])
        sound = willfidence.stretch(score)
        if not cues and sound is not None and sound >= FLOOR:
            voice.append(_ASSURED)
    words: list[str] = []
    if said and willfidence.filler(said) == 1:
        words.append("There are no filler words in it.")
    if said and willfidence.hedging(said) == 1:
        words.append("There are no hedging words in it.")
    fit = willfidence.slide_fit([metrics])
    if fit == 1:
        words.append("It makes the point of its slide.")
    elif fit == 0.5:
        words.append("It partly makes the point of its slide.")
    return {"said": said, "voice": voice, "words": words}


def _has_something_to_say(facts: dict) -> bool:
    """A quote alone is not a reason: there must be a fact to explain it."""
    heard = [f for f in facts["voice"] if f != _NO_SOUND]
    return bool(facts["said"]) and bool(heard or facts["words"])


def _parsed(reply: Any) -> Optional[tuple[str, list[str]]]:
    """The reply's quote and paragraphs, or None when it has neither
    shape. Pure."""
    if isinstance(reply, str):
        try:
            reply = json.loads(reply)
        except ValueError:
            return None
    if not isinstance(reply, dict) or not isinstance(reply.get("paragraphs"), list):
        return None
    quote = " ".join(str(reply.get("quote") or "").split()).strip(" \"\u201c\u201d")
    paragraphs = [" ".join(p.split()) for p in reply["paragraphs"]
                  if isinstance(p, str) and p.strip()]
    return quote, paragraphs


def _fits(paragraphs: list[str], quote: str, said: str) -> bool:
    """One to three short paragraphs, quoting words the speaker said."""
    if not 1 <= len(paragraphs) <= MAX_PARAGRAPHS:
        return False
    if any(len(p) > MAX_PARAGRAPH_CHARS for p in paragraphs):
        return False
    quoted = _norm(quote)
    if not quoted or len(quote) > _MAX_QUOTE_CHARS or quoted not in _norm(said):
        return False
    return any(quoted in _norm(p) for p in paragraphs)


def _says_only_what_is_allowed(paragraphs: list[str], quote: str, facts: dict) -> bool:
    """No number, measurement word, comparison, emoji or exclamation in
    the coach's words; nothing about the voice without a voice fact. The
    speaker's own quoted words may hold anything."""
    around = " ".join(re.sub(re.escape(quote), " ", p, flags=re.I) for p in paragraphs)
    if _BANNED.search(around) or _EMOJI.search(around) or "!" in around:
        return False
    heard = [f for f in facts.get("voice") or [] if f != _NO_SOUND]
    return bool(heard) or not _VOICE.search(around)


def clean_reason(reply: Any, facts: dict) -> Optional[dict]:
    """The reply as ``{paragraphs, quote}`` if it keeps every rule in the
    module docstring, else None. Pure."""
    parsed = _parsed(reply)
    if parsed is None:
        return None
    quote, paragraphs = parsed
    if not _fits(paragraphs, quote, str(facts.get("said") or "")):
        return None
    if not _says_only_what_is_allowed(paragraphs, quote, facts):
        return None
    return {"paragraphs": paragraphs, "quote": quote}


def _prompt(facts: dict, slide: Optional[str]) -> str:
    lines = [f"SLIDE: {slide or 'unknown'}", f"WHAT THEY SAID: {facts['said']}", "FACTS:"]
    lines += [f"- {fact}" for fact in facts["voice"] + facts["words"]]
    return "\n".join(lines)


def write_reason(facts: dict, slide: Optional[str], *, session_id: str,
                 arc_id: str, user_id: str) -> Optional[dict]:
    """GPT's reason for one clip: ``{paragraphs, quote}``; ``{paragraphs:
    [], quote: None}`` when two replies broke the rules; None when the
    provider gave nothing (nothing is kept, so a later read asks again)."""
    from services.llm import chat_complete
    from services.llm_config import SPEC_GREEN_MOMENT_REASON
    answered = False
    for _attempt in range(2):
        result = chat_complete(
            spec=SPEC_GREEN_MOMENT_REASON, system=_SYSTEM, user=_prompt(facts, slide),
            surface=_SURFACE, user_id=user_id, session_id=session_id, arc_id=arc_id)
        text = getattr(result, "text", None) if result else None
        if not text:
            continue
        answered = True
        reason = clean_reason(text, facts)
        if reason:
            return reason
        logger.info("green reason refused by the checks take=%s", session_id)
    return {"paragraphs": [], "quote": None} if answered else None


def _write_missing(database: Any, take: str, wanted: list[str]) -> int:
    stored = database.list_green_moment_reasons(wanted, REASON_VERSION)
    wanted = [sid for sid in wanted if sid not in stored]
    if not wanted:
        return 0
    session = database.v2_get_session_by_id(take) or {}
    snippets = database.get_snippets_by_session(take) or []
    by_id = {str(s.get("id")): s for s in snippets if isinstance(s, dict) and s.get("id")}
    # Only this Take's own clips: an id from anywhere else is ignored.
    targets = [by_id[sid] for sid in wanted if sid in by_id]
    if not targets:
        return 0
    from services.take_summary import _under_authority
    from services.transcript_document import _slide_corrections
    from services.voice_confidence import resolve_confidence_baseline
    baseline, _kind = resolve_confidence_baseline(
        session.get("user_id"), [s.get("metrics") for s in snippets], database=database)
    slides = (session.get("intake_context") or {}).get("slides") or []
    fixes = _slide_corrections(database, take)
    kept = 0
    for snippet in targets:
        sid = str(snippet["id"])
        facts = moment_facts(snippet, baseline)
        if not _has_something_to_say(facts):
            reason: Optional[dict] = {"paragraphs": [], "quote": None}
        else:
            slide = _slide_title(snippet, slides, fixes)
            try:
                reason = _under_authority(database, take, lambda: write_reason(
                    facts, slide, session_id=take, arc_id=str(session.get("arc_id") or ""),
                    user_id=str(session.get("user_id") or "")), label="green-reason")
            except Exception as error:  # noqa: BLE001 -- refused or failed: ask later
                logger.warning("green reason refused take=%s: %s", take, error)
                reason = None
        if reason is None:
            continue
        database.save_green_moment_reason(
            snippet_id=sid, take_session_id=take, reason_version=REASON_VERSION,
            paragraphs=reason["paragraphs"], quote=reason["quote"])
        kept += 1
    return kept


def run(take_session_id: str, snippet_ids: list) -> int:
    """RQ entry point: write the missing reasons for these green clips of
    one Take, first slide first. Returns how many were kept. Never raises."""
    take = str(take_session_id or "").strip()
    wanted = [str(s) for s in snippet_ids or [] if s]
    if not take or not wanted:
        return 0
    try:
        from services.db import db
        return _write_missing(db, take, wanted)
    except Exception as error:  # noqa: BLE001 -- the walk shows the cue lines
        logger.warning("green reason failed take=%s: %s", take, error)
        return 0


def enqueue(take_session_id: str, snippet_ids: list) -> bool:
    """Queue ``run`` for these clips, once per two minutes per set. Never
    raises; False when nothing was queued."""
    take = str(take_session_id or "").strip()
    ids = [str(s) for s in snippet_ids or [] if s]
    if not take or not ids:
        return False
    try:
        from services import job_queue
        if not job_queue.queue_configured():
            return False
        key = hashlib.sha256(",".join(sorted(ids)).encode("utf-8")).hexdigest()[:12]
        job_id = f"green-reason:{take}:{key}"
        conn = job_queue.get_redis()
        if conn is not None and not conn.set(job_id, "1", nx=True, ex=_ENQUEUE_HOLD_SECONDS):
            return False
        return job_queue.enqueue(TASK_PATH, take, ids, queue=job_queue.bake_queue_name(),
                                 rq_job_id=job_id)
    except Exception as error:  # noqa: BLE001 -- the walk shows the cue lines
        logger.warning("green reason not queued take=%s: %s", take, error)
        return False


def _is_green(row: Any) -> bool:
    return (isinstance(row, dict) and row.get("bookmark_tier") == "confident"
            and bool(row.get("snippet_id")) and bool(row.get("take_session_id")))


def attach(database: Any, rows: list) -> list:
    """The served rows, each green one carrying its stored reason as
    ``praise_reason: {paragraphs, quote}``; a green row without one has it
    queued. Rows are copied, never edited; nothing else changes."""
    green = [row for row in rows or [] if _is_green(row)]
    if not green:
        return rows
    try:
        stored = database.list_green_moment_reasons(
            [row["snippet_id"] for row in green], REASON_VERSION)
    except Exception as error:  # noqa: BLE001 -- no table yet: no reason, no job
        logger.info("green reasons unreadable: %s", error)
        return rows
    missing: dict[str, list[str]] = {}
    out: list = []
    for row in rows:
        if not _is_green(row):
            out.append(row)
            continue
        sid = str(row["snippet_id"])
        reason = stored.get(sid)
        if reason is None:
            missing.setdefault(str(row["take_session_id"]), []).append(sid)
        if reason and reason.get("paragraphs"):
            row = {**row, "praise_reason": {"paragraphs": reason["paragraphs"],
                                            "quote": reason.get("quote")}}
        out.append(row)
    for take, ids in missing.items():
        enqueue(take, ids)
    return out


def reasons_for(database: Any, take_session_id: str, snippet_ids: list) -> dict:
    """The walk's poll: ``{reasons: {snippet_id: {paragraphs, quote}},
    pending: [snippet_id]}`` for this Take's clips. A clip asked about and
    kept empty is in neither: the walk shows the cue lines for it."""
    take = str(take_session_id or "")
    wanted = [str(s) for s in snippet_ids or [] if s][:MAX_PARAGRAPHS * 3]
    own = {str(s.get("id")) for s in database.get_snippets_by_session(take) or []
           if isinstance(s, dict)}
    wanted = [sid for sid in wanted if sid in own]
    stored = database.list_green_moment_reasons(wanted, REASON_VERSION) if wanted else {}
    return {
        "reasons": {sid: {"paragraphs": r["paragraphs"], "quote": r.get("quote")}
                    for sid, r in stored.items() if r.get("paragraphs")},
        "pending": [sid for sid in wanted if sid not in stored],
    }
