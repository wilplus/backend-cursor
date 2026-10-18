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

BUILDER_VERSION = "ai-voice-prompt-v1"
ALLOWED_TAGS = frozenset({"[slowly]", "[pause]"})
VOICE_SETTINGS = {"stability": 0.55, "similarity_boost": 0.9}
OUTPUT_FORMAT = "mp3_44100_128"

_TAG = re.compile(r"\[[^\]]*\]")
_SPACE = re.compile(r"\s+")
_CLAUSE = re.compile(r"\s(because|but|so|and|which|when|if)\s", re.IGNORECASE)


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
    return re.findall(r"[a-z0-9']+", text.lower())


def _locate(text: str, phrase: str) -> Optional[re.Match]:
    words = [re.escape(w) for w in phrase.split()]
    if not words:
        return None
    return re.compile(r"\b" + r"\W+".join(words) + r"\b", re.IGNORECASE).search(text)


def _seed(practice_id: str) -> int:
    return int.from_bytes(hashlib.sha256(practice_id.encode()).digest()[:4], "big")


def _pace(text: str) -> str:
    # One breath at each joining word that has no punctuation before it.
    slower = _CLAUSE.sub(lambda m: f", {m.group(1)} ", text)
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


def _stress(text: str, phrase: str) -> str:
    match = _locate(text, phrase)
    if match is None:
        raise PromptRejected("TARGET_PHRASE_NOT_IN_SENTENCE")
    return text[:match.start()] + match.group(0).upper() + text[match.end():]


def check_text(prepared: str, original: str) -> None:
    """Reject anything but the original words plus whitelisted tags."""
    for tag in _TAG.findall(prepared):
        if tag.lower() not in ALLOWED_TAGS:
            raise PromptRejected("UNSUPPORTED_TAG")
    if _words(_TAG.sub(" ", prepared)) != _words(original):
        raise PromptRejected("WORDS_CHANGED")


def _without_fillers(text: str) -> str:
    """The sentence with its hesitations out; refused when there were none
    (then there is nothing to hear differently)."""
    from services.ai_voice_severity import LANE_LANGUAGE
    from services.transcript_smoothing import without_fillers
    cleaned = _SPACE.sub(" ", without_fillers(text, LANE_LANGUAGE)).strip()
    if not cleaned or _words(cleaned) == _words(text):
        raise PromptRejected("NO_FILLERS_TO_REMOVE")
    return cleaned


def build(*, sentence: str, exercise: dict, practice_id: str) -> dict:
    """One request for ``ElevenLabsClient.speak``, plus what to validate."""
    problem = str((exercise or {}).get("exercise") or "")
    text = _clean(sentence)
    if problem == "fillers":
        # The words the clip must say are the sentence without its fillers.
        text = _without_fillers(text)
    if not text or len(_words(text)) < 3:
        raise PromptRejected("SENTENCE_TOO_SHORT")
    if len(text) > int(Config.AI_VOICE_MAX_SENTENCE_CHARACTERS):
        raise PromptRejected("SENTENCE_TOO_LONG")
    # Said a little slower, with one pause, it must fit the clip limit.
    if len(text.split()) / SLOW_WORDS_PER_SECOND + 0.6 > float(Config.AI_VOICE_MAX_CLIP_SECONDS):
        raise PromptRejected("SENTENCE_TOO_LONG_TO_SAY")
    phrase = (exercise or {}).get("target_phrase")
    if problem == "pace":
        prepared = _pace(text)
    elif problem == "pause" and phrase:
        prepared = _pause(text, str(phrase))
    elif problem == "stress" and phrase:
        prepared = _stress(text, str(phrase))
    elif problem == "fillers":
        prepared = text
    else:
        raise PromptRejected("UNSUPPORTED_EXERCISE")
    check_text(prepared, text)
    body = {
        "text": prepared,
        "model_id": Config.ELEVENLABS_MODEL_ID,
        "language_code": "en",
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
            "voice_settings": dict(VOICE_SETTINGS),
            "output_format": OUTPUT_FORMAT,
            "tags": sorted({t.lower() for t in _TAG.findall(prepared)}),
            "characters": len(prepared),
        },
    }
