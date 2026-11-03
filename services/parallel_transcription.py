"""A Take transcribed in parts at the same time (N406), behind
``PARALLEL_TRANSCRIPTION_ENABLED`` (off by default).

One call for a whole Take makes the wait after Stop grow with the Take's
length. Here the recording is cut at its quietest moments into up to
``PARTS`` parts, each part is transcribed by the same authorized adapter
(each call under its own permit, as every provider call), and the words and
segments are put back on the Take's clock. The transcription step then takes
about as long as one part.

Same result shape as ``AuthorizedProviderAdapter.transcribe_audio``:
``{text, duration, language, segments, words}``.

``None`` means "not done in parts": too short to split, the audio could not
be decoded, or a part failed. The caller then makes the one whole-file call
it always made, so a failure here costs time, never the transcript.
"""
from __future__ import annotations

import io
import logging
import wave
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

#: At most this many parts: the pipeline's thread pool runs four at once.
PARTS = 4
#: No part shorter than this: a part needs a few sentences of context.
MIN_PART_SECONDS = 45.0
#: A cut lands in the quietest stretch this long...
QUIET_WINDOW_SECONDS = 0.3
#: ...within this share of a part's length around its ideal place.
SEARCH_SHARE = 0.15
_FRAME_SECONDS = 0.02


def cut_points(pcm: np.ndarray, sample_rate: int) -> list[float]:
    """The seconds to cut at: none for a recording shorter than two parts;
    otherwise each cut in the quietest ``QUIET_WINDOW_SECONDS`` near where
    equal parts would end, so no word is cut in two."""
    duration = len(pcm) / float(sample_rate)
    parts = min(PARTS, int(duration // MIN_PART_SECONDS))
    if parts < 2:
        return []
    frame = max(1, int(_FRAME_SECONDS * sample_rate))
    usable = len(pcm) // frame * frame
    energy = np.sqrt(np.mean(pcm[:usable].reshape(-1, frame) ** 2, axis=1))
    span = max(1, int(round(QUIET_WINDOW_SECONDS / _FRAME_SECONDS)))
    smooth = np.convolve(energy, np.ones(span) / span, mode="same")
    part = duration / parts
    reach = part * SEARCH_SHARE
    cuts: list[float] = []
    for k in range(1, parts):
        ideal = k * part
        lo = max(0, int((ideal - reach) / _FRAME_SECONDS))
        hi = min(len(smooth), int((ideal + reach) / _FRAME_SECONDS))
        if hi <= lo:
            continue
        quietest = lo + int(np.argmin(smooth[lo:hi]))
        cuts.append(round(quietest * _FRAME_SECONDS, 3))
    return cuts


def _wav(pcm: np.ndarray, sample_rate: int) -> bytes:
    """16-bit mono WAV of float PCM: small, and every provider reads it."""
    data = (np.clip(pcm, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(data)
    return out.getvalue()


def stitch(parts: list[tuple[float, dict]], total_seconds: float) -> dict:
    """Each part's transcription, given with the second it starts at, as one
    transcription on the recording's clock. The language is the one most of
    the recording was heard in."""
    segments: list[dict] = []
    words: list[dict] = []
    texts: list[str] = []
    heard: dict[str, float] = {}
    for start, result in parts:
        for seg in result.get("segments") or []:
            segments.append({**seg, "start": float(seg.get("start") or 0.0) + start,
                             "end": float(seg.get("end") or 0.0) + start})
        for word in result.get("words") or []:
            words.append({**word, "start": float(word.get("start") or 0.0) + start,
                          "end": float(word.get("end") or 0.0) + start})
        text = (result.get("text") or "").strip()
        if text:
            texts.append(text)
        if result.get("language"):
            lang = str(result["language"])
            heard[lang] = heard.get(lang, 0.0) + (float(result.get("duration") or 0.0) or 1.0)
    # The provider's own duration is its last segment's end; the same here,
    # on the whole clock, and never past the recording.
    duration = min(total_seconds, segments[-1]["end"]) if segments else 0.0
    return {
        "text": " ".join(texts),
        "duration": duration,
        "language": max(heard, key=lambda k: heard[k]) if heard else None,
        "segments": segments,
        "words": words,
    }


def transcribe_in_parts(
    adapter: Any, audio_bytes: bytes, *,
    vocabulary: Optional[list] = None, language: Optional[str] = None,
    usage_surface: str, usage_user_id: Optional[str], usage_session_id: str,
) -> Optional[dict]:
    """The recording transcribed in parts at once, or None (see the module
    docstring). A refusal of the processing authorization is never
    swallowed: it is the same refusal the whole-file call would meet."""
    from services.audio_metrics import SAMPLE_RATE, decode_audio_to_pcm
    from services.parallel import run_in_parallel
    from services.processing_authorization import ProcessingAuthorizationError

    pcm = decode_audio_to_pcm(audio_bytes)
    if pcm is None or not len(pcm):
        return None
    cuts = cut_points(pcm, SAMPLE_RATE)
    if not cuts:
        return None
    total = len(pcm) / float(SAMPLE_RATE)
    bounds = [0.0, *cuts, total]
    pieces = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]

    def hear(start: float, end: float) -> dict:
        audio, name = _wav(pcm[int(start * SAMPLE_RATE):int(end * SAMPLE_RATE)], SAMPLE_RATE), "part.wav"
        from services.recording_transcription import WHISPER_MAX_BYTES
        if len(audio) > WHISPER_MAX_BYTES:  # a very long Take's part
            from services.audio_metrics import compress_audio_for_whisper
            smaller = compress_audio_for_whisper(audio)
            if not smaller:
                raise ValueError("a part too large to transcribe")
            audio, name = smaller, "part.mp3"
        result = adapter.transcribe_audio(
            audio, name, vocabulary=vocabulary, language=language,
            usage_surface=usage_surface, usage_user_id=usage_user_id,
            usage_session_id=usage_session_id)
        if result is None:
            raise ValueError("no transcription for a part")
        return result

    def safely(start: float, end: float):
        try:
            return hear(start, end)
        except ProcessingAuthorizationError:
            raise
        except Exception as error:  # noqa: BLE001 -- the whole-file call takes over
            return error

    results = run_in_parallel(*(
        (lambda s=s, e=e: safely(s, e)) for s, e in pieces
    ), max_workers=PARTS)
    failed = [r for r in results if isinstance(r, Exception)]
    if failed:
        logger.warning(
            "parallel transcription: %d of %d parts failed (%s); "
            "the whole recording is transcribed in one call",
            len(failed), len(pieces), failed[0])
        return None
    logger.info("parallel transcription: %d parts, %.1fs", len(pieces), total)
    return stitch([(s, r) for (s, _), r in zip(pieces, results)], total)
