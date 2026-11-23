"""The structured exercise → one Eleven v4 request, deterministically
(founder lock 2026-10-12, docs/FOUNDER-LOCK-ai-voice-practice-2026-10-12.md).

No model writes the request and no free text reaches the provider: the text
sent is the speaker's own sentence, with only punctuation, line breaks and
two whitelisted audio tags added. The words are never changed. The one
exception is the fillers exercise (founder 2026-10-18): the sentence is sent
without its hesitations ("um", "uh"), exactly the tokens the transcript
fence removes silently, and nothing else.

WHAT ELEVEN V4 CAN AND CANNOT DO (official SDK 2.71 and docs, 2026-10):

  * no SSML: ``<break>`` is not read; pauses come from punctuation, an
    ellipsis or the ``[pause]`` tag.
  * ``voice_settings``: only ``stability`` and ``similarity_boost`` act on
    v4. ``speed`` and ``style`` are v2/v3 only, so pace cannot be set as a
    number; it is asked for with the ``[slowly]`` tag and clause breaks, and
    the validator checks it really happened.
  * no emphasis tag: a phrase is made to stand out by capitals, the one
    documented way; the weakest of the three, so the validator decides.
  * tags guide delivery and are not guaranteed.

Accent is kept by the clone itself; ``similarity_boost`` is set high so the
voice stays close to the speaker's, and no accent or style tag is ever
added.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

from config import Config
from services.ai_voice_language import require as require_language
from services.ai_voice_language import tokens as word_tokens

BUILDER_VERSION = "ai-voice-prompt-v3"
ALLOWED_TAGS = frozenset({"[slowly]", "[pause]"})
VOICE_SETTINGS = {"stability": 0.55, "similarity_boost": 0.9}
OUTPUT_FORMAT = "mp3_44100_128"

_TAG = re.compile(r"\[[^\]]*\]")
_SPACE = re.compile(r"\s+")


#: Words a second at the slightly slower pace a clip is asked for (about
#: 130 a minute): how long a sentence takes to say, before it is sent.
SLOW_WORDS_PER_SECOND = 2.2


class PromptRejected(ValueError):
    """The exercise or sentence can't make a safe request; nothing is sent."""


def _clean(sentence: str) -> str:
    """The speaker's words as text: no brackets (they would read as tags),
    one space between words."""
    text = _TAG.sub(" ", str(sentence or "")).replace("[", " ").replace("]", " ")
    return _SPACE.sub(" ", text).strip()


def _words(text: str) -> list[str]:
    return word_tokens(text)


def _locate(text: str, phrase: str) -> Optional[re.Match]:
    target = _words(phrase)
    if not target:
        return None
    pattern = (r"(?<![\w'’])" + r"\W+".join(re.escape(word) for word in target)
               + r"(?![\w'’])")
    return re.compile(pattern, re.IGNORECASE | re.UNICODE).search(text)


def _seed(practice_id: str) -> int:
    return int.from_bytes(hashlib.sha256(practice_id.encode()).digest()[:4], "big")


def _pace(text: str, language: str) -> str:
    # One breath at each joining word that has no punctuation before it.
    joining = "|".join(re.escape(word) for word in _JOINING[language])
    clause = re.compile(rf"\s({joining})\s", re.IGNORECASE | re.UNICODE)
    slower = clause.sub(lambda m: f", {m.group(1)} ", text)
    slower = re.sub(r",\s*,", ",", slower)
    return f"[slowly] {slower}"


def _pause(text: str, phrase: str) -> str:
    match = _locate(text, phrase)
    if match is None:
        raise PromptRejected("TARGET_PHRASE_NOT_IN_SENTENCE")
    before = text[:match.start()].rstrip(" ,;:")
    # The tag alone made too short a gap on Eleven v4 (founder's smoke run,
    # 2026-10-13); an ellipsis before it is the documented way to hold a beat.
    return f"{before}... [pause] {text[match.start():]}".strip()


_OPENING_GREETING = re.compile(
    r"^(hi|hello|good morning|cześć|hej|dzień dobry|witam)[.!]\s+$", re.IGNORECASE,
)


def _stress(text: str, phrase: str, *, opening_emphasis: bool = False) -> str:
    match = _locate(text, phrase)
    if match is None:
        raise PromptRejected("TARGET_PHRASE_NOT_IN_SENTENCE")
    before = text[:match.start()]
    if opening_emphasis:
        before = _OPENING_GREETING.sub(r"\1, ", before)
    return before + match.group(0).upper() + text[match.end():]


def check_text(prepared: str, original: str) -> None:
    """Reject anything but the original words plus whitelisted tags."""
    for tag in _TAG.findall(prepared):
        if tag.lower() not in ALLOWED_TAGS:
            raise PromptRejected("UNSUPPORTED_TAG")
    if _words(_TAG.sub(" ", prepared)) != _words(original):
        raise PromptRejected("WORDS_CHANGED")


def _fillers_out(text: str, language: str) -> str:
    """The text without its hesitations, one space between words."""
    from services.transcript_smoothing import without_fillers
    return _SPACE.sub(" ", without_fillers(text, language)).strip()


def _seconds(text: str) -> float:
    """How long the text takes said a little slower, with one pause."""
    return len(_words(text)) / SLOW_WORDS_PER_SECOND + 0.6


def _without_fillers(text: str, language: str) -> str:
    """The sentence with its hesitations out; refused when there were none
    (then there is nothing to hear differently)."""
    cleaned = _fillers_out(text, language)
    if not cleaned or _words(cleaned) == _words(text):
        raise PromptRejected("NO_FILLERS_TO_REMOVE")
    return cleaned


def build(*, sentence: str, exercise: dict, practice_id: str, language: str) -> dict:
    """One request for ``ElevenLabsClient.speak``, plus what to validate."""
    language = require_language(language)
    problem = str((exercise or {}).get("exercise") or "")
    text = _clean(sentence)
    if problem == "fillers":
        # The words the clip must say are the sentence without its fillers.
        text = _without_fillers(text, language)
    if not text or len(_words(text)) < 3:
        raise PromptRejected("SENTENCE_TOO_SHORT")
    if len(text) > int(Config.AI_VOICE_MAX_SENTENCE_CHARACTERS):
        raise PromptRejected("SENTENCE_TOO_LONG")
    # Said a little slower, with one pause, it must fit the clip limit.
    if _seconds(text) > float(Config.AI_VOICE_MAX_CLIP_SECONDS):
        raise PromptRejected("SENTENCE_TOO_LONG_TO_SAY")
    phrase = (exercise or {}).get("target_phrase")
    if problem == "pace":
        prepared = _pace(text, language)
    elif problem == "pause" and phrase:
        prepared = _pause(text, str(phrase))
    elif problem == "stress" and phrase:
        prepared = _stress(
            text, str(phrase), opening_emphasis=bool(exercise.get("opening_emphasis")),
        )
    elif problem == "fillers":
        prepared = text
    else:
        raise PromptRejected("UNSUPPORTED_EXERCISE")
    check_text(prepared, text)
    body = {
        "text": prepared,
        "model_id": Config.ELEVENLABS_MODEL_ID,
        "language_code": language,
        "voice_settings": dict(VOICE_SETTINGS),
        "seed": _seed(practice_id),
        "apply_text_normalization": "auto",
    }
    return {
        "body": body,
        "prepared_text": prepared,
        "spoken_words": _words(text),
        "validation_target": {
            "exercise": problem,
            "target_phrase": phrase,
            "target_change": (exercise or {}).get("target_change"),
        },
        # What may be stored for debugging: no audio, no voice id, no key.
        "metadata": {
            "builder_version": BUILDER_VERSION,
            "model_id": Config.ELEVENLABS_MODEL_ID,
            "language": language,
            "voice_settings": dict(VOICE_SETTINGS),
            "output_format": OUTPUT_FORMAT,
            "tags": sorted({t.lower() for t in _TAG.findall(prepared)}),
            "characters": len(prepared),
        },
    }


_SENTENCE = re.compile(r"[^.!?]+(?:[.!?]+[\"'”)]*|$)")
_JOINING = {
    "en": frozenset({"because", "but", "so", "and", "which", "when", "if"}),
    "pl": frozenset({"bo", "ale", "więc", "i", "który", "kiedy", "jeśli", "że"}),
}


def _said(text: str, drop_fillers: bool, language: Optional[str]) -> str:
    """The words the clip would say for this span, as ``build`` counts them."""
    words = _clean(text)
    return _fillers_out(words, require_language(language)) if drop_fillers else words


def fits_clip(text: str, *, drop_fillers: bool = False, language: Optional[str] = None) -> bool:
    """True when ``build`` would take the text: under the character limit,
    and short enough to say a little slower, with one pause, in a clip."""
    words = _said(text, drop_fillers, language)
    return (len(words) <= int(Config.AI_VOICE_MAX_SENTENCE_CHARACTERS)
            and _seconds(words) <= float(Config.AI_VOICE_MAX_CLIP_SECONDS))


def _anchor(text: str, phrase: Optional[str], drop_fillers: bool,
            language: Optional[str]) -> tuple[int, int]:
    """Where the clip's lesson sits: the target phrase, else (the fillers
    clip) the first hesitation, else the opening."""
    match = _locate(text, phrase) if phrase else None
    if match is None and drop_fillers:
        from services.transcript_smoothing import _filler_re, hesitations_for
        match = _filler_re(hesitations_for(require_language(language))).search(text)
    return (match.start(), match.end()) if match else (0, 0)


def _covering(spans: list[tuple[int, int]], start: int, end: int) -> list[int]:
    """The indexes of the spans that overlap [start, end) (an empty range
    counts as its first character); [0] when none does."""
    return [k for k, (s, e) in enumerate(spans) if s < max(end, start + 1) and e > start] or [0]


def _sentence_span(text: str, start: int, end: int, drop_fillers: bool,
                   language: str) -> Optional[tuple[int, int]]:
    """The sentences holding [start, end), grown by their neighbours while
    the whole still fits; None when those sentences alone do not fit."""
    spans = [(m.start() + len(m.group(0)) - len(m.group(0).lstrip()), m.end())
             for m in _SENTENCE.finditer(text) if m.group(0).strip()]
    held = _covering(spans, start, end)
    i, j = held[0], held[-1]
    if not fits_clip(text[spans[i][0]:spans[j][1]], drop_fillers=drop_fillers,
                     language=language):
        return None
    grew = True
    while grew:
        grew = False
        for a, b in ((i - 1, j), (i, j + 1)):
            if (0 <= a and b < len(spans)
                    and fits_clip(text[spans[a][0]:spans[b][1]],
                                  drop_fillers=drop_fillers, language=language)):
                i, j, grew = a, b, True
                break
    return spans[i][0], spans[j][1]


def _word_window(text: str, start: int, end: int, drop_fillers: bool,
                 language: str) -> tuple[int, int]:
    """A window of words centred on [start, end) that fits, cut at a comma
    or a joining word when one is inside it."""
    words = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    inside = _covering(words, start, end)
    lo, hi = inside[0], inside[-1]

    def fit(a: int, b: int) -> bool:
        return fits_clip(text[words[a][0]:words[b][1]], drop_fillers=drop_fillers,
                         language=language)

    left = True
    while True:
        a, b = (lo - 1, hi) if left else (lo, hi + 1)
        if not (0 <= a and b < len(words)):
            a, b = (lo, hi + 1) if left else (lo - 1, hi)
        if not (0 <= a and b < len(words)) or not fit(a, b):
            break
        lo, hi, left = a, b, not left
    first, last = inside[0], inside[-1]

    def word(k: int) -> str:
        return text[words[k][0]:words[k][1]]

    joining = _JOINING[language]
    cuts = [k for k in range(lo + 1, first + 1)
            if word(k - 1)[-1] in ",;:" or word(k).casefold().strip(",;:") in joining]
    ends = [k for k in range(last, hi) if word(k)[-1] in ",;:.!?"]
    lo, hi = (cuts[0] if cuts else lo), (ends[-1] if ends else hi)
    return words[lo][0], words[hi][1]


def fit_to_clip(text: str, phrase: Optional[str] = None, *, drop_fillers: bool = False,
                language: str) -> str:
    """The words a clip can say (founder 2026-11-04, N459 item 3): the text
    unchanged when it fits; otherwise the shortest natural part of it that
    fits and holds what the clip teaches. Whole sentences first (the one
    with the phrase, then its neighbours while they fit); a sentence too
    long alone gives a window of words around the phrase, cut at a comma
    or a joining word. No phrase: from the first hesitation (the fillers
    clip, ``drop_fillers``) or the opening. The words are the speaker's own,
    cut, never changed. Pure."""
    language = require_language(language)
    text = str(text or "")
    if fits_clip(text, drop_fillers=drop_fillers, language=language):
        return text
    start, end = _anchor(text, phrase, drop_fillers, language)
    span = _sentence_span(text, start, end, drop_fillers, language) or _word_window(
        text, start, end, drop_fillers, language)
    return text[span[0]:span[1]].strip().rstrip(",;:").strip()
