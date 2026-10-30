"""What the transcriber wrote that nobody said (N276).

Whisper learnt on videos, so a stretch with no words in it can come back as
one of the videos' stock lines ("Thanks for watching", "Subtitles by the
Amara.org community"), and it tells us so: each segment carries how sure it
is there was no speech (``no_speech_prob``) and how sure it is of its words
(``avg_logprob``). Every transcription goes through
``services/openai_service.transcribe_audio``, which drops such segments here
before any caller sees them: a Take, a plan answer, a note, a coach's word.
The Ideal Text is only what the speaker said (Never 5).

Two kinds of line, two rules:

* a segment Whisper itself would call silence (its own rule: no speech
  likely and its words unsure) is dropped, whatever it says;
* a video's stock line ("Thanks for watching") is dropped with only weak
  evidence of silence. A plain "Thank you." is never dropped for its words
  alone: a talk often ends with one.

``heard_nothing`` is for a short voice answer read whole (the plan's
questions, N262 item 2): one that is only stock lines, the plain ones too,
was not an answer.
"""
from __future__ import annotations

import re
from typing import Any, Optional

#: Lines only a video says: dropped on weak evidence of silence.
VIDEO_LINES = frozenset({
    "thank you for watching", "thanks for watching", "thank you so much for watching",
    "thank you very much for watching", "please subscribe", "like and subscribe",
    "subscribe to my channel", "see you in the next video",
})

#: Lines a speaker may well say; a stock line only when nothing else was said.
PLAIN_LINES = frozenset({
    "you", "bye", "bye bye", "thank you", "thanks", "thank you very much",
    "thank you so much", "thank you for listening", "thanks for listening",
    "see you next time",
})

#: Whisper's own silence rule (its decoder's defaults).
NO_SPEECH = 0.6
UNSURE_LOGPROB = -1.0
#: Weak evidence of silence: enough to drop a video's line.
SOME_NO_SPEECH = 0.3


def _sentences(text: str) -> list[str]:
    parts = [" ".join(re.sub(r"[^\w' ]+", " ", p).split()) for p in re.split(r"[.!?,\n]+", text.lower())]
    return [p for p in parts if p]


def _only(text: str, lines: frozenset) -> bool:
    if "amara.org" in text.lower():  # "Subtitles by the Amara.org community", in any language
        return True
    parts = _sentences(text)
    return bool(parts) and all(p in lines for p in parts)


def heard_nothing(text: str) -> bool:
    """Is a short answer, read whole, only the transcriber's stock lines?"""
    return _only(text, VIDEO_LINES | PLAIN_LINES)


def _num(seg: Any, name: str) -> Optional[float]:
    value = getattr(seg, name, None)
    if value is None and isinstance(seg, dict):
        value = seg.get(name)
    return float(value) if isinstance(value, (int, float)) else None


def unspoken(seg: Any, text: str) -> bool:
    """Is this segment the transcriber's, not the speaker's?"""
    no_speech = _num(seg, "no_speech_prob")
    logprob = _num(seg, "avg_logprob")
    if no_speech is not None and logprob is not None and no_speech > NO_SPEECH and logprob < UNSURE_LOGPROB:
        return True
    return _only(text, VIDEO_LINES) and (no_speech is None or no_speech >= SOME_NO_SPEECH)
