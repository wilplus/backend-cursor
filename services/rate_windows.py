"""Stitch snippets into ~40 s windows so a RATE can be measured at all.

SPEC.md v3 D33, Appendix F.2/F.4.1. PURE: no DB, no clock. `session_metrics`
supplies the pieces and writes the rows; everything here is arithmetic.

THE PROBLEM THIS SOLVES, measured rather than argued. `wpm`, `fillers` and
`pause_ms` gate at 30 s (F.2 — Henderson's planning cycle makes a sub-cycle
RATE swing with where the window landed). A snippet is 6.55 s at the median
and 17.4 s at p90, so EVERY per-snippet row for those three is
`insufficient_data` — not occasionally, always. A 60-second test recording
produced four snippets of ~15 s and therefore four refusals and zero usable
rate measurements, while containing more than three planning cycles of
perfectly measurable speech. The information was captured and thrown away for
being asked about at the wrong zoom.

The snippet is the F1 SEGMENTATION unit — slide-aligned, load-bearing for
per-slide transcription and ranking. It is not, and was never meant to be, a
measurement window. Appendix F-2's claim that it "sits almost exactly at one
planning CYCLE" was retracted on 2026-08-06 when the duration was finally
measured.

TWO GRAINS, AND THE REGISTRY DECIDES WHICH. A dimension whose minimum exceeds
the 90th-percentile snippet (`registry.measurable_in_a_snippet` is False) is
windowed here. Everything else stays per-snippet, untouched — the three LEVEL
measures are stable well inside one cycle and are already flowing.

GAP HANDLING, which is the part that has to be right. Two independent guards,
because a rate with an inflated denominator is silently wrong rather than
visibly missing:

  1. THE DENOMINATOR IS SUMMED SPEECH, NEVER WALL-CLOCK. A window's seconds
     are the sum of its snippets' durations, so a pause between takes cannot
     enter the denominator even if the window somehow spanned it. This alone
     makes the rate gap-immune.
  2. WINDOWS NEVER CROSS A RECORDING. A take boundary is a hard break, not a
     time-based heuristic — `_emit_drift_telemetry` is handed every snippet in
     the SESSION, which spans takes, and averaging across two takes measures
     neither. Within a recording, a long silence also breaks the window.

Guard 1 protects the arithmetic; guard 2 protects the meaning. Neither is
sufficient alone.

AC-9. Nothing here is user-facing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

# Appendix F.2: "Minimum window for any pause/disfluency rate: 30 s ...
# Preferred: 40 s." Built to the preferred figure — the extra 10 s is cheap
# once the window spans snippets at all, and the 30 s minimum is the point at
# which a rate stops being noise, not the point at which it becomes good.
WINDOW_SECONDS = 40.0

# A silence this long inside one recording ends the window. INVENTED, and the
# lesser of the two guards: the recording boundary above is what actually
# carries the argument, and the summed-speech denominator means a gap cannot
# corrupt the rate even when it does not break the window. Chosen an order of
# magnitude above any plausible rhetorical pause — Roberts & Francis put the
# perceptual pause floor at 600 ms, and Henderson's whole planning cycle is
# ~18 s — so 10 s of silence is a break in speaking, not a feature of it.
MAX_GAP_SECONDS = 10.0


@dataclass(frozen=True)
class Piece:
    """One snippet, reduced to what windowing needs."""
    snippet_id: str
    recording_id: Optional[str]
    start_ms: float
    duration_ms: float
    words: int = 0
    # dimension_id -> the snippet's raw value. A COUNT for a per-minute rate
    # (fillers), a LEVEL or an already-per-minute rate for the rest.
    values: dict = field(default_factory=dict)

    @property
    def end_ms(self) -> float:
        return self.start_ms + self.duration_ms


@dataclass(frozen=True)
class Window:
    """A stitched span, and the evidence for how it was built."""
    anchor_snippet_id: str          # the FIRST snippet — see the note below
    recording_id: Optional[str]
    seconds: float                  # SUMMED SPEECH, never wall-clock
    words: int
    pieces: int
    values: dict = field(default_factory=dict)

    @property
    def minutes(self) -> float:
        return self.seconds / 60.0

    @property
    def meets(self) -> bool:
        """Does this window clear the 30 s minimum? The trailing remainder of
        a recording usually will not, and is still emitted — F.5 makes
        "could not compute this" first-class, and dropping short windows would
        hide exactly how much speech is falling through."""
        return self.seconds >= 30.0


def _aggregate(pieces: Sequence[Piece], dimension: str, seconds: float,
               words: int) -> Optional[float]:
    """Combine one dimension across a window, per the REGISTRY's aggregation.

    The registry owns this fact (D31); restating Appendix F.4 here is how the
    two drift apart.

      per_minute      sum of counts / speech minutes        exact
      per_1000_words  sum of counts / (words / 1000)        exact
      mean            DURATION-WEIGHTED mean                 see below

    Duration-weighting is not a refinement, it is the correct roll-up for a
    value that is already a rate: the duration-weighted mean of per-snippet
    words-per-minute IS total words over total minutes. An unweighted mean
    would over-weight short snippets, which is the caveat the registry records
    against `wpm` today.

    For `pause_ms` — a MEAN pause length, not a rate — duration-weighting is
    an approximation, because the exact figure needs the pause COUNT per
    snippet and the pipeline does not store one. It assumes pause count scales
    with duration, which is roughly Henderson's finding. Recorded here rather
    than hidden: capturing a per-snippet pause count would make it exact.
    """
    from services import dimension_registry as registry

    how = registry.aggregation_of(dimension)
    if how is None:
        return None

    # `bool` is a subclass of `int`, so a stray True would otherwise be
    # aggregated as 1 — excluded explicitly rather than left to chance.
    have: list[tuple[Piece, float]] = [
        (p, float(v)) for p in pieces
        for v in (p.values.get(dimension),)
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    if not have:
        return None
    total = sum(v for _, v in have)

    if how == "per_minute":
        minutes = seconds / 60.0
        return (total / minutes) if minutes > 0 else None
    if how == "per_1000_words":
        return (total / (words / 1000.0)) if words > 0 else None
    if how == "sum":
        return total

    weight = sum(p.duration_ms for p, _ in have)
    if weight <= 0:
        return total / len(have)
    return sum(v * p.duration_ms for p, v in have) / weight


def build_windows(pieces: Sequence[Piece], *,
                  window_seconds: float = WINDOW_SECONDS,
                  max_gap_seconds: float = MAX_GAP_SECONDS,
                  dimensions: Sequence[str] = ()) -> list[Window]:
    """Group snippets into windows. Order and boundaries are the whole job.

    ANCHORED ON THE FIRST SNIPPET, deliberately. A window has no snippet id of
    its own, and the alternative — writing `snippet_id` NULL — would break
    idempotency: NULLs are DISTINCT in the unique index, so every re-run of
    the pipeline would insert duplicate windows instead of replacing them.
    Anchoring also keeps the row traceable to a point in the talk.

    A window's rate dimensions and a snippet's level dimensions never collide
    on that shared anchor, because they are different `dimension_id`s.
    """
    usable = [p for p in pieces
              if p.snippet_id and p.duration_ms and p.duration_ms > 0]
    # Sort by recording FIRST so a session spanning takes groups cleanly, and
    # by offset within it. `start_ms` alone would interleave two takes whose
    # offsets both restart near zero — which is exactly how a cross-take
    # average gets built by accident.
    usable.sort(key=lambda p: (str(p.recording_id or ""), p.start_ms))

    windows: list[Window] = []
    current: list[Piece] = []

    def close() -> None:
        if not current:
            return
        seconds = sum(p.duration_ms for p in current) / 1000.0
        words = sum(p.words for p in current)
        windows.append(Window(
            anchor_snippet_id=current[0].snippet_id,
            recording_id=current[0].recording_id,
            seconds=seconds,
            words=words,
            pieces=len(current),
            values={d: _aggregate(current, d, seconds, words)
                    for d in dimensions},
        ))
        current.clear()

    for piece in usable:
        if current:
            previous = current[-1]
            crossed_take = piece.recording_id != previous.recording_id
            gap = (piece.start_ms - previous.end_ms) / 1000.0
            if crossed_take or gap > max_gap_seconds:
                close()
        current.append(piece)
        if sum(p.duration_ms for p in current) / 1000.0 >= window_seconds:
            close()
    close()
    return windows
