"""Pluggable ASR backends, all returning the production result shape.

Every provider returns exactly what ``openai_service.transcribe_audio``
returns — ``{text, duration, language, segments, words}``, word times in
SECONDS absolute to the recording — so the metrics never learn a
provider-specific shape and a winner can be wired into the live path
without reshaping anything.

DEPENDENCIES ARE DELIBERATELY NOT IN requirements.txt
-----------------------------------------------------
The local providers need torch + a model download (faster-whisper is
~2GB with large-v3; whisperx adds wav2vec2 on top). requirements.txt is
the PRODUCTION image — putting bench-only deps there would add gigabytes
to every Railway deploy to serve a harness that never runs there. They are
lazy-imported and a missing package degrades to a clear
``unavailable`` result, matching how every optional dependency in this
codebase behaves (pypdf, reportlab, python-docx, pywebpush).

Install locally, only when running a bake-off:
    pip install faster-whisper          # word timestamps, no API, no 25MB cap
    pip install whisperx                # + wav2vec2 forced alignment
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# The disfluent prompt from openai_service.transcribe_audio. Identical on
# purpose: the eval must transcribe the way production transcribes, or it
# is benchmarking a configuration we do not ship.
DISFLUENT_PROMPT = (
    "Umm, let me think like, hmm... Okay, so, uh, yeah. "
    "I mean, you know, it's like, um, well..."
)

_REGISTRY: dict[str, Callable] = {}


def register(name: str):
    def _wrap(fn: Callable) -> Callable:
        _REGISTRY[name] = fn
        return fn
    return _wrap


def available() -> list:
    return sorted(_REGISTRY)


def _unavailable(name: str, why: str) -> dict:
    logger.warning("asr_eval provider %s unavailable: %s", name, why)
    return {"text": "", "duration": 0.0, "language": None,
            "segments": [], "words": [],
            "unavailable": why, "provider": name}


def transcribe(provider: str, audio_path: str, *,
               language: Optional[str] = None,
               vocabulary: Any = None, **kw) -> dict:
    """Run one provider over one audio file. Never raises.

    A provider that errors returns an ``unavailable`` result rather than
    aborting the sweep — one bad file or one missing package must not cost
    the other 40 takes in the run.
    """
    fn = _REGISTRY.get(provider)
    if fn is None:
        return _unavailable(provider, f"unknown provider (have: {available()})")
    t0 = time.time()
    try:
        out = fn(audio_path, language=language, vocabulary=vocabulary, **kw)
    except Exception as e:
        return _unavailable(provider, f"{type(e).__name__}: {e}")
    out.setdefault("provider", provider)
    out["wall_seconds"] = round(time.time() - t0, 2)
    return out


# ── OpenAI ───────────────────────────────────────────────────────────────


def _openai_client():
    import openai  # lazy: the harness must import without a key

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return openai.OpenAI(api_key=key, timeout=900.0, max_retries=2)


def _openai_prompt(language: Any, vocabulary: Any) -> Optional[str]:
    """Reproduces transcribe_audio's language/prompt rule exactly.

    An English disfluency prompt on non-English audio biases detection
    toward English and can return garbage — production drops the prompt for
    declared non-English and keeps only the (language-neutral) vocabulary.
    The eval must do the same or its non-English numbers describe a
    configuration we do not run.
    """
    terms = [str(t).strip() for t in (vocabulary or []) if str(t).strip()][:40]
    lang = (str(language or "").strip().lower() or None)
    if lang and not lang.startswith("en"):
        return (", ".join(terms) + ".") if terms else None
    p = DISFLUENT_PROMPT
    if terms:
        p += " " + ", ".join(terms) + "."
    return p


def _openai_result(resp: Any, provider: str) -> dict:
    def attr(o: Any, n: str, d: Any = None) -> Any:
        return o.get(n, d) if isinstance(o, dict) else getattr(o, n, d)

    segments = []
    for s in (attr(resp, "segments", None) or []):
        segments.append({
            "start": float(attr(s, "start", 0.0) or 0.0),
            "end": float(attr(s, "end", 0.0) or 0.0),
            "text": (attr(s, "text", "") or "").strip(),
        })
    words = []
    for w in (attr(resp, "words", None) or []):
        st, en = attr(w, "start", None), attr(w, "end", None)
        if not isinstance(st, (int, float)):
            continue
        words.append({
            "word": str(attr(w, "word", "") or ""),
            "start": float(st),
            "end": float(en) if isinstance(en, (int, float)) else float(st),
        })
    duration = attr(resp, "duration", None)
    if not isinstance(duration, (int, float)):
        duration = segments[-1]["end"] if segments else (
            words[-1]["end"] if words else 0.0)
    return {
        "text": (attr(resp, "text", "") or ""),
        "duration": float(duration or 0.0),
        "language": attr(resp, "language", None),
        "segments": segments,
        "words": words,
        "provider": provider,
    }


@register("openai:whisper-1")
def _whisper_1(audio_path: str, *, language=None, vocabulary=None, **_) -> dict:
    """The INCUMBENT. Baseline for every comparison.

    Mirrors the live call byte-for-byte: verbose_json + both timestamp
    granularities + the same prompt rule.
    """
    client = _openai_client()
    with open(audio_path, "rb") as fh:
        data = fh.read()
    kwargs: dict = {
        "model": "whisper-1",
        "file": (os.path.basename(audio_path), data, "audio/mpeg"),
        "response_format": "verbose_json",
        "timestamp_granularities": ["segment", "word"],
    }
    lang = (str(language or "").strip().lower() or None)
    if lang:
        kwargs["language"] = lang
    prompt = _openai_prompt(language, vocabulary)
    if prompt:
        kwargs["prompt"] = prompt
    return _openai_result(
        client.audio.transcriptions.create(**kwargs), "openai:whisper-1")


def _gpt_transcribe(model: str):
    """Factory for the gpt-4o-* transcribe family.

    HEADS UP, and this is the whole reason the harness reports coverage
    first: as of this writing these models accept ``response_format=json``
    or ``text`` ONLY. ``verbose_json`` is rejected, and
    ``timestamp_granularities`` requires verbose_json — so these endpoints
    return NO word timestamps and NO segment timestamps. They will fail the
    coverage gate by design. That is a real finding about the migration, not
    a bug in this file, and the harness is written to surface it loudly
    rather than to average it away.

    Kept registered anyway so the claim is re-testable in one command the
    day OpenAI adds timestamps, instead of being a stale note in a doc.
    """
    def _fn(audio_path: str, *, language=None, vocabulary=None, **_) -> dict:
        client = _openai_client()
        with open(audio_path, "rb") as fh:
            data = fh.read()
        kwargs: dict = {
            "model": model,
            "file": (os.path.basename(audio_path), data, "audio/mpeg"),
            "response_format": "json",
        }
        lang = (str(language or "").strip().lower() or None)
        if lang:
            kwargs["language"] = lang
        prompt = _openai_prompt(language, vocabulary)
        if prompt:
            kwargs["prompt"] = prompt
        return _openai_result(client.audio.transcriptions.create(**kwargs),
                              f"openai:{model}")
    return _fn


for _m in ("gpt-4o-transcribe", "gpt-4o-mini-transcribe", "gpt-transcribe"):
    register(f"openai:{_m}")(_gpt_transcribe(_m))


# ── local / open-source ──────────────────────────────────────────────────


@register("faster-whisper")
def _faster_whisper(audio_path: str, *, language=None, vocabulary=None,
                    model_size: str = "large-v3", device: str = "auto",
                    compute_type: str = "default", **_) -> dict:
    """CTranslate2 Whisper with native word timestamps.

    Why it is in the bake-off: no 25MB cap and no request size limit at all
    (it reads the file), large-v3 is materially stronger than the API's
    whisper-1 on accented speech, and it returns word timestamps — the thing
    the newer OpenAI endpoints drop. Runs on CPU; a GPU makes it ~10x faster.
    """
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as e:
        raise RuntimeError(f"faster-whisper not installed ({e}); "
                           "pip install faster-whisper") from e

    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    terms = [str(t).strip() for t in (vocabulary or []) if str(t).strip()][:40]
    lang = (str(language or "").strip().lower() or None)
    prompt = _openai_prompt(language, terms)
    segments_iter, info = model.transcribe(
        audio_path,
        language=lang[:2] if lang else None,
        word_timestamps=True,
        initial_prompt=prompt,
        vad_filter=False,   # VAD drops leading silence and SHIFTS the clock
    )
    segments, words = [], []
    for s in segments_iter:
        segments.append({"start": float(s.start), "end": float(s.end),
                         "text": (s.text or "").strip()})
        for w in (getattr(s, "words", None) or []):
            words.append({"word": str(w.word), "start": float(w.start),
                          "end": float(w.end)})
    text = " ".join(s["text"] for s in segments).strip()
    return {
        "text": text,
        "duration": float(getattr(info, "duration", 0.0) or
                          (segments[-1]["end"] if segments else 0.0)),
        "language": getattr(info, "language", None),
        "segments": segments,
        "words": words,
        "provider": f"faster-whisper:{model_size}",
    }


@register("whisperx")
def _whisperx(audio_path: str, *, language=None, vocabulary=None,
              model_size: str = "large-v3", device: str = "cpu",
              compute_type: str = "int8", **_) -> dict:
    """faster-whisper + wav2vec2 FORCED ALIGNMENT.

    The strongest word-timing candidate, and the one most likely to move F1:
    Whisper's native word times are decoder attention estimates, whereas
    whisperx re-aligns each word against the acoustics with a phoneme model.
    That is a different quality class at exactly the place willab is
    sensitive — the first word after a slide tap.

    If this wins the timestamp metrics, the two-clocks compensation in
    ``slide_word_split`` (pause-snap, clock offset) is fighting a smaller
    residual than it is today.
    """
    try:
        import whisperx  # type: ignore
    except ImportError as e:
        raise RuntimeError(f"whisperx not installed ({e}); "
                           "pip install whisperx") from e

    audio = whisperx.load_audio(audio_path)
    model = whisperx.load_model(model_size, device, compute_type=compute_type)
    lang = (str(language or "").strip().lower() or None)
    result = model.transcribe(audio, language=lang[:2] if lang else None)
    detected = result.get("language") or lang
    align_model, meta = whisperx.load_align_model(
        language_code=detected, device=device)
    aligned = whisperx.align(result["segments"], align_model, meta, audio,
                             device, return_char_alignments=False)

    segments, words = [], []
    for s in (aligned.get("segments") or []):
        segments.append({"start": float(s.get("start") or 0.0),
                         "end": float(s.get("end") or 0.0),
                         "text": (s.get("text") or "").strip()})
        for w in (s.get("words") or []):
            # An unalignable word (out-of-vocab phonemes) has no start —
            # dropping it is correct: a fabricated time would be bucketed
            # to a slide with false confidence.
            if not isinstance(w.get("start"), (int, float)):
                continue
            words.append({"word": str(w.get("word") or ""),
                          "start": float(w["start"]),
                          "end": float(w.get("end") or w["start"])})
    return {
        "text": " ".join(s["text"] for s in segments).strip(),
        "duration": segments[-1]["end"] if segments else 0.0,
        "language": detected,
        "segments": segments,
        "words": words,
        "provider": f"whisperx:{model_size}",
    }


@register("forced-align-reference")
def _forced_align_reference(audio_path: str, *, reference_text: str = "",
                            language=None, device: str = "cpu", **_) -> dict:
    """NOT an ASR provider — a TIER 2 GROUND TRUTH producer.

    Given audio and the KNOWN human reference text, forced-align them to get
    reference word TIMES. This is what upgrades every timing number in the
    harness from tier 3 (agreement with whisper-1) to tier 2 (accuracy), and
    it is the single highest-value thing to run once the golden set exists —
    without it we can only say a candidate DIFFERS from whisper-1, never
    that it is BETTER.

    Requires whisperx's aligner (wav2vec2) and a reference transcript.
    """
    if not (reference_text or "").strip():
        raise RuntimeError("forced-align-reference needs reference_text")
    try:
        import whisperx  # type: ignore
    except ImportError as e:
        raise RuntimeError(f"whisperx not installed ({e}); "
                           "pip install whisperx") from e

    audio = whisperx.load_audio(audio_path)
    code = (str(language or "en").strip().lower() or "en")[:2]
    align_model, meta = whisperx.load_align_model(language_code=code,
                                                  device=device)
    # One segment spanning the file: the aligner places every word itself.
    duration = float(len(audio)) / 16000.0
    aligned = whisperx.align(
        [{"text": reference_text.strip(), "start": 0.0, "end": duration}],
        align_model, meta, audio, device, return_char_alignments=False)

    words = []
    for s in (aligned.get("segments") or []):
        for w in (s.get("words") or []):
            if not isinstance(w.get("start"), (int, float)):
                continue
            words.append({"word": str(w.get("word") or ""),
                          "start": float(w["start"]),
                          "end": float(w.get("end") or w["start"])})
    return {
        "text": reference_text.strip(),
        "duration": duration,
        "language": code,
        "segments": [],
        "words": words,
        "provider": "forced-align-reference",
    }
