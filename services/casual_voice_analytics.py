"""Phase Stress-Contrast (BE-3) — async DSP extraction for casual chat audio.

Mirrors ``services.conversation_summary.update_summary_async``'s
fire-and-forget daemon pattern. NEVER blocks the LLM response in
``POST /v2/chat/query``.

The flow:
  1. ``/v2/chat/query`` receives a multipart request with both
     ``question`` (Web Speech transcript from the frontend) and an
     ``audio_file`` blob (the raw mic capture).
  2. Path A: the question goes to the LLM via answer_question and the
     HTTP response returns as soon as the answer is ready.
  3. Path B (this module): ``analyze_casual_audio_async`` spawns a
     daemon thread that decodes the blob, runs the DSP suite, and
     persists the metrics row to ``casual_voice_benchmarks``. The
     user's LLM reply is never gated on any of this.

Failure semantics
-----------------
Every failure mode (decode error, DB write error, R2 upload error
when the retain flag is on) is logged and swallowed. A failed row
just means one fewer sample for the stress contrast — non-fatal.
The daemon NEVER raises out to the request thread.
"""
from __future__ import annotations

import logging
import os
import threading
import uuid as _uuid
from typing import Optional

from services.db import db


logger = logging.getLogger(__name__)


def _retain_audio_enabled() -> bool:
    """Feature flag ``RETAIN_CASUAL_AUDIO`` — default false.

    When true, the daemon uploads the blob to
    ``casual_voice/<user_id>/<row_id>.webm`` in the audio bucket
    so QA can replay it against a suspicious metrics reading.
    Read each call so a hot env-var flip takes effect on the next
    capture without a restart.
    """
    val = (os.environ.get("RETAIN_CASUAL_AUDIO") or "").strip().lower()
    return val in ("1", "true", "yes", "on")


def analyze_casual_audio_async(
    *,
    user_id: str,
    session_id: Optional[str],
    audio_bytes: bytes,
    transcript: str,
    duration_sec: float,
    transcript_source: str = "web_speech",
) -> None:
    """Fire-and-forget. Spawns a daemon thread that:

      1. Decodes + analyzes ``audio_bytes`` via
         ``services.audio_metrics.analyze_audio``.
      2. Optionally uploads the blob to R2 (RETAIN_CASUAL_AUDIO).
      3. Persists the metrics row to ``casual_voice_benchmarks``.

    Args
    ----
    user_id : str
        Authenticated owner from ``request.user_id``.
    session_id : str | None
        v2_sessions row id IFF this capture happens to coincide with
        an active coaching session. None for pure Lounge chat (the
        common case).
    audio_bytes : bytes
        Raw blob from the frontend MediaRecorder; expected
        webm/opus but the ffmpeg-backed decoder is forgiving.
    transcript : str
        The Web Speech API text the frontend sent up as the user's
        question. Passed through to ``analyze_audio`` so WPM is
        computed against the same text the user actually saw on
        screen.
    duration_sec : float
        Hint from the frontend (MediaRecorder duration). Used by
        ``analyze_audio`` for WPM normalization; when 0/missing,
        the analyzer falls back to deriving from the decoded PCM
        length.
    transcript_source : str
        ``"web_speech"`` (default) — column CHECK constraint
        accepts only the documented values.

    Returns
    -------
    None. The thread is a daemon; callers do not join. Errors are
    logged, never raised.
    """
    # Capture args by value into the closure so the caller can drop
    # references (e.g. the request handler returning) without
    # affecting this thread.
    args = {
        "user_id": user_id,
        "session_id": session_id,
        "audio_bytes": audio_bytes,
        "transcript": transcript or "",
        "duration_sec": float(duration_sec or 0.0),
        "transcript_source": transcript_source or "web_speech",
    }

    def _runner() -> None:
        try:
            from services.audio_metrics import analyze_audio
            metrics = analyze_audio(
                audio_bytes=args["audio_bytes"],
                transcript=args["transcript"],
                duration_sec=args["duration_sec"],
            )
            if not metrics:
                # Decode or analysis returned None (ffmpeg miss, audio
                # too short, etc.). Drop silently — the stress
                # contrast just gets one fewer sample.
                logger.warning(
                    "casual_voice.analyze_empty user=%s "
                    "bytes=%d dur=%.2f",
                    args["user_id"],
                    len(args["audio_bytes"]) if args["audio_bytes"] else 0,
                    args["duration_sec"],
                )
                return

            storage_path: Optional[str] = None
            if _retain_audio_enabled():
                try:
                    from services.audio_storage import put_audio_bytes
                    # Path-prefixed by user so we can prune per-user
                    # on data-deletion requests; row_id is freshly
                    # generated so we never collide.
                    row_id = str(_uuid.uuid4())
                    storage_path = (
                        f"casual_voice/{args['user_id']}/{row_id}.webm"
                    )
                    put_audio_bytes(
                        storage_path,
                        args["audio_bytes"],
                        content_type="audio/webm",
                    )
                except Exception as up_err:
                    logger.warning(
                        "casual_voice.retain_upload_failed user=%s err=%s "
                        "— proceeding metrics-only",
                        args["user_id"], up_err,
                    )
                    storage_path = None

            audio_duration_ms: Optional[int] = None
            if args["duration_sec"] and args["duration_sec"] > 0:
                audio_duration_ms = int(round(args["duration_sec"] * 1000))

            row = db.insert_casual_voice_benchmark(
                user_id=args["user_id"],
                session_id=args["session_id"],
                metrics=metrics,
                transcript_source=args["transcript_source"],
                audio_duration_ms=audio_duration_ms,
                audio_storage_path=storage_path,
            )
            if row is None:
                logger.warning(
                    "casual_voice.persist_failed user=%s "
                    "(table missing or write failed — metrics lost "
                    "but request unaffected)",
                    args["user_id"],
                )
            else:
                logger.info(
                    "casual_voice.persisted user=%s row=%s wpm=%s "
                    "pitch_st=%s",
                    args["user_id"],
                    row.get("id"),
                    metrics.get("wpm"),
                    metrics.get("pitch_center_st"),
                )
        except Exception as e:
            logger.warning(
                "casual_voice.runner_crashed user=%s err=%s",
                args["user_id"], e,
            )

    threading.Thread(
        target=_runner,
        name=f"casual-voice-{user_id[:8]}",
        daemon=True,
    ).start()
