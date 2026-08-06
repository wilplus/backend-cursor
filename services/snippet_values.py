"""Read a snippet's six acoustic measures off whatever actually holds them.

PURE: no DB, no clock, no registry lookup. Lives apart from session_metrics so
`services.db` can use it too — session_metrics imports db, so the resolver
cannot live there without a cycle.

WHY THIS MODULE EXISTS AT ALL — measured 2026-08-06, not assumed.

`charisma_snippets` has six denormalized metric columns (wpm, fillers,
pause_ms, dynamic_db, pitch_center, energy) and a `metrics` JSONB blob. The
columns look canonical and are in fact DEAD: the only writer,
`db.update_snippet_metrics`, is reached solely from
`snippet_extraction.recompute_snippet_metrics_for_window`, which has no callers
repo-wide. `process_lab_recording` inserts the blob and nothing else.

So every caller reading `snippet["wpm"]` has been reading NULL — the admin
snippet lists, the coach acoustic disclosure, the labelled-metric baselines,
the session roll-up and, through it, the KPI. The drift layer surfaced this
first because it was the only consumer that recorded its own refusals.

PRECEDENCE: column → blob → transcript derivation. Stored measurements win;
derivation is a floor, not a preference.

THE BLOB IS NOT THE COLUMN SET. Two keys differ in NAME (pitch_center_st,
energy_ratio) and one measure — fillers — is not in the blob at all, because
audio_metrics computes no filler field. For fillers the transcript IS the
measurement.

UNITS, and the trap to not walk into. `pitch_center` carries SEMITONES
(audio_metrics._pitch_center_st_from_series), while the registry declares the
dimension's unit as "Hz". The data is self-consistent — every consumer sees
semitones — so comparisons are valid, but anything RENDERING this must not
label it Hz. True Hz lives in the blob as `f0_mean`; see HZ_DISPLAY_KEY.

AC-9. Nothing here decides or characterizes; it returns figures. The user-lane
panel already treats raw acoustic figures as reference data (SpeechDataPanel:
"reference DATA, never a verdict"), and this changes what is READ, never what
is said about it.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# The blob key holding a genuine Hz pitch, for surfaces that render "Hz".
# NOT the same quantity as the `pitch_center` dimension (semitones).
HZ_DISPLAY_KEY = "f0_mean"


def _derive_wpm(transcript: str, seconds: Optional[float]) -> Optional[float]:
    """Words per minute from the transcript. NOT an approximation of what the
    pipeline would have stored — `audio_metrics._analyze_pcm` computes wpm as
    `len(transcript.split()) / (duration_sec / 60)` from the same transcript,
    so this reproduces that number exactly."""
    if not transcript or not seconds or seconds <= 0:
        return None
    from utils.metrics import compute_wpm
    return float(compute_wpm(transcript, float(seconds)))


def _derive_fillers(transcript: str, seconds: Optional[float]) -> Optional[float]:
    """Filler COUNT, not a rate — the registry aggregates fillers per_minute
    and rate_windows divides by minutes itself. The ONLY source: nothing in the
    acoustic pipeline computes fillers."""
    if not transcript:
        return None
    from utils.metrics import count_fillers
    return float(int(count_fillers(transcript).get("total") or 0))


# dimension_id -> (column, JSONB `metrics` key, transcript derivation)
#
# ONLY the plumbing lives here. Window class, tier, minimum length, denominator
# and aggregation all come from services/dimension_registry — Appendix F.4 is
# the source, and retyping any of it here is how two consumers start
# disagreeing about the same dimension.
SNIPPET_FIELDS: dict[str, tuple[str, Optional[str], Optional[Callable]]] = {
    "wpm":          ("wpm",          "wpm",             _derive_wpm),
    "fillers":      ("fillers",      None,              _derive_fillers),
    "pause_ms":     ("pause_ms",     "pause_ms",        None),
    "dynamic_db":   ("dynamic_db",   "dynamic_db",      None),
    "pitch_center": ("pitch_center", "pitch_center_st", None),
    "energy":       ("energy",       "energy_ratio",    None),
}


def _context(snippet: dict) -> tuple[dict, str, Optional[float]]:
    blob = snippet.get("metrics")
    metrics = blob if isinstance(blob, dict) else {}
    transcript = (snippet.get("transcript")
                  or snippet.get("transcription_text") or "").strip()
    duration_ms = snippet.get("duration_ms")
    seconds = (float(duration_ms) / 1000.0
               if isinstance(duration_ms, (int, float)) else None)
    return metrics, transcript, seconds


def resolve(snippet: dict, dimension_id: str) -> Optional[float]:
    """One measure off one snippet row. None when no source holds it.

    None is a real answer and must stay distinct from 0.0: `compute_wpm`
    returns 0.0 for an empty string and `count_fillers` returns 0, and writing
    either for a snippet we have no transcript for would fabricate a
    measurement (F.5 — missing stays missing). The mirror case is deliberate
    too: clean speech genuinely scoring 0 fillers IS a measurement and is
    returned as 0.0.
    """
    plumbing = SNIPPET_FIELDS.get(dimension_id)
    if not plumbing or not isinstance(snippet, dict):
        return None
    column, blob_key, derive = plumbing
    metrics, transcript, seconds = _context(snippet)

    value = snippet.get(column)
    if value is None and blob_key:
        value = metrics.get(blob_key)
    # `bool` subclasses `int`; a stray True must not become 1.0.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if derive is None:
        return None
    try:
        return derive(transcript, seconds)
    except Exception as e:
        logger.warning("snippet_values: %s derivation failed sid=%s: %s",
                       dimension_id, snippet.get("id"), e)
        return None


def resolve_all(snippet: dict) -> dict[str, Optional[float]]:
    """All six, keyed by dimension_id. Values may be None."""
    return {d: resolve(snippet, d) for d in SNIPPET_FIELDS}


def display_hz(snippet: dict) -> Optional[float]:
    """Mean f0 in TRUE Hz, for surfaces that render a "Hz" label.

    Deliberately not `resolve(snippet, "pitch_center")` — that one is
    semitones, and rendering it under a Hz label is the specific mistake this
    function exists to make hard.
    """
    metrics, _, _ = _context(snippet)
    value = metrics.get(HZ_DISPLAY_KEY)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None
