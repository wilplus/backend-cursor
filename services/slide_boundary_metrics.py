"""F1 — how good is the word→slide bucketing, actually? (2026-07-26)

The two-clocks problem: Whisper word times are measured from the AUDIO, slide
tap times from the phone's UI. The recorder warm-up makes the audio clock run
slightly LATER than the UI clock, so the first words after a tap can be bucketed
to the PREVIOUS slide. `services.slide_word_split._snap_boundaries_to_pauses`
compensates by moving each boundary into the nearest real speech pause.

That compensation shipped and is live — but nothing ever measured it. This
module is the measurement.

WHAT THIS CAN AND CANNOT TELL YOU — read this before trusting a number.

There is no ground truth here. Nothing in the transcript, the acoustics or the
deck records which slide was ACTUALLY on screen when a word was spoken; that is
exactly the fact the drift destroys. So these are EXPOSURE and IMPACT measures,
never an accuracy rate:

  * words_at_risk        — words within ±risk_ms of a boundary. How much of the
                           transcript is close enough to a tap that a drift of
                           that size COULD move it. Big number = the mechanism
                           matters here; it does NOT mean anything is wrong.
  * words_reassigned     — words whose slide actually CHANGES when pause-snap is
                           applied. This is the honest impact number: it is what
                           the feature did, not what it should have done.
  * boundaries_snapped / boundaries_no_pause
                         — coverage. A boundary with no qualifying pause nearby
                           (the speaker talked straight through the tap) is one
                           pause-snap CANNOT help, so it bounds how much of the
                           problem this approach can ever reach.

Calling `words_reassigned` an improvement would be assuming the answer. The only
real labels available are COACH CORRECTIONS — when a coach moves text between
slides, a human has said "this was bucketed wrong". Joining these metrics to
those corrections is the follow-up that turns impact into accuracy.

AC-9: internal/coach-side only. Nothing here is ever surfaced to a user — no
score, no verdict, no percentage in any user payload.

Pure and dependency-light: no DB, no I/O, never raises on malformed input.
"""
from __future__ import annotations

from typing import Any, Optional

# Words this close to a boundary are "at risk" — the observed recorder warm-up
# is well inside this, so it is a generous bound on what drift could move.
DEFAULT_RISK_MS = 500


def _words_ms(words: Any) -> list:
    """[(start_ms, token)] for usable words, time-sorted. Whisper word times are
    SECONDS absolute to the recording — the same frame as slide tap times."""
    out = []
    for w in (words or []):
        if not isinstance(w, dict):
            continue
        st = w.get("start")
        if not isinstance(st, (int, float)) or isinstance(st, bool):
            continue
        token = (w.get("word") or "").strip()
        if not token:
            continue
        out.append((int(float(st) * 1000), token))
    out.sort(key=lambda p: p[0])
    return out


def _boundary_times(slide_advances: Any) -> list:
    """Tap times in ms, excluding the recording-start entry (t<=0), which is not
    a boundary anyone can be on the wrong side of."""
    out = []
    for a in (slide_advances or []):
        if not isinstance(a, dict):
            continue
        t = a.get("t_ms")
        if not isinstance(t, (int, float)) or isinstance(t, bool):
            continue
        t = int(t)
        if t > 0:
            out.append(t)
    return sorted(out)


def _assign(words_ms: list, advances: Any, n_slides: int) -> list:
    """Slide index per word, using the SAME rule the real bucketer uses."""
    from services.slide_alignment import slide_index_for_offset
    out = []
    for start_ms, _tok in words_ms:
        si = slide_index_for_offset(start_ms, advances)
        si = 0 if not isinstance(si, int) else max(0, min(si, max(0, n_slides - 1)))
        out.append(si)
    return out


def boundary_metrics(words: Any, slide_advances: Any, slides: Any, *,
                     window_ms: int = 1200, min_gap_ms: int = 200,
                     risk_ms: int = DEFAULT_RISK_MS) -> Optional[dict]:
    """Exposure + impact of the word→slide boundary, for ONE take.

    Returns None when the take can't be measured (no deck, no taps, no words) —
    a deckless take has no boundaries and is not a silent zero.

    Computes the snap itself rather than reading the live flag, so the numbers
    describe what pause-snap DOES on this take regardless of how the flag is set
    — that is what makes the output comparable across takes and across a flag
    flip. `snap_enabled` records the live setting alongside, for context.
    """
    try:
        from services.slide_word_split import (
            _snap_boundaries_to_pauses, _pause_snap_enabled,
        )

        n_slides = len(slides) if isinstance(slides, list) else 0
        words_ms = _words_ms(words)
        raw_bounds = _boundary_times(slide_advances)
        if n_slides <= 0 or not words_ms or not raw_bounds:
            return None

        snapped_advances = _snap_boundaries_to_pauses(
            slide_advances, words, window_ms=window_ms, min_gap_ms=min_gap_ms)
        snapped_bounds = _boundary_times(snapped_advances)

        # ── exposure: words close enough to a tap that drift could move them ──
        at_risk = 0
        for start_ms, _tok in words_ms:
            for b in raw_bounds:
                if abs(start_ms - b) <= risk_ms:
                    at_risk += 1
                    break

        # ── impact: words whose slide actually changes under the snap ──
        before = _assign(words_ms, slide_advances, n_slides)
        after = _assign(words_ms, snapped_advances, n_slides)
        reassigned = sum(1 for a, b in zip(before, after) if a != b)

        # ── coverage: which boundaries found a pause to snap into ──
        shifts = [abs(s - r) for r, s in zip(raw_bounds, snapped_bounds)] \
            if len(snapped_bounds) == len(raw_bounds) else []
        snapped_n = sum(1 for d in shifts if d > 0)
        # A boundary that did not move either had no qualifying pause nearby OR
        # was already sitting in one. These are NOT distinguishable from the
        # shift alone, so the field is named for what it measures: unmoved.
        return {
            "words_total": len(words_ms),
            "slides_total": n_slides,
            "boundaries_total": len(raw_bounds),
            "words_at_risk": at_risk,
            "risk_ms": int(risk_ms),
            "words_reassigned": reassigned,
            "boundaries_moved": snapped_n,
            "boundaries_unmoved": len(raw_bounds) - snapped_n,
            "shift_ms_max": max(shifts) if shifts else 0,
            "shift_ms_median": sorted(shifts)[len(shifts) // 2] if shifts else 0,
            "snap_enabled": bool(_pause_snap_enabled()),
            "window_ms": int(window_ms),
            "min_gap_ms": int(min_gap_ms),
        }
    except Exception:
        # LIVE LOOP: a measurement must never break the analysis pipeline.
        return None
