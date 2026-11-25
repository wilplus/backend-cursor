"""Is this AI clip good enough to be heard? (founder lock 2026-10-12, D7)

A clip the provider returned is not yet a clip anyone hears. It is shown
only when every check passes:

  exists      the bytes are there and decode
  clipping    almost no samples at full scale
  silence     not mostly silence, no long dead air
  duration    near what the sentence takes to say, and never over
              Config.AI_VOICE_MAX_CLIP_SECONDS (17 s, founder 2026-10-13)
  words       re-transcribed (the existing Whisper, through the permit), the
              same words as the speaker's own sentence
  exercise    pace: slower than the original, but not dragged out
              pause: one natural pause right before the target phrase,
                     read from the audio's silence (Whisper's word times
                     swallow short silences)
              stress: the target phrase louder than the rest, not shouted
  fillers: not one hesitation heard in the clip, using the recording language

Every threshold is a named constant here, so tuning is one reviewed edit.
Nothing in the result is ever shown to the speaker (AC-9).
"""
from __future__ import annotations

import statistics
import unicodedata
from typing import Any, Optional

from config import Config
from services.ai_voice_language import require as require_language
from services.ai_voice_language import tokens as word_tokens
from services.rater_languages import normalize_provider_language

VALIDATOR_VERSION = "ai-voice-validator-v4"

CLIPPED_SAMPLE = 0.999
MAX_CLIPPED_SHARE = 0.001
SILENT_DB = -45.0
MAX_SILENT_SHARE = 0.45
MAX_DEAD_AIR_S = 1.6
MIN_DURATION_RATIO, MAX_DURATION_RATIO = 0.6, 2.2
MAX_WORD_ERROR_RATE = 0.10
PACE_MAX_RATIO, PACE_MIN_RATIO = 0.97, 0.70
# Up to 1.5 s: the founder's smoke run held a natural 1.24 s beat before the
# main point (2026-10-14); still under MAX_DEAD_AIR_S.
PAUSE_MIN_S, PAUSE_MAX_S = 0.3, 1.5
PAUSE_OVER_MEDIAN = 1.8
STRESS_MIN_DB, STRESS_MAX_DB = 1.5, 10.0

_FRAME_S = 0.02
_POLISH_STROKE_FOLD = str.maketrans({"ł": "l", "Ł": "L"})


def _tokens(text: str) -> list[str]:
    """Words in the clip check's deliberately narrow comparison form.

    Whisper can return Polish without diacritics, or with canonically
    decomposed Unicode, even when the audio says the requested word.  Folding
    those spelling-only differences keeps the word fence strict: punctuation,
    case and accents may differ, but a different lexical token still costs a
    full edit in the existing word-error-rate check.
    """
    decomposed = unicodedata.normalize(
        "NFKD", str(text or "").translate(_POLISH_STROKE_FOLD)
    )
    comparable = "".join(
        character for character in decomposed
        if unicodedata.category(character) != "Mn"
    )
    return word_tokens(comparable)


def _spoken_tokens(words: list[str]) -> list[str]:
    return [token for word in words for token in _tokens(word)]


def _word_error_rate(said: list[str], heard: list[str]) -> float:
    if not said:
        return 1.0
    previous = list(range(len(heard) + 1))
    for i, a in enumerate(said, 1):
        row = [i]
        for j, b in enumerate(heard, 1):
            row.append(min(previous[j] + 1, row[j - 1] + 1,
                           previous[j - 1] + (a != b)))
        previous = row
    return previous[-1] / len(said)


def _timed_words(transcription: dict) -> list[dict]:
    out = []
    for w in (transcription or {}).get("words") or []:
        if not isinstance(w, dict):
            continue
        start, end = w.get("start"), w.get("end")
        token = _tokens(str(w.get("word") or ""))
        if (isinstance(start, (int, float)) and isinstance(end, (int, float))
                and end > start and token):
            out.append({"t": token[0], "start": float(start), "end": float(end)})
    return out


def _frames_db(pcm, sample_rate: int) -> list[float]:
    import math
    size = max(1, int(_FRAME_S * sample_rate))
    out = []
    for i in range(0, len(pcm) - size + 1, size):
        frame = pcm[i:i + size]
        rms = math.sqrt(float((frame * frame).mean()) + 1e-12)
        out.append(20.0 * math.log10(rms + 1e-12))
    return out


def _longest_run(flags: list[bool]) -> int:
    best = run = 0
    for flag in flags:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best


def _find_phrase(words: list[dict], phrase: str) -> Optional[int]:
    target = _tokens(phrase)
    if not target:
        return None
    tokens = [w["t"] for w in words]
    for i in range(len(tokens) - len(target) + 1):
        if tokens[i:i + len(target)] == target:
            return i
    return None


def _span_db(dbs: list[float], start: float, end: float) -> Optional[float]:
    a, b = int(start / _FRAME_S), int(end / _FRAME_S)
    voiced = [d for d in dbs[a:b] if d > SILENT_DB]
    return statistics.mean(voiced) if voiced else None


def _check_pace(words: list[dict], original_wpm: Optional[float]) -> dict:
    m: dict[str, Any] = {}
    speaking = words[-1]["end"] - words[0]["start"]
    wpm = 60.0 * len(words) / speaking if speaking > 0 else None
    m.update(generated_wpm=wpm, original_wpm=original_wpm)
    if wpm is None or not original_wpm:
        return {"passed": False, "measurements": m, "failed": ["pace_unmeasurable"]}
    ratio = wpm / original_wpm
    m["ratio"] = round(ratio, 3)
    failed = (["not_slower"] if ratio > PACE_MAX_RATIO
              else ["too_slow"] if ratio < PACE_MIN_RATIO else [])
    return {"passed": not failed, "measurements": m, "failed": failed}


def _silent_runs(dbs: list[float]) -> list[tuple[int, int]]:
    """(first frame, frame count) of each silence inside the speech: the
    lead-in and the tail are not pauses."""
    runs, start = [], None
    for i, db in enumerate(list(dbs) + [0.0]):
        if db <= SILENT_DB and start is None:
            start = i
        elif db > SILENT_DB and start is not None:
            if start > 0 and i < len(dbs):
                runs.append((start, i - start))
            start = None
    return runs


def _check_pause(words: list[dict], dbs: list[float], index: int) -> dict:
    """The pause before the target phrase, read from the audio's silence.

    Whisper's word times stretch the words over a short silence (the
    founder's smoke run, 2026-10-13: a clearly audible pause read as 0 s),
    so the pause is the longest silence between the start of the word
    before the phrase and the end of the phrase's first word; the word gap
    counts only when it is longer."""
    gap = max(0.0, words[index]["start"] - words[index - 1]["end"])
    lo = int(words[index - 1]["start"] / _FRAME_S)
    hi = int(words[index]["end"] / _FRAME_S) + 1
    runs = _silent_runs(dbs)
    here = [n for (i, n) in runs if i < hi and i + n > lo]
    others = [n * _FRAME_S for (i, n) in runs if not (i < hi and i + n > lo)]
    pause = max([gap] + [n * _FRAME_S for n in here])
    median = statistics.median(others) if others else 0.0
    m = {"pause_s": round(pause, 3), "word_gap_s": round(gap, 3),
         "median_other_silence_s": round(median, 3)}
    failed = []
    if not PAUSE_MIN_S <= pause <= PAUSE_MAX_S:
        failed.append("pause_length")
    if pause < PAUSE_OVER_MEDIAN * max(median, 0.05):
        failed.append("pause_not_distinct")
    return {"passed": not failed, "measurements": m, "failed": failed}


def _check_stress(words: list[dict], dbs: list[float], index: int, phrase: str, *,
                  opening_emphasis: bool = False) -> dict:
    n = len(_tokens(phrase))
    start, end = words[index]["start"], words[index + n - 1]["end"]
    inside = _span_db(dbs, start, end)
    around = [d for d in (_span_db(dbs, words[0]["start"], start),
                          _span_db(dbs, end, words[-1]["end"])) if d is not None]
    if inside is None or not around:
        return {"passed": False, "measurements": {}, "failed": ["stress_unmeasurable"]}
    contrast = inside - statistics.mean(around)
    m = {"contrast_db": round(contrast, 2)}
    failed = (["not_stressed"] if contrast < STRESS_MIN_DB
              else ["exaggerated"] if contrast > STRESS_MAX_DB else [])
    if opening_emphasis:
        # Measure through the emphasized phrase, including the lead-in. Pauses
        # later in the example can still give the rest of the thought room.
        opening = dbs[:int(end / _FRAME_S)]
        gap = round(_longest_run([db <= SILENT_DB for db in opening]) * _FRAME_S, 3)
        m["opening_gap_s"] = gap
        if gap > Config.AI_VOICE_OPENING_MAX_GAP_S:
            failed.append("opening_gap")
    return {"passed": not failed, "measurements": m, "failed": failed}


def opening_contrast(pcm, sample_rate: int, transcript_words: list[dict]) -> float | None:
    """Relative loudness of the first phrase, using the demo validator's span read."""
    words = _timed_words({"words": transcript_words})
    if len(words) < 4:
        return None
    phrase = " ".join(word["t"] for word in words[:3])
    read = _check_stress(words, _frames_db(pcm, sample_rate), 0, phrase, opening_emphasis=True)
    return read["measurements"].get("contrast_db")


def _check_fillers(words: list[dict], language: str) -> dict:
    """Not one hesitation in what was heard in the recording's language."""
    from services.transcript_smoothing import hesitations_for
    fillers = set(_spoken_tokens(list(hesitations_for(language))))
    heard = sum(1 for w in words if w["t"] in fillers)
    return {"passed": heard == 0, "measurements": {"fillers_heard": heard},
            "failed": ["fillers_heard"] if heard else []}


def check_exercise(problem: str, *, words: list[dict], dbs: list[float],
                   phrase: Optional[str], original_wpm: Optional[float],
                   language: str, opening_emphasis: bool = False) -> dict:
    """``{"passed", "measurements", "failed"}`` for the one exercise."""
    if len(words) < 3:
        return {"passed": False, "measurements": {}, "failed": ["no_timed_words"]}
    if problem == "pace":
        return _check_pace(words, original_wpm)
    if problem == "fillers":
        return _check_fillers(words, language)
    if problem not in ("pause", "stress"):
        return {"passed": False, "measurements": {}, "failed": ["unknown_exercise"]}
    index = _find_phrase(words, phrase or "")
    if index is None or (index == 0 and (problem == "pause" or not opening_emphasis)):
        return {"passed": False, "measurements": {}, "failed": ["target_not_found"]}
    if problem == "pause":
        return _check_pause(words, dbs, index)
    return _check_stress(words, dbs, index, phrase or "", opening_emphasis=opening_emphasis)


def _check_duration(duration: float, original: Optional[float], *,
                    opening_emphasis: bool) -> tuple[dict[str, float], list[str]]:
    measurements = {"duration_s": round(duration, 2)}
    failed = []
    if duration > Config.AI_VOICE_MAX_CLIP_SECONDS:
        failed.append("too_long")
    if original and original > 0:
        ratio = duration / original
        measurements["duration_ratio"] = round(ratio, 3)
        if not MIN_DURATION_RATIO <= ratio <= MAX_DURATION_RATIO:
            failed.append("duration")
        elif opening_emphasis and abs(ratio - 1) > Config.AI_VOICE_OPENING_MAX_DURATION_DRIFT:
            failed.append("opening_pace")
    elif opening_emphasis:
        failed.append("pace_unmeasurable")
    return measurements, failed


def validate(*, audio: bytes, transcription: Optional[dict], spoken_words: list[str],
             exercise: dict, original_wpm: Optional[float],
             original_duration_s: Optional[float], decode=None,
             sample_rate: int = 16000, language: str) -> dict:
    """The brief's result shape: ``passed``, ``exercise``, ``measurements``,
    ``failed_checks``, ``reason`` (the first failed check), ``version``."""
    language = require_language(language)
    problem = str((exercise or {}).get("exercise") or "")
    opening_emphasis = problem == "stress" and bool(exercise.get("opening_emphasis"))
    result: dict[str, Any] = {"passed": False, "exercise": problem,
                              "measurements": {}, "failed_checks": [],
                              "reason": None, "version": VALIDATOR_VERSION,
                              "language": language}
    failed: list[str] = result["failed_checks"]
    m: dict[str, Any] = result["measurements"]

    if not audio:
        failed.append("no_audio")
    else:
        if decode is None:
            from services.audio_metrics import decode_audio_to_pcm as decode
        pcm = decode(audio)
        if pcm is None or len(pcm) < sample_rate // 2:
            failed.append("undecodable")
        else:
            clipped = float((abs(pcm) >= CLIPPED_SAMPLE).mean())
            m["clipped_share"] = round(clipped, 5)
            if clipped > MAX_CLIPPED_SHARE:
                failed.append("clipped")
            dbs = _frames_db(pcm, sample_rate)
            silent = [d <= SILENT_DB for d in dbs]
            m["silent_share"] = round(sum(silent) / max(1, len(silent)), 3)
            m["longest_silence_s"] = round(_longest_run(silent) * _FRAME_S, 2)
            if m["silent_share"] > MAX_SILENT_SHARE:
                failed.append("mostly_silence")
            if m["longest_silence_s"] > MAX_DEAD_AIR_S:
                failed.append("dead_air")
            duration_metrics, duration_failures = _check_duration(
                len(pcm) / float(sample_rate), original_duration_s,
                opening_emphasis=opening_emphasis,
            )
            m.update(duration_metrics)
            failed.extend(duration_failures)
            if transcription is None:
                failed.append("not_transcribed")
            else:
                heard_language = normalize_provider_language(transcription.get("language"))
                if heard_language and heard_language != language:
                    failed.append("language_mismatch")
                said = _spoken_tokens(list(spoken_words))
                heard = _tokens(str(transcription.get("transcript") or ""))
                wer = _word_error_rate(said, heard)
                m["word_error_rate"] = round(wer, 3)
                if wer > MAX_WORD_ERROR_RATE:
                    failed.append("words_changed")
                verdict = check_exercise(
                    problem, words=_timed_words(transcription), dbs=dbs,
                    phrase=(exercise or {}).get("target_phrase"),
                    original_wpm=original_wpm, language=language,
                    opening_emphasis=opening_emphasis)
                m.update(verdict["measurements"])
                failed.extend(verdict["failed"])
    result["passed"] = not failed
    result["reason"] = failed[0] if failed else None
    return result
