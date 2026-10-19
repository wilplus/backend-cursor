"""Pet phrase: a phrase the speaker keeps using gets one other way to say it
(founder 2026-10-19, WIL-26; decision tree
https://claude.ai/artifact/QpvRaEfH4bRGM9E85dtmYF).

"At the end of the day" three times in five minutes. Each use alone is
fine; together the listener starts counting. The repeat detector in
take_feedback_manager only sees words said twice in a row, so this lane
looks across the whole Take.

THREE STEPS, TWO PLACES:

  1. FIND (pure, `find_pet_phrase`): the longest phrase of 3 to 6 words
     said ``MIN_USES`` or more times inside sentences. Never the topic: a
     phrase whose content words are all on the slides, a phrase with a name
     or a number, or one made only of small words ("a lot of the").
  2. WORD (the analysis job, `generate_for_session`): one small AI call for
     one alternative, inside the Take's provider-authorization scope
     (run_full_analysis), stored on the Take (v2_sessions.pet_phrase).
  3. OFFER (the feedback GET, `rewrite_row`): when the phrase is still
     said ``MIN_USES`` times in the served Ideal Text, its last use becomes
     an ordinary rewrite_clarity candidate. It shares the one wording slot
     (founder: "share the slot"): the Manager ranks it under the
     word-preserving repairs and above the tentative fallback.

Behind PET_PHRASE_ENABLED, off by default (founder: off until the golden
examples are read). Off: no AI call, no row. AC-9: nothing here reaches a
speaker but the alternative words themselves.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from services.take_feedback_manager import _WORD_RE, _sentences, _stable_id

logger = logging.getLogger(__name__)

#: Bump when the prompt, the guards or the find rules change.
PET_PHRASE_VERSION = "pet-phrase-v1"
#: Uses in one Take before a phrase is a pet phrase (founder: three).
MIN_USES = 3
MIN_WORDS = 3
MAX_WORDS = 6
MAX_ALTERNATIVE_WORDS = 6
#: The July rule (protected_phrases A): a phrase said in two or more Takes
#: is the speaker's own wording. Asked of the founder 2026-10-19 whether a
#: pet phrase is an exception; until answered, the July rule wins.
OVERRIDES_OWN_WORDING = False

# Small words that do not make a phrase a habit on their own. A phrase needs
# at least one word outside this list. English only: in another language
# every word counts as content, which only lets more phrases through to the
# other checks.
_SMALL_WORDS = frozenset("""
a an the and or but so to of in on at by for with from as is are was were be
been it its this that these those i we you they he she me us them my our your
their his her not no do does did have has had will would can could should
just very really there here what which who than then if about into out up
""".split())

_ENDS_SENTENCE = re.compile(r"[.!?]")


def enabled() -> bool:
    try:
        from config import Config
        return bool(getattr(Config(), "PET_PHRASE_ENABLED", False))
    except Exception:
        logger.warning("pet_phrase: config unreadable, staying off", exc_info=True)
        return False


def _tokens(text: str) -> list[tuple[int, int, str, int, bool]]:
    """(start, end, lowered word, sentence index, said as a name)."""
    out = []
    for index, (s_start, s_end, _sentence) in enumerate(_sentences(text)):
        first = True
        for match in _WORD_RE.finditer(text, s_start, s_end):
            word = match.group(0)
            name = (not first and word[0].isupper() and word != "I")
            out.append((match.start(), match.end(), word.lower(), index, name))
            first = False
    return out


def _topic_words(slide_text: str) -> frozenset:
    return frozenset(w.lower() for w in _WORD_RE.findall(slide_text or ""))


def find_pet_phrase(text: Any, slide_text: Any = "") -> Optional[dict]:
    """The phrase used most like a habit, or None. Pure.

    ``{"phrase": <first use as said>, "uses": n}``. Longest phrase first, so
    "at the end of the day" wins over "the end of the"; then the most uses;
    then the earliest."""
    text = text if isinstance(text, str) else ""
    tokens = _tokens(text)
    topic = _topic_words(slide_text if isinstance(slide_text, str) else "")
    for size in range(MAX_WORDS, MIN_WORDS - 1, -1):
        starts: dict[tuple, list[int]] = {}
        for i in range(len(tokens) - size + 1):
            run = tokens[i:i + size]
            if run[0][3] != run[-1][3] or any(t[4] for t in run):
                continue
            words = tuple(t[2] for t in run)
            if any(ch.isdigit() for w in words for ch in w):
                continue
            content = [w for w in words if w not in _SMALL_WORDS]
            if not content or all(w in topic for w in content):
                continue
            seen = starts.setdefault(words, [])
            if not seen or i - seen[-1] >= size:   # non-overlapping uses
                seen.append(i)
        best = None
        for words, at in starts.items():
            if len(at) < MIN_USES:
                continue
            key = (-len(at), at[0])
            if best is None or key < best[0]:
                best = (key, at[0], len(at))
        if best is not None:
            _, first, uses = best
            phrase = text[tokens[first][0]:tokens[first + size - 1][1]]
            return {"phrase": phrase, "uses": uses}
    return None


def uses_of(text: Any, phrase: Any) -> list[tuple[int, int]]:
    """Every (start, end) where the phrase is said, any case. Pure."""
    text = text if isinstance(text, str) else ""
    words = _WORD_RE.findall(phrase if isinstance(phrase, str) else "")
    if not text or not words:
        return []
    pattern = r"(?<![\w'’-])" + r"\s+".join(map(re.escape, words)) + r"(?![\w'’-])"
    return [m.span() for m in re.finditer(pattern, text, re.IGNORECASE)]


def clean_alternative(raw: Any, phrase: str) -> Optional[str]:
    """The model's alternative, or None when it breaks a rule. An empty
    alternative ("just drop it") is allowed and returned as ""."""
    if not isinstance(raw, str):
        return None
    alt = raw.strip().strip("\"'“”‘’").strip()
    alt = _ENDS_SENTENCE.sub("", alt).strip(" ,;:")
    if not alt:
        return ""
    words = _WORD_RE.findall(alt)
    if not words or len(words) > MAX_ALTERNATIVE_WORDS:
        return None
    if any(ch.isdigit() for ch in alt):
        return None
    if any(w[0].isupper() and w != "I" for w in words[1:]):
        return None   # a name the speaker did not say
    said = {w.lower() for w in _WORD_RE.findall(phrase)} - _SMALL_WORDS
    if said and said <= {w.lower() for w in words}:
        return None   # the same habit in other clothes
    return alt


_RESPONSE_SCHEMA = {
    "name": "pet_phrase",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["alternative"],
        "properties": {"alternative": {"type": "string", "maxLength": 80}},
    },
    "strict": True,
}


def generate_alternative(phrase: str, sentence: str) -> Optional[dict]:
    """One AI call → ``{"alternative", "model"}``, or None. The caller owns
    the provider-authorization scope (run_full_analysis)."""
    if not phrase or not sentence:
        return None
    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_PET_PHRASE
        from services.prompts import pet_phrase as prompts
        result = chat_complete(
            spec=SPEC_PET_PHRASE,
            system=prompts.SYSTEM,
            user=prompts.user(phrase, sentence),
            surface="pet_phrase",
            response_format_override={
                "type": "json_schema", "json_schema": _RESPONSE_SCHEMA},
        )
    except Exception as error:  # noqa: BLE001 -- logged; no row rather than a broken Take
        logger.warning("pet_phrase: llm call failed: %s", error, exc_info=True)
        return None
    if result is None:
        return None
    parsed = result.parsed
    if parsed is None:
        try:
            parsed = json.loads(result.text or "")
        except (ValueError, TypeError):
            parsed = None
    alt = clean_alternative((parsed or {}).get("alternative")
                            if isinstance(parsed, dict) else None, phrase)
    if alt is None:
        return None
    return {"alternative": alt, "model": result.model}


def _sentence_around(text: str, start: int) -> Optional[tuple[int, int, str]]:
    for s_start, s_end, sentence in _sentences(text):
        if s_start <= start < s_end:
            return s_start, s_end, sentence
    return None


def _session_text(database: Any, session_id: str) -> str:
    parts = []
    for row in (database.get_snippets_by_session(session_id) or []):
        said = (row.get("transcript") or row.get("transcription_text") or "").strip()
        if said:
            parts.append(said)
    return " ".join(parts)


def _slide_text(session: dict) -> str:
    context = session.get("intake_context")
    slides = (context or {}).get("slides") if isinstance(context, dict) else None
    return "\n".join(
        f"{s.get('title') or ''}\n{s.get('body') or ''}"
        for s in (slides or []) if isinstance(s, dict))


def generate_for_session(session_id: str, arc_id: Optional[str], *,
                         database: Any = None) -> bool:
    """Analysis-time hook: find, word and store this Take's pet phrase.
    True when one was stored. Never raises into the analysis job."""
    if not session_id or not enabled():
        return False
    try:
        if database is None:
            from services.db import db as database
        session = database.v2_get_session_by_id(session_id) or {}
        text = _session_text(database, session_id)
        found = find_pet_phrase(text, _slide_text(session))
        if found is None:
            return False
        phrase = found["phrase"]
        if not OVERRIDES_OWN_WORDING and arc_id:
            from services.protected_phrases import collect_take_texts, phrase_recurs
            if phrase_recurs(phrase, collect_take_texts(database, arc_id)):
                return False
        last = uses_of(text, phrase)[-1]
        around = _sentence_around(text, last[0])
        if around is None:
            return False
        worded = generate_alternative(phrase, around[2])
        if worded is None:
            return False
        return bool(database.takes.update_session_pet_phrase(session_id, {
            "version": PET_PHRASE_VERSION,
            "phrase": phrase,
            "alternative": worded["alternative"],
            "model": worded["model"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }))
    except Exception as error:  # noqa: BLE001 -- logged; the Take finishes without it
        logger.warning("pet_phrase: generate failed sid=%s: %s", session_id, error,
                       exc_info=True)
        return False


def _in_place(alternative: str, said: str, sentence_start: bool) -> str:
    if not alternative:
        return ""
    if sentence_start or said[:1].isupper():
        return alternative[0].upper() + alternative[1:]
    if alternative[:2].isupper():   # an acronym keeps its capitals
        return alternative
    return alternative[0].lower() + alternative[1:]


def rewrite_row(served_text: Any, stored: Any, *, take_session_id: Any,
                snippet_id: Any) -> Optional[dict]:
    """The pet phrase's last use in the served Ideal Text as a rewrite
    candidate, or None. Pure."""
    text = served_text if isinstance(served_text, str) else ""
    take, sid = str(take_session_id or ""), str(snippet_id or "")
    if not isinstance(stored, dict) or not text or not take or not sid:
        return None
    if stored.get("version") != PET_PHRASE_VERSION:
        return None
    phrase, alternative = stored.get("phrase"), stored.get("alternative")
    if not isinstance(phrase, str) or not isinstance(alternative, str):
        return None
    uses = uses_of(text, phrase)
    if len(uses) < MIN_USES:
        return None   # the Ideal Text moved on; the habit is no longer there
    start, end = uses[-1]
    around = _sentence_around(text, start)
    if around is None:
        return None
    s_start, s_end, sentence = around
    words = _in_place(alternative, text[start:end], start == s_start)
    before, after = text[s_start:start], text[end:s_end]
    if not words:   # "just drop it": tidy the gap it leaves
        before = before.rstrip(" ,")
        after = after.lstrip(" ,")
        if not before and after:
            after = after[0].upper() + after[1:]
        joiner = " " if before and after and after[0].isalnum() else ""
        proposed = f"{before}{joiner}{after}"
    else:
        proposed = f"{before}{words}{after}"
    if len(_WORD_RE.findall(proposed)) < 2 or proposed == sentence:
        return None
    return {
        "id": _stable_id("pet-phrase-rewrite", take, sentence),
        "snippet_id": sid,
        "take_session_id": take,
        "kind": "replace",
        "source": "wording",
        "span": {"start": s_start, "end": s_end},
        "quote": sentence,
        "proposed_text": proposed,
        "why_key": "clarity",
        "feedback_family": "rewrite_clarity",
        "tentative": False,
        "suggestion_version": PET_PHRASE_VERSION,
        "_manager_evidence": {
            "fallback": False,
            "detector": "pet_phrase",
            "detector_rank": 3,
            "specificity": 3,
            "basis": "phrase_used_often",
        },
    }
