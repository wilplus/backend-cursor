"""Two acoustic cues, measured silently first (founder 2026-09-30, E10;
build plan ML-14). The shadow stage of services/verbal_cues.py, for the
voice rather than the words:

  * ``low_volume`` — the voice barely rises above the room: the clip's own
    noise meter (services/audio_metrics.py) puts the speaking frames under
    LOW_VOLUME_MAX_SEPARATION_DB above the quietest frames. Relative to the
    recording itself, because microphones differ;
  * ``flat_pitch`` — the voice stays on one note: the pitch track's
    standard deviation is under FLAT_PITCH_MAX_CV of its mean, on at least
    FLAT_PITCH_MIN_FRAMES confident frames. A ratio, so a low voice and a
    high voice read alike.

Both are logged once per Take into the same shadow log the verbal cues
use, and route NOTHING: routing reads ``status = 'detected'`` only, and
migration 0406 seeds both as ``shadow``. Promotion is the weekly job's
drafted migration after the founder's go (ML-14), once the verdicts have
been checked against coaches' own judgements. Language-free: the row's
language column says ``any``.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

_log = logging.getLogger(__name__)

ACOUSTIC_CUES_VERSION = "acoustic-cues-v1"
CUES = ("low_volume", "flat_pitch")

LOW_VOLUME_MAX_SEPARATION_DB = 12.0
LOW_VOLUME_MIN_FRAMES = 20
FLAT_PITCH_MAX_CV = 0.06
FLAT_PITCH_MIN_FRAMES = 30


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def measure(metrics: Any) -> Optional[dict]:
    """{cue: {fired, measurements}} from a clip's stored metrics, or None
    when the clip carries neither reading (nothing to log)."""
    if not isinstance(metrics, dict):
        return None
    raw_meter = metrics.get("noise_meter")
    meter: dict = raw_meter if isinstance(raw_meter, dict) else {}
    separation = _number(meter.get("separation_db"))
    f0_mean, f0_sd = _number(metrics.get("f0_mean")), _number(metrics.get("f0_sd"))
    frames = _number(metrics.get("pitch_frame_count")) or 0.0
    out: dict[str, dict] = {}
    if separation is not None:
        out["low_volume"] = {
            "fired": separation < LOW_VOLUME_MAX_SEPARATION_DB,
            "measurements": {"separation_db": separation,
                             "voice_db": _number(meter.get("voice_db")),
                             "background_db": _number(meter.get("background_db")),
                             "max_separation_db": LOW_VOLUME_MAX_SEPARATION_DB},
        }
    if f0_mean and f0_sd is not None and frames >= FLAT_PITCH_MIN_FRAMES:
        cv = round(f0_sd / f0_mean, 4)
        out["flat_pitch"] = {
            "fired": cv < FLAT_PITCH_MAX_CV,
            "measurements": {"f0_mean": f0_mean, "f0_sd": f0_sd, "f0_cv": cv,
                             "pitch_frame_count": int(frames), "max_cv": FLAT_PITCH_MAX_CV},
        }
    return out or None


def take_observations(snippets: list[dict], *, take_session_id: str) -> list[dict]:
    rows: list[dict] = []
    for snippet in snippets or []:
        if not isinstance(snippet, dict) or not snippet.get("id"):
            continue
        verdicts = measure(snippet.get("metrics"))
        if not verdicts:
            continue
        for cue, verdict in verdicts.items():
            rows.append({
                "take_session_id": str(take_session_id),
                "snippet_id": str(snippet["id"]),
                "recording_id": str(snippet.get("recording_id") or "") or None,
                "error_id": cue,
                "detector_version": ACOUSTIC_CUES_VERSION,
                "language": "any",
                "fired": bool(verdict["fired"]),
                "measurements": verdict["measurements"],
            })
    return rows


def record_take(database: Any, take_session_id: str) -> int:
    """Measure one Take's clips and log the verdicts. Same boundary as the
    verbal cues: only with the speaker's "Personalised practice" yes.
    Best-effort by contract (the caller runs it under DegradationLog)."""
    from services.verbal_cues import _practice_permitted
    if not take_session_id or not _practice_permitted(database, take_session_id):
        return 0
    rows = take_observations(database.get_snippets_by_session(str(take_session_id)) or [],
                             take_session_id=str(take_session_id))
    if not rows:
        return 0
    return int(database.record_verbal_cue_shadow(rows) or 0)
