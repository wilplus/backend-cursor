"""Will's voice in the walk (founder 2026-11-09, N560).

Each walk message is written by GPT-4o from what we know about the Take,
by the rules the founder sets (`services/prompts/walk_voice.py`), instead
of a signed line. The walk asks for one message at a time
(`routes/v2/walk_voice.py`); when the writer is off, slow, fails, or its
words fail `check`, the answer is None and the walk says its signed line,
so record -> Ideal Text -> next Take never waits on it (Never 3).

  write(database, user_id, take_id, step, snippet_id, conversation)
      the message, or None. Ring-gated (`rings.WALK_VOICE`), the speaker's
      own Take only, the provider call under the processing authorization.
  context_for(database, user_id, take_id, snippet_id)
      what Will knows, as words: the moment's own words, how it sounded
      against the speaker's own usual, the last Take's fix, this week's
      level, the speaker's private note. Never a number for the speaker.
  compose(context, step)
      the provider call and the check, with no database: the eval set's
      entry point (`tests/evals/surfaces.py`).
  check(text, context)
      None when the words may reach the speaker, else the reason. Pure.

Numbers never cross (Never 1): the context the model reads holds words, and
`check` refuses a digit, a measurement name, a fix-the-speaker word, more
than two sentences or 220 characters, more than one question, and a quote
that is not the speaker's own words.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SURFACE = "walk_voice"

#: The walk's steps Will may write for.
STEPS: tuple[str, ...] = ("praise", "try", "after_try", "good_take", "reply")
_STEP_ASK = {
    "praise": "praise their best moment (opens the walk after their clip plays)",
    "try": "introduce the one moment to try another way, before its exercise",
    "after_try": "respond to their try at the moment",
    "good_take": "say this Take held up as a whole; mention last time if it helps",
    "reply": "reply to the speaker",
}

MAX_CHARS = 220
MAX_SENTENCES = 2

#: Words that say the speaker is broken, internal names, verdicts
#: (N557, Never 1). Whole words, any case.
BANNED_WORDS: tuple[str, ...] = (
    "fix", "fixed", "fixing", "improve", "improvement", "wrong", "mistake",
    "mistakes", "weak", "weakness", "error", "errors", "problem", "problems",
    "score", "scores", "metric", "metrics", "cue", "cues", "willfidence",
    "perfect", "amazing", "awesome", "flawless",
)
#: Measurement names and coaching idioms the founder turned down
#: (2026-11-09: "too complex", "'drawing in' sounds weird").
BANNED_PHRASES: tuple[str, ...] = (
    "loudness range", "pause ratio", "words per minute", "wpm", "pitch",
    "draw us in", "drawing us in", "draws us in", "drew us in",
    "make it land", "makes it land", "land the", "make it stick",
    "made the idea stick", "give your words weight", "gave your words weight",
    "resonate", "space to breathe", "gives weight", "give weight", "gave weight",
    "adds weight", "added weight", "as if you", "you should", "you need to",
    "great job", "good job", "you've got this",
)
_WORD_RE = re.compile(r"[a-z']+")
_QUOTE_RE = re.compile(r"[\"“”]([^\"“”]{2,})[\"“”]")
#: A sentence ends at . ! or ? (and any closing quote) before a capital
#: letter or the end; a full stop inside a quotation followed by more of the
#: sentence ('"...how." came through') is no end.
_SENTENCE_END = re.compile(r"[.!?]+[\"”)]*(?=\s+[A-Z\"“]|\s*$)")


def check(text: Optional[str], context: Optional[dict] = None) -> Optional[str]:
    """None when ``text`` may reach the speaker, else the reason. Pure."""
    if not text or not text.strip():
        return "empty"
    said = text.strip()
    if len(said) > MAX_CHARS:
        return f"too long ({len(said)} > {MAX_CHARS})"
    if re.search(r"\d", said):
        return "a digit (Never 1)"
    lower = said.lower()
    words = set(_WORD_RE.findall(lower))
    for word in BANNED_WORDS:
        if word in words:
            return f"banned word: {word}"
    for phrase in BANNED_PHRASES:
        if phrase in lower:
            return f"banned phrase: {phrase}"
    if said.count("?") > 1:
        return "more than one question"
    sentences = [s for s in _SENTENCE_END.split(said) if s.strip()]
    if len(sentences) > MAX_SENTENCES:
        return f"more than {MAX_SENTENCES} sentences"
    spoken = _spoken_text(context)
    for quoted in _QUOTE_RE.findall(said):
        if _norm(quoted) not in spoken:
            return f"quote not in their words: {quoted}"
    return None


def _norm(text: str) -> str:
    return " ".join(_WORD_RE.findall(text.lower().replace("’", "'")))


def _spoken_text(context: Optional[dict]) -> str:
    """Every sentence the speaker said that the context carries, normalised,
    so a quote can be checked against it."""
    found: list[str] = []

    def walk(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, k)
        elif isinstance(value, list):
            for v in value:
                walk(v, key)
        elif isinstance(value, str) and key in ("words", "speaker"):
            found.append(value)
    walk(context or {})
    return " | ".join(_norm(f) for f in found)


def compose(context: dict, step: dict) -> Optional[str]:
    """Will's message for ``step`` from ``context``, or None when the call
    fails or its words fail ``check``. No database."""
    from services.llm import chat_complete
    from services.llm_config import SPEC_WALK_VOICE
    from services.prompts.walk_voice import SYSTEM
    user = ("CONTEXT:\n" + json.dumps(context, indent=1, ensure_ascii=False)
            + "\n\nSTEP:\n" + json.dumps(step, indent=1, ensure_ascii=False))
    for attempt in range(ATTEMPTS):
        result = chat_complete(spec=SPEC_WALK_VOICE, system=SYSTEM, user=user, surface=_SURFACE)
        text = _unwrapped((getattr(result, "text", None) or "") if result else "")
        reason = check(text, context)
        if not reason:
            return text
        logger.info("walk voice: refused (%s) attempt=%d: %r", reason, attempt + 1, text[:240])
        # One more try, told what was refused (the walk's budget allows it:
        # a call takes about a second).
        user += f"\n\nYour last draft was refused ({reason}). Write it again within the rules."
    return None


#: Tries before the walk says its signed line.
ATTEMPTS = 2


def _unwrapped(text: str) -> str:
    """The text without quote marks wrapped around the whole of it."""
    said = text.strip()
    if len(said) > 1 and said[0] in "\"“" and said[-1] in "\"”" and said.count('"') + said.count("“") + said.count("”") == 2:
        said = said[1:-1].strip()
    return said


def write(database: Any, user_id: Any, take_id: Any, step: Any,
          snippet_id: Any = None, conversation: Any = None) -> Optional[str]:
    """The walk's message for ``step``, or None (the walk says its signed
    line). Never raises."""
    try:
        from services import rings
        if step not in STEPS or not take_id:
            return None
        if not rings.feature_is_on_for_user(rings.WALK_VOICE, user_id, database=database):
            return None
        take = database.v2_get_session_by_id(str(take_id)) or {}
        if str(take.get("user_id") or "") != str(user_id):
            return None
        context = context_for(database, user_id, take, snippet_id)
        ask: dict[str, Any] = {"message": _STEP_ASK[step]}
        said = _conversation(conversation)
        if said:
            ask["conversation"] = said
        return _under_authority(database, str(take_id), lambda: compose(context, ask))
    except Exception as error:  # noqa: BLE001 -- the signed line then
        logger.warning("walk voice: not written take=%s step=%s: %s", take_id, step, error,
                       exc_info=True)
        return None


def _conversation(conversation: Any) -> list[dict]:
    """The walk's last few turns, as the client sent them: [{"will": ...} |
    {"speaker": ...}], each at most 400 characters."""
    out: list[dict] = []
    for turn in (conversation if isinstance(conversation, list) else [])[-6:]:
        if isinstance(turn, dict):
            for who in ("will", "speaker"):
                if isinstance(turn.get(who), str) and turn[who].strip():
                    out.append({who: turn[who].strip()[:400]})
    return out


def context_for(database: Any, user_id: Any, take: dict, snippet_id: Any) -> dict:
    """What Will knows for this message, in words. Each part is read on its
    own; one that fails is left out."""
    take_id = str(take.get("id") or "")
    context: dict[str, Any] = {"take_number": take.get("take_index")}
    snippets = _safe(lambda: database.get_snippets_by_session(take_id), []) or []
    moment = next((s for s in snippets if str(s.get("id")) == str(snippet_id or "")), None)
    if moment is not None:
        context["moment"] = {"words": str(moment.get("transcript") or "").strip(),
                             "sounded": sounded(moment, snippets)}
    note = _safe(lambda: _note(database, user_id), "")
    if note:
        context["speaker_note"] = note
    level = _safe(lambda: _level(database, user_id, take), None)
    if level:
        context["plan_this_week"] = level
    last = _safe(lambda: _last(database, take), None)
    if last:
        context["last_take"] = last
    return context


def sounded(snippet: dict, snippets: list[dict]) -> dict:
    """How one clip sounded against the speaker's own usual on this Take,
    in words (`ai_voice_severity`): pace, pauses, loudness, fillers. Only
    what stands out is said; nothing when nothing does."""
    from services import ai_voice_severity as sev
    medians = sev.own_medians(snippets)
    scores = sev.severities(snippet, medians, sentence=str(snippet.get("transcript") or ""))
    out: dict[str, str] = {}
    metrics = snippet.get("metrics") or {}
    wpm, usual = metrics.get("wpm"), medians.get("wpm")
    if scores.get("pace", 0) >= 0.2:
        out["pace"] = "faster than their usual"
    elif isinstance(wpm, (int, float)) and isinstance(usual, (int, float)) and usual and wpm < 0.85 * usual:
        out["pace"] = "slower than their usual"
    if scores.get("pause", 0) >= 0.2:
        out["pauses"] = "few or no pauses"
    if scores.get("stress", 0) >= 0.2:
        out["loudness"] = "flatter than their usual"
    if scores.get("fillers", 0) >= 0.2:
        out["fillers"] = "more fillers than their usual"
    return out


def _note(database: Any, user_id: Any) -> str:
    from services.speaker_memory import note_for
    return note_for(database, user_id)


def _level(database: Any, user_id: Any, take: dict) -> Optional[str]:
    from services.plan_walk import level_for_take
    return level_for_take(database, user_id, take)


def _last(database: Any, take: dict) -> Optional[str]:
    """The last Take's fix, when it rose on this Take, as words."""
    from services import take_progress
    sessions = database.takes.get_arc_sessions(str(take.get("arc_id"))) or []
    before = take_progress.previous_take(sessions, take.get("id"))
    fix = take_progress.last_fix(database, take.get("id"), before) if before else None
    if not fix:
        return None
    kinds = {"voice": "the voice exercise", "clearer": "a clearer way to say it",
             "tempo": "the pace game"}
    return f"last Take's walk gave {kinds.get(str(fix.get('kind')), 'one moment')}, and on this Take that moment came out the way they practised"


def _safe(read, default):
    try:
        return read()
    except Exception as error:  # noqa: BLE001 -- that part is left out
        logger.info("walk voice: context part not read: %s", error)
        return default


def _under_authority(database: Any, take: str, write) -> Optional[str]:
    """Run ``write`` inside the Take's protected provider scope when the
    processing-authorization mode enforces (as `take_summary`)."""
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
    with protected_provider_scope(adapter, idempotency_prefix=f"walk-voice:{take}:{uuid.uuid4()}"):
        return write()
