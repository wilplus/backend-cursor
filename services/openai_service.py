"""Whisper transcription — the provider call behind F1 piece (a).

Transcription-only since the audit's Q-A4 (Phase 3, 2026-09-14). This module
used to be a 1,579-line hub of fourteen chat prompts as well; every one of
those methods had zero production callers and zero tests, so they were
deleted rather than moved (their prompt-registry entries went with them).
Chat completions go through ``services.llm.chat_complete``; the OpenAI client
itself is built in one place, ``services.llm_client``.

What remains: ``transcribe_audio`` (untouched — its source is hashed by the
prompt registry as ``legacy_openai.whisper_priming``), the shared client, and
``_chat_model`` for the one caller that still reads the runtime model config
directly (``services/ceo_work_items.py``, a grandfathered direct call site).
"""
from config import Config
import os
import mimetypes
import time
import sentry_sdk
from services.db import db
from services.llm_client import build_openai_client

config = Config()


class OpenAIService:
    def __init__(self):
        # Strict client-side timeout (async-queue work 2026-08-03): the SDK
        # default is 600s, so ONE hung OpenAI call used to park a gunicorn
        # worker — half the backend's capacity at --workers 2 — for 10 min.
        # Whisper calls override this with the larger transcribe timeout
        # (see transcribe_audio). None without a key: the documented
        # "provider unavailable" signal every caller handles.
        self.client = build_openai_client(
            config.OPENAI_API_KEY,
            timeout=config.OPENAI_TIMEOUT_SECONDS,
            max_retries=config.OPENAI_MAX_RETRIES,
        )
        self._model_cache: dict[str, tuple[float, str]] = {}

    def _chat_model(self, purpose: str = "default") -> str:
        """Resolve model from runtime_config, then env, then hard default."""
        base_default = "gpt-4o-mini"
        env_fallback = (
            config.OPENAI_COPILOT_MODEL
            if purpose == "copilot"
            else config.OPENAI_CHAT_MODEL
        ) or config.OPENAI_COPILOT_MODEL or config.OPENAI_CHAT_MODEL
        now = time.time()
        cached = self._model_cache.get(purpose)
        if cached and (now - cached[0]) < 60:
            return cached[1]
        key = "openai_copilot_model" if purpose == "copilot" else "openai_chat_model"
        # R-13 (Job 1 review 2026-09-22). SAME CLASS AS LEGACY-1, WITHOUT THE
        # LEARNING LANE. These two keys live in the same service-role-writable,
        # RLS-less `runtime_config` table as the surface keys, and a value in
        # either was served to every chat and copilot call with no flag, no
        # evaluation and no provenance. This repository contains no writer for
        # them, which is precisely why nothing would have noticed a row.
        #
        # The gate is shared with the promoted surfaces so there is one answer
        # to "can a database row change which model runs", not two.
        from services.runtime_model_gate import resolve_gated_model

        promoted = resolve_gated_model(key, read=db.get_runtime_config)
        model = (promoted or env_fallback or base_default).strip()
        self._model_cache[purpose] = (now, model)
        return model
    
    def transcribe_audio(self, audio_file, filename: str = "audio.webm", content_type: str | None = None, vocabulary: list | None = None, language: str | None = None,
                         usage_surface: str = "whisper_take", usage_user_id: str | None = None,
                         usage_session_id: str | None = None, usage_arc_id: str | None = None):
        """
        Transcribe audio using Whisper-1.
        Returns {text, duration, segments} — segments is the verbose_json
        per-segment list [{start, end, text}] (ADDITIVE; existing callers
        reading text/duration are unaffected). The willab Lab handler uses
        segments to slice per-snippet transcripts by timestamp.

        content_type: optional MIME for the multipart file tuple; defaults from filename (not hard-coded webm).
        vocabulary: optional domain terms (session_context.domain_vocabulary)
                    appended to the Whisper prompt to prime recognition of
                    domain-specific words (willab contract §3.3 — "Whisper
                    primed with domain_vocabulary"). None → the default
                    disfluent-only prompt.
        language:   optional ISO-639-1 code ('pl', 'de', …). None → Whisper
                    auto-detects, which is the live path's behaviour and is
                    unchanged.

        LANGUAGE + THE PROMPT (fix 2026-07-29, first non-English import):
        the disfluency prompt below is ENGLISH, and Whisper follows its
        prompt's language — an English prompt on Polish audio biases
        auto-detection toward English and can yield an empty or garbage
        transcript. So the prompt is only applied when the audio is English
        or the language is unknown-but-assumed-English; for any other
        declared language we pass the code and DROP the English prompt
        (keeping only the domain vocabulary, which is language-neutral).
        Losing filler-word priming on a non-English take is a far smaller
        cost than losing the transcript.

        usage_*:    cost-ledger attribution for the llm_usage table
                    (token-pricing Phase 0). All optional with safe defaults —
                    existing callers are unaffected. Whisper is ~52% of a
                    take's cost and the only line that scales without limit
                    with duration, so this is the most important row in the
                    ledger; pass usage_session_id wherever it is known.
        """
        # Dev mode mock response (COMMENTED OUT - using real OpenAI)
        # if not config.is_production:
        #     # Mock response in dev
        #     return {
        #         "text": "This is a mock transcription for development purposes. The user spoke about their presentation and how they felt nervous but prepared.",
        #         "duration": 45.0
        #     }
        
        if not self.client:
            raise Exception("OpenAI client not initialized")

        import logging
        logger = logging.getLogger(__name__)
        audio_data = b""
        try:
            audio_file.seek(0)
            audio_data = audio_file.read()
            audio_file.seek(0)
            logger.info("transcribe_audio: filename=%s size=%d bytes", filename, len(audio_data))

            ext = os.path.splitext(filename or "")[1].lower()
            ct = (content_type or "").strip() or None
            if not ct:
                ct = mimetypes.guess_type(filename or "")[0]
            if not ct:
                ct = {
                    ".webm": "audio/webm",
                    ".wav": "audio/wav",
                    ".mp3": "audio/mpeg",
                    ".m4a": "audio/mp4",
                    ".mp4": "video/mp4",
                    ".mpeg": "audio/mpeg",
                    ".mpga": "audio/mpeg",
                    ".ogg": "audio/ogg",
                    ".opus": "audio/opus",
                }.get(ext, "application/octet-stream")

            # Transcribe
            # Disfluent prompt conditions Whisper to preserve filler words instead of cleaning them.
            prompt = "Umm, let me think like, hmm... Okay, so, uh, yeah. I mean, you know, it's like, um, well..."
            if vocabulary:
                # Append domain terms so Whisper recognises domain-specific
                # words (willab §3.3 priming). Cap so the prompt stays small.
                terms = [str(t).strip() for t in vocabulary if str(t).strip()][:40]
                if terms:
                    prompt = prompt + " " + ", ".join(terms) + "."
            _lang = (language or "").strip().lower() or None
            _create_kwargs = dict(
                model="whisper-1",
                file=(filename or "audio.bin", audio_data, ct),
                response_format="verbose_json",
            )
            # See the LANGUAGE + THE PROMPT note in the docstring: an English
            # prompt on non-English audio is worse than no prompt at all.
            if _lang and not _lang.startswith("en"):
                _create_kwargs["language"] = _lang
                _vocab_only = ", ".join(
                    [str(t).strip() for t in (vocabulary or [])
                     if str(t).strip()][:40])
                if _vocab_only:
                    _create_kwargs["prompt"] = _vocab_only + "."
                logger.info(
                    "transcribe_audio: language=%s — English disfluency "
                    "prompt dropped", _lang,
                )
            else:
                if _lang:
                    _create_kwargs["language"] = _lang
                _create_kwargs["prompt"] = prompt
            # Whisper on a long take legitimately runs minutes — give
            # transcription its own (larger, still bounded) timeout instead
            # of the client-wide LLM one.
            _tclient = self.client.with_options(
                timeout=config.OPENAI_TRANSCRIBE_TIMEOUT_SECONDS,
            )
            try:
                # Ask for BOTH granularities: segments (existing per-snippet
                # transcript slicing) AND words (willab #6 — precise per-slide
                # transcript sync; a word's slide is the one on screen at its
                # timestamp). Same single call, just a richer response.
                transcript_response = _tclient.audio.transcriptions.create(
                    timestamp_granularities=["segment", "word"], **_create_kwargs,
                )
            except Exception as _gran_err:
                # SDK too old / API rejects the param → fall back to the prior
                # segment-only call so transcription is never worse than before
                # (#6 just loses word timestamps; the readout/transcript stand).
                logger.warning(
                    "transcribe_audio: word granularity unavailable, "
                    "falling back to segments-only: %s", _gran_err,
                )
                transcript_response = _tclient.audio.transcriptions.create(
                    **_create_kwargs,
                )

            # Extract duration + per-segment timestamps.
            duration = 0.0
            segments: list = []
            if hasattr(transcript_response, 'segments') and transcript_response.segments:
                duration = transcript_response.segments[-1].end
                for seg in transcript_response.segments:
                    segments.append({
                        "start": float(getattr(seg, "start", 0.0) or 0.0),
                        "end": float(getattr(seg, "end", 0.0) or 0.0),
                        "text": (getattr(seg, "text", "") or "").strip(),
                    })

            # Word-level timestamps (#6) — [{word, start, end}] in SECONDS,
            # absolute to the recording. ADDITIVE: existing callers ignore it.
            words: list = []
            if hasattr(transcript_response, "words") and transcript_response.words:
                for w in transcript_response.words:
                    ws = getattr(w, "word", None)
                    if ws is None and isinstance(w, dict):
                        ws = w.get("word")
                    st = getattr(w, "start", None)
                    if st is None and isinstance(w, dict):
                        st = w.get("start")
                    en = getattr(w, "end", None)
                    if en is None and isinstance(w, dict):
                        en = w.get("end")
                    if ws is None or not isinstance(st, (int, float)):
                        continue
                    words.append({
                        "word": str(ws),
                        "start": float(st),
                        "end": float(en) if isinstance(en, (int, float)) else float(st),
                    })

            # Whisper verbose_json includes `language` (ISO 639-1). Surface it so
            # callers can persist transcription_language on the recording row for
            # downstream multilingual filler detection (utils/filler_words.py).
            detected_language = getattr(transcript_response, "language", None)

            # Cost ledger (token-pricing Phase 0). Whisper bills on AUDIO TIME,
            # so `duration` is the billable quantity. Best-effort: llm_usage
            # swallows its own failures and never touches the transcript.
            try:
                from services.llm_usage import record_audio_usage
                record_audio_usage(
                    surface=usage_surface,
                    seconds=duration,
                    user_id=usage_user_id,
                    session_id=usage_session_id,
                    arc_id=usage_arc_id,
                )
            except Exception:
                pass

            return {
                "text": transcript_response.text,
                "duration": duration,
                "language": detected_language,
                "segments": segments,
                "words": words,
            }
        except Exception as e:
            logger.error(
                "transcribe_audio: FAILED filename=%s size=%d error=%r",
                filename, len(audio_data), e, exc_info=True,
            )
            sentry_sdk.capture_exception(e)
            raise Exception(f"Transcription failed: {str(e)}")
    

# Singleton instance
openai_service = OpenAIService()
