"""A recording sent in a host's chat: its words and plain facts.

The visitor's screen reads the walk from the same reply
(``POST /v2/chats/<id>/reply``), so the work finishes in that request.
A recording over 25 MB or 5 minutes is refused before any provider call.
ffmpeg is resolved the way every other recording is (``FFMPEG_PATH``, then
PATH, then the bundled imageio-ffmpeg binary). A wav can also be read with
soundfile when ffmpeg is not there. Word times come from the existing
Whisper client. librosa reads the loudness and the pitch of the two halves.

Nothing here scores a person or names a feeling. The sentences match the
chat builder's voice measures, which the visitor can tap.
"""
from __future__ import annotations

import base64
import io
import logging
import math
import os
import subprocess
from typing import Any, Optional

logger = logging.getLogger(__name__)

AUDIO_MAX = 25 * 1024 * 1024
AUDIO_MAX_SECONDS = 5 * 60
PAUSE_SECONDS = 1
_RATE = 16000
_SAFE_EXT = {"webm": "audio/webm", "m4a": "audio/mp4", "wav": "audio/wav",
             "mp3": "audio/mpeg", "ogg": "audio/ogg", "mp4": "audio/mp4"}


def too_big(raw: bytes) -> bool:
    return len(raw) > AUDIO_MAX


def too_long(seconds: float) -> bool:
    return seconds > AUDIO_MAX_SECONDS


def _whole(value: float) -> int:
    """The nearest whole number, halves away from zero, as the visitor's clock does."""
    return int(math.floor(float(value) + 0.5))


def clock(seconds: float) -> str:
    whole = max(0, _whole(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


def safe_name(name: str) -> str:
    """A filename the transcriber can label. The visitor's name is not a path."""
    ext = str(name or "").rsplit(".", 1)[-1].lower()
    if ext not in _SAFE_EXT:
        ext = "webm"
    return f"talk.{ext}"


def decode(raw: bytes, name: str) -> Optional[tuple[Any, int]]:
    """16 kHz mono float32 samples, or None when the bytes cannot be read."""
    loaded = _ffmpeg(raw)
    if loaded is None and str(name or "").lower().endswith(".wav"):
        loaded = _wav(raw)
    if loaded is None:
        return None
    audio, rate = loaded
    cap = _RATE * (AUDIO_MAX_SECONDS + 1)
    if len(audio) > cap:
        audio = audio[:cap]
    return audio, rate


def _ffmpeg(raw: bytes) -> Optional[tuple[Any, int]]:
    from services.audio_metrics import _resolve_ffmpeg_executable, ffmpeg_input
    exe = _resolve_ffmpeg_executable()
    if not exe:
        return None
    try:
        with ffmpeg_input(raw) as (source, stdin):
            proc = subprocess.run(
                [exe, "-i", source, "-t", str(AUDIO_MAX_SECONDS + 1),
                 "-f", "s16le", "-acodec", "pcm_s16le",
                 "-ar", str(_RATE), "-ac", "1", "pipe:1"],
                input=stdin, capture_output=True, timeout=30,
            )
        if proc.returncode != 0 or len(proc.stdout) < 2:
            return None
        import numpy as np
        samples = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
        return samples, _RATE
    except Exception:
        logger.warning("chat_voice: ffmpeg could not read the recording", exc_info=True)
        return None


def _wav(raw: bytes) -> Optional[tuple[Any, int]]:
    try:
        import numpy as np
        import soundfile as sf
        data, rate = sf.read(io.BytesIO(raw), dtype="float32", always_2d=True)
        mono = np.asarray(data.mean(axis=1), dtype=np.float32)
        rate = int(rate)
        if rate != _RATE and len(mono):
            import librosa
            mono = librosa.resample(mono, orig_sr=rate, target_sr=_RATE)
            rate = _RATE
        return mono, rate
    except Exception:
        logger.warning("chat_voice: the wav could not be read", exc_info=True)
        return None


def prepare(data_b64: str, name: str) -> dict:
    """``{error}`` or the samples. No provider call."""
    if not isinstance(data_b64, str) or len(data_b64) > (AUDIO_MAX * 4 // 3) + 8:
        return {"error": "too-big" if isinstance(data_b64, str) and data_b64 else "unreadable"}
    try:
        raw = base64.b64decode(data_b64, validate=True)
    except ValueError:
        return {"error": "unreadable"}
    if too_big(raw):
        return {"error": "too-big"}
    if not raw:
        return {"error": "unreadable"}
    loaded = decode(raw, name)
    if not loaded:
        return {"error": "unreadable"}
    audio, rate = loaded
    seconds = float(len(audio) / rate) if rate else 0.0
    if too_long(seconds):
        return {"error": "too-long"}
    return {"raw": raw, "audio": audio, "rate": rate, "seconds": seconds,
            "name": safe_name(name)}


def transcribe_words(raw: bytes, name: str, user_id: Optional[str]) -> list[dict]:
    """Word times from the existing Whisper client, or none when it is down."""
    model = (os.environ.get("OPENAI_TRANSCRIBE_MODEL") or "whisper-1").strip() or "whisper-1"
    filename = safe_name(name)
    try:
        from services.authorized_provider import scoped_adapter
        adapter = scoped_adapter()
        if adapter is not None:
            result = adapter.transcribe_audio(
                raw, filename, usage_surface="whisper_chat_builder",
                usage_user_id=user_id, usage_session_id="chat-builder",
                model=model,
            ) or {}
        else:
            from services.openai_service import OpenAIService
            service = OpenAIService()
            if not service.client:
                return []
            result = service.transcribe_audio(
                io.BytesIO(raw), filename, usage_surface="whisper_chat_builder",
                usage_user_id=user_id, usage_session_id="chat-builder",
                model=model,
            ) or {}
    except Exception:
        logger.warning("chat_voice: transcription failed", exc_info=True)
        return []
    words = []
    for item in result.get("words") or []:
        if not isinstance(item, dict):
            continue
        word = str(item.get("word") or "")
        start = item.get("start")
        if not word or not isinstance(start, (int, float)):
            continue
        end = item.get("end")
        words.append({"word": word, "start": float(start),
                      "end": float(end) if isinstance(end, (int, float)) else float(start)})
    return words


def _span(left: float, right: float) -> str:
    if not left or not right:
        return "unknown"
    ratio = (left / right) if left > right else (right / left)
    return "moves" if ratio >= 1.4 else "steady"


def _rms(chunk: Any) -> float:
    import numpy as np
    if len(chunk) == 0:
        return 0.0
    try:
        import librosa
        frames = librosa.feature.rms(y=np.asarray(chunk, dtype=np.float32))
        return float(np.mean(frames)) if frames.size else 0.0
    except Exception:
        logger.warning("chat_voice: loudness fell back", exc_info=True)
        return float(np.sqrt(np.mean(np.square(np.asarray(chunk, dtype=np.float32)))))


def _pitch_hz(chunk: Any, rate: int) -> Optional[float]:
    import numpy as np
    if rate <= 0 or len(chunk) < rate // 5:
        return None
    try:
        import librosa
        track = librosa.yin(np.asarray(chunk, dtype=np.float32), fmin=80, fmax=400, sr=rate)
    except Exception:
        logger.warning("chat_voice: pitch could not be read", exc_info=True)
        return None
    voiced = [float(hz) for hz in track if np.isfinite(hz) and float(hz) > 0]
    if not voiced:
        return None
    return float(np.median(voiced))


def _loudness(audio: Any) -> str:
    half = len(audio) // 2
    return _span(_rms(audio[:half]), _rms(audio[half:])) if len(audio) else "unknown"


def _pitch(audio: Any, rate: int) -> str:
    if not len(audio):
        return "unknown"
    half = len(audio) // 2
    left, right = _pitch_hz(audio[:half], rate), _pitch_hz(audio[half:], rate)
    if left is None or right is None:
        return "unknown"
    return _span(left, right)


def _pauses(words: list[dict]) -> list[dict]:
    found = []
    for prev, nxt in zip(words, words[1:]):
        gap = float(nxt.get("start", 0)) - float(prev.get("end", 0))
        if gap >= PAUSE_SECONDS:
            found.append({"at": float(prev.get("end", 0)), "seconds": max(1, _whole(gap))})
    return found


def _segments(words: list[dict], seconds: float) -> list[dict]:
    if seconds <= 0:
        return []
    width = seconds if seconds <= 15 else 10.0
    segments = []
    start = 0.0
    while start < seconds:
        end = min(seconds, start + width)
        count = sum(1 for word in words if start <= float(word.get("start", 0)) < end)
        minutes = (end - start) / 60
        segments.append({"start": start, "end": end,
                         "words_per_minute": _whole(count / minutes) if minutes else 0})
        start = end
    return segments


def measures(audio: Any, rate: int, words: list[dict]) -> dict:
    """Loudness and pitch of the two halves, pauses, and words in each stretch."""
    seconds = float(len(audio) / rate) if rate else 0.0
    span = seconds or (float(words[-1]["end"]) if words else 0.0)
    return {"seconds": seconds, "pauses": _pauses(words), "segments": _segments(words, span),
            "loudness": _loudness(audio), "pitch": _pitch(audio, rate)}


def facts(found: dict) -> list[str]:
    """Plain sentences about the recording. No feeling is named."""
    lines = []
    for pause in found.get("pauses") or []:
        n = int(pause["seconds"])
        unit = "second" if n == 1 else "seconds"
        lines.append(f"You paused for {n} {unit} at {clock(float(pause['at']))}.")
    pace = next((segment for segment in found.get("segments") or []
                 if segment.get("words_per_minute")), None)
    if pace:
        lines.append(
            f"From {clock(float(pace['start']))} to {clock(float(pace['end']))}, "
            f"the words came at about {pace['words_per_minute']} a minute.")
    if found.get("loudness") == "steady":
        lines.append("The loudness stayed even.")
    elif found.get("loudness") == "moves":
        lines.append("The loudness changed from one part to the next.")
    if found.get("pitch") == "steady":
        lines.append("The pitch stayed even.")
    elif found.get("pitch") == "moves":
        lines.append("The pitch moved from one part to the next.")
    return lines


def walk_from(found: dict, steps: list[str], ideal: bool) -> list[dict]:
    """The walk a visitor can tap. Times point at the recording."""
    beats = []
    pause = (found.get("pauses") or [None])[0]
    segments = found.get("segments") or []
    clear = next((segment for segment in segments if segment.get("words_per_minute")), None)
    if clear is None and segments:
        clear = segments[0]
    if "best" in steps and clear:
        beats.append({"key": "best",
                      "text": f"A clear stretch starts at {clock(float(clear['start']))}.",
                      "at": float(clear["start"])})
    if "fix" in steps:
        if pause:
            n = int(pause["seconds"])
            unit = "second" if n == 1 else "seconds"
            beats.append({"key": "fix",
                          "text": (f"You paused for {n} {unit} at {clock(float(pause['at']))}. "
                                   "You could say that part again."),
                          "at": float(pause["at"])})
        else:
            beats.append({"key": "fix",
                          "text": "The words ran on without a pause. You could leave a breath in one place.",
                          "at": 0})
    if "words" in steps:
        beats.append({"key": "words",
                      "text": "Keep a few words you want to say the same way next time.",
                      "at": None})
    if ideal:
        beats.append({"key": "ideal", "text": "Here is the text to keep.", "at": None})
    return beats


def hear(raw: bytes, name: str, audio: Any, rate: int, user_id: Optional[str]) -> dict:
    """Transcript, facts and the measures. Transcription is the one provider call."""
    words = transcribe_words(raw, name, user_id)
    found = measures(audio, rate, words)
    text = " ".join(word.get("word", "") for word in words).strip()
    return {"transcript": text, "facts": facts(found), "measures": found, "words": words}
