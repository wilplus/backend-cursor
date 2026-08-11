"""Confidence labelling (founder 2026-07-28) — the corpus for the app's core
function: recognising the confident snippet.

TWO PIECES, both pure:

  * ``validate_confidence_label`` — the coach's call on one snippet:
    ``confident`` yes/no, plus ``intensity`` 1-5 for how strongly. Binary
    first because the model's job is a binary recognition and a rater who
    must commit gives a cleaner boundary; the 1-5 is the same scale Jiang &
    Pell (2017) put in front of their listeners, which makes these numbers
    directly comparable to the published anchor AND the human side of the
    voice-confidence validation gate.

  * ``stratified_label_queue`` — WHICH pieces to put in front of the coach.
    Samples ACROSS the confidence spectrum (some the composite reads as
    confident, some middling, some doubtful) rather than only the ones it
    already likes. A corpus drawn only from machine-confident pieces teaches
    the model to agree with itself: it never sees the boundary it is supposed
    to learn, and every later "agreement" number is circular. The bands are
    used to SELECT and are then discarded — never returned, never shown.

BLIND COACH. The queue carries the moment and nothing else: no band, no
score, no machine read of any kind. The composite decides who gets asked;
the coach decides the answer.

AC-9. ``intensity`` is a number and is coach->machine only. Nothing in this
module is ever serialized toward a student.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

SOURCES = ("coach", "game", "peer")

# Band edges on the voice-confidence spectrum ([-1, 1], 0 = the neutral dead
# zone). Deliberately coarse — these only decide who gets ASKED, so precision
# buys nothing and false precision would invite reading them as truth.
_CONFIDENT_MIN = 0.35
_DOUBTFUL_MAX = -0.35

# Per-band target when the caller doesn't say. Small on purpose: review
# attention is the scarce resource, and a balanced 15 beats a lopsided 60.
DEFAULT_PER_BAND = 5


def validate_confidence_label(payload: Any) -> tuple[Optional[dict], Optional[str]]:
    """Validate one confidence label → ``(row, None)`` or ``(None, error)``.

    Body: ``{confident: bool, intensity?: 1..5, note?: str}``. ``confident``
    is required and must be a real boolean — a string "true" is rejected
    rather than coerced, because a rating corpus that quietly accepted
    truthy junk would be worse than one that refused it. ``intensity`` is
    optional (a coach may call it without grading it) but must be 1-5 when
    present. Pure."""
    if not isinstance(payload, dict):
        return None, "body: must be an object"

    confident = payload.get("confident")
    if not isinstance(confident, bool):
        return None, "confident: required, must be true or false"

    intensity = payload.get("intensity")
    if intensity is not None:
        if isinstance(intensity, bool) or not isinstance(intensity, int):
            return None, "intensity: must be an integer 1-5 (or omitted)"
        if not (1 <= intensity <= 5):
            return None, "intensity: must be between 1 and 5"

    note = payload.get("note")
    if note is not None and not isinstance(note, str):
        return None, "note: must be a string"

    source = (payload.get("source") or "coach")
    if source not in SOURCES:
        return None, f"source: must be one of {', '.join(SOURCES)}"

    return {
        "confident": confident,
        "intensity": intensity,
        "note": (note.strip()[:1000] or None) if isinstance(note, str) else None,
        "source": source,
    }, None


def _confidence_of(snippet: Any) -> Optional[float]:
    """The stored voice-confidence score for a piece, or None when unstamped
    (older takes, or too few measurable cues). Pure."""
    if not isinstance(snippet, dict):
        return None
    metrics = snippet.get("metrics")
    if not isinstance(metrics, dict):
        return None
    read = metrics.get("voice_confidence")
    if not isinstance(read, dict):
        return None
    v = read.get("score")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return None


def band_of(score: Any) -> str:
    """'confident' | 'neutral' | 'doubtful' | 'unscored'. Internal to
    selection — never returned to a labeller. Pure."""
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return "unscored"
    v = float(score)
    if v >= _CONFIDENT_MIN:
        return "confident"
    if v <= _DOUBTFUL_MAX:
        return "doubtful"
    return "neutral"


def stratified_label_queue(snippets: Any, *,
                           per_band: int = DEFAULT_PER_BAND,
                           seed: str = "") -> list:
    """Pick a spectrum-balanced set of pieces for the coach to label.

    Returns the chosen snippet dicts in a DETERMINISTIC but band-shuffled
    order: deterministic so re-opening a session shows the same queue (and a
    re-import is replayable), band-shuffled so the coach can't infer the band
    from position — an ordering tell would anchor the labels exactly like a
    visible score.

    Pieces with no confidence score ('unscored') still participate: they are
    the honest unknowns, and excluding them would bias the corpus toward
    pieces the composite happened to measure. Pure."""
    rows = [s for s in (snippets or []) if isinstance(s, dict) and s.get("id")]
    if not rows:
        return []

    by_band: dict = {}
    for s in rows:
        by_band.setdefault(band_of(_confidence_of(s)), []).append(s)

    def _key(s: dict) -> str:
        return hashlib.sha1(
            f"{seed}:{s.get('id')}".encode("utf-8")).hexdigest()

    picked: list = []
    for band in ("confident", "neutral", "doubtful", "unscored"):
        bucket = sorted(by_band.get(band, []), key=_key)
        picked.extend(bucket[:max(0, per_band)])

    # Final shuffle across bands — deterministic, but band-blind to the eye.
    picked.sort(key=_key)
    return picked


def queue_payload(snippets: Any) -> list:
    """The labelling queue as the coach sees it: the moment, and nothing that
    could hint at an answer.

    Explicitly an allowlist — the snippet row carries metrics with
    voice_confidence, acoustic_read and the tone word, any of which would
    anchor the label if it leaked into this payload (BLIND COACH). Pure."""
    out: list = []
    for s in (snippets or []):
        if not isinstance(s, dict) or not s.get("id"):
            continue
        out.append({
            "snippet_id": s.get("id"),
            "transcript": (s.get("transcript")
                           or s.get("transcript_excerpt") or ""),
            "audio_ref": (s.get("audio_segment_path") or s.get("audio_ref")
                          or s.get("storage_path")),
            "start_offset_ms": s.get("start_offset_ms"),
            "duration_ms": s.get("duration_ms"),
            "session_id": s.get("session_id"),
        })
    return out


def corpus_summary(label_rows: Any) -> dict:
    """Class balance for a confidence-corpus pull — so a training run can see
    whether the data is usable before it trains on it. A corpus that is 90%
    'confident: true' will produce a model that says yes to everything, and
    this is where that shows up."""
    rows = [r for r in (label_rows or []) if isinstance(r, dict)]
    # TERNARY FIRST (the shipped instrument: value in yes/no/neutral,
    # unrateable separate), legacy `confident` as the fallback for rows
    # written before the migration. Counting only the binary here was the
    # BE sibling of the FE's pickLabel bug: a stored neutral vanished
    # from every count and the balance read as cleaner than the corpus.
    def _answer(r):
        v = r.get("value")
        if v in ("yes", "no", "neutral"):
            return v
        if r.get("confident") is True:
            return "yes"
        if r.get("confident") is False:
            return "no"
        return None

    yes = sum(1 for r in rows if _answer(r) == "yes")
    no = sum(1 for r in rows if _answer(r) == "no")
    neutral = sum(1 for r in rows if _answer(r) == "neutral")
    unrateable = sum(1 for r in rows if r.get("unrateable") is True)
    answered = yes + no + neutral
    by_intensity: dict = {}
    for r in rows:
        v = r.get("intensity")
        if isinstance(v, int) and not isinstance(v, bool):
            by_intensity[v] = by_intensity.get(v, 0) + 1
    rated = sum(by_intensity.values())
    return {
        "total": len(rows),
        "confident_yes": yes,
        "confident_no": no,
        "neutral": neutral,
        # Two abstentions are not two labels — unrateable rows carry no
        # answer and stay out of `balance` (same rule as aggregate()).
        "unrateable": unrateable,
        "balance": (round(yes / answered, 3) if answered else None),
        "by_intensity": by_intensity,
        "mean_intensity": (
            round(sum(k * n for k, n in by_intensity.items()) / rated, 2)
            if rated else None
        ),
        "raters": len({r.get("rater_id") for r in rows if r.get("rater_id")}),
    }
