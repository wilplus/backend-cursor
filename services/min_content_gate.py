"""willab beta — Lab min-content gate (design §4 / contract §3.3 / §5.5).

The salvaged remnant of the deleted onboarding completion gate. The
old gate required ≥1 charisma + ≥1 stress + ≥60s (a CONTRAST gate);
willab drops the contrast requirement entirely and keeps only a
**content-validity** check: a recording must have enough speech to be
worth processing + sending to a coach.

Rule (invariant §5.5 — enforced BEFORE the pipeline runs, never trusted
to FE): a recording passes iff
  (a) duration ≥ MIN_DURATION_SEC (60s), AND
  (b) it actually contains speech (≥ MIN_VOICED_SEC of voiced audio).

A failing recording → re-record prompt; nothing sendable is persisted.

This module is import-safe without numpy (the heavy bits lazy-import
audio_metrics inside the functions), so the route layer can import it
freely; only *calling* it needs the audio stack.
"""
from __future__ import annotations

from typing import Any, Optional


# Minimum duration RETIRED (founder 2026-07-15): there is NO minimum
# recording time anywhere — main takes and seconds-long snippet re-reads
# alike are accepted. Kept at 0.0 (not deleted) so the thresholds echo the
# FE reads stays shape-stable; the too_short reason can no longer fire.
MIN_DURATION_SEC = 0.0

# Has-speech floor: at least this many seconds of voiced audio, so a
# near-silent / dead-air recording fails "no_speech" — this one protects
# the pipeline (nothing to transcribe/analyze), not a UX minimum. A very
# short but VOICED clip passes: voiced_sec is capped by duration, so the
# floor scales down to the clip length for sub-3s recordings.
MIN_VOICED_SEC = 3.0


def evaluate_min_content(sig: Any) -> dict:
    """Evaluate the gate on an already-decoded PCM array.

    Returns::

        {
          "ok":           bool,
          "reason":       "too_short" | "no_speech" | "no_audio" | None,
          "duration_sec": float,
          "voiced_sec":   float,
          "thresholds":   {"min_duration_sec": 60.0, "min_voiced_sec": 3.0}
        }

    ``reason`` is None iff ``ok`` is True. The FE renders a re-record
    prompt keyed on ``reason`` (too_short vs no_speech read differently
    to the user).
    """
    from services.audio_metrics import (
        SAMPLE_RATE, FRAME_MS, SILENCE_DB_THRESHOLD, _frame_rms_db,
    )
    import numpy as np

    thresholds = {
        "min_duration_sec": MIN_DURATION_SEC,
        "min_voiced_sec": MIN_VOICED_SEC,
    }

    if sig is None or len(sig) == 0:
        return {
            "ok": False, "reason": "no_audio",
            "duration_sec": 0.0, "voiced_sec": 0.0,
            "thresholds": thresholds,
        }

    duration_sec = round(len(sig) / float(SAMPLE_RATE), 1)

    dbs = _frame_rms_db(sig)
    voiced_frames = int(np.sum(dbs >= SILENCE_DB_THRESHOLD)) if len(dbs) else 0
    voiced_sec = round(voiced_frames * (FRAME_MS / 1000.0), 1)

    # No duration minimum (founder 2026-07-15) — too_short retired. The
    # has-speech floor scales DOWN for short clips (a 2s fully-voiced
    # re-read passes; 2s of silence still fails): require voiced audio of
    # at least min(3s, half the clip), never less than one frame.
    _floor = min(MIN_VOICED_SEC, max(0.1, duration_sec * 0.5))
    if voiced_sec < _floor:
        reason: Optional[str] = "no_speech"
    else:
        reason = None

    return {
        "ok": reason is None,
        "reason": reason,
        "duration_sec": duration_sec,
        "voiced_sec": voiced_sec,
        "thresholds": thresholds,
    }


def evaluate_min_content_bytes(audio_bytes: bytes) -> dict:
    """Decode container bytes → PCM → evaluate. Convenience wrapper for
    the Lab upload handler (which has raw upload bytes).

    Decode failure returns a failing gate with reason ``no_audio`` so a
    corrupt/unreadable upload is rejected exactly like silence — never
    enters the pipeline.
    """
    from services.audio_metrics import decode_audio_to_pcm

    if not audio_bytes:
        return {
            "ok": False, "reason": "no_audio",
            "duration_sec": 0.0, "voiced_sec": 0.0,
            "thresholds": {
                "min_duration_sec": MIN_DURATION_SEC,
                "min_voiced_sec": MIN_VOICED_SEC,
            },
        }
    sig = decode_audio_to_pcm(audio_bytes)
    if sig is None:
        return {
            "ok": False, "reason": "no_audio",
            "duration_sec": 0.0, "voiced_sec": 0.0,
            "thresholds": {
                "min_duration_sec": MIN_DURATION_SEC,
                "min_voiced_sec": MIN_VOICED_SEC,
            },
        }
    return evaluate_min_content(sig)
