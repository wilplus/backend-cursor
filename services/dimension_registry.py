"""THE DIMENSION REGISTRY — one source for window, benchmark and intervention.

SPEC.md v3 D31. Mirrors Appendix F.4 (per-dimension window assignment),
Appendix F.2 (minimum-length gates), Appendix D (benchmark tiers) and
Appendix C (intervention routing).

WHY THIS FILE EXISTS. Appendices C, D and F specify window <-> benchmark <->
intervention completely — and before this file, NOTHING IN THE CODEBASE READ
ANY OF IT. There was no `fire_at` anywhere, no window-class table, no tier
lookup. Every consumer that needed one of these facts retyped it by hand from
the document, which means every consumer was free to disagree with every other
consumer, silently and permanently. The drift layer did exactly that: it
hardcoded six dimensions and a window class inside a metrics service.

So this is the brain. Change a window in Appendix F, change it HERE, and the
drift layer, the p-chart's tier filter, the feedback engine and the
intervention router all follow. A consumer that hardcodes any of these values
instead of importing them is a bug, whatever it looks like.

WHAT EACH FIELD IS FOR, AND THE ONE THAT IS EASIEST TO GET WRONG

  window_class    Appendix F.1's five classes. The span the measure is
                  computed over. NOT the same axis as segmentation — F.8's
                  F-2 establishes piece and window as orthogonal.

  denominator     Appendix F.3. The unit a rate is per. THE FIELD THAT IS
                  EASIEST TO GET WRONG, and the error is silent: a rate
                  computed over a different unit count than the benchmark
                  assumes is wrong by whatever the ratio happens to be, and
                  it still returns a plausible number.

  aggregation     How per-snippet values roll up to the SESSION class. NOT
                  cosmetic — see FILLERS below.

  min_seconds     Appendix F.2's minimum-length gate. Below it the measure is
                  noise, and F.5 makes INSUFFICIENT_DATA a first-class
                  outcome rather than a null to be papered over.

  tier            Appendix D provenance. T1/T2 are measured and NEVER adapt
                  (D24). Only T1/T2 with a real threshold may be charted:
                  a CORPUS_REL fire rate is pinned by construction.

  computed        Whether the measure actually EXISTS in the pipeline today.
                  Specified-but-not-built is the normal state here, and
                  pretending otherwise produces monitors over measures nobody
                  produces, which report STABLE forever.

THE FILLERS CORRECTION. `session_metrics` currently rolls fillers up as a
SUM. Appendix F.4 (E6) says the denominator is PER MINUTE. A sum scales with
how long the session was, so a 30-snippet session and a 5-snippet session are
not comparable and any monitor over it would mostly be measuring session
length. Declared here as a rate so the correction lives next to the window it
belongs to.

Pure: no DB, no I/O, unit-tested.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Appendix F.1 — the five window classes. There is no sixth.
WINDOW_CLASSES = ("FRAME", "UNIT", "CYCLE", "PROPORTIONAL", "SESSION")

# Appendix D — provenance tiers.
TIERS = ("T1", "T2", "T3", "CORPUS_REL")

# How per-snippet values roll up to the SESSION class.
AGGREGATIONS = ("mean", "sum", "per_minute", "per_1000_words", "max", "none")


@dataclass(frozen=True)
class Dimension:
    """One row of Appendix F.4, joined to its Appendix D benchmark and its
    Appendix C intervention. Frozen: a consumer must not mutate the spec."""
    dimension_id: str
    appendix_id: str                    # E5, E6, D7 ... traceability
    label: str
    window_class: str
    aggregation: str
    denominator: Optional[str] = None
    min_seconds: Optional[float] = None
    min_tokens: Optional[int] = None
    tier: str = "CORPUS_REL"
    fire_at: Optional[float] = None     # None = no threshold in code yet
    clear_at: Optional[float] = None
    benchmark_version: str = "measure-v1"
    intervention: Optional[str] = None  # Appendix C routing; None = no fire
    computed: bool = False              # produced by the pipeline TODAY?
    note: str = ""


# ── the registry ────────────────────────────────────────────────────────────
#
# `computed=True` is the six measures the pipeline actually produces
# (services/session_metrics.compute_session_global_metrics). Everything else
# in Appendix F.4 is specified and NOT built; listed so the gap is visible
# rather than forgotten, and so a consumer asking for it gets a real answer
# instead of a KeyError.

_REGISTRY: dict[str, Dimension] = {

    # ── live: produced per snippet today ────────────────────────────────────
    "wpm": Dimension(
        dimension_id="wpm", appendix_id="E5", label="Speech rate",
        window_class="CYCLE", aggregation="mean", denominator="wpm",
        min_seconds=30.0, tier="CORPUS_REL", computed=True,
        note="F.4 also assigns PROPORTIONAL for rate VARIATION; only the "
             "level is computed today.",
    ),
    "fillers": Dimension(
        dimension_id="fillers", appendix_id="E6", label="Filler density",
        window_class="CYCLE", aggregation="per_minute", denominator="per minute",
        min_seconds=30.0, tier="CORPUS_REL", computed=True,
        note="session_metrics rolls this up as a SUM, which scales with "
             "session length. F.4 says per minute. The sum is a "
             "session-length confound, not a measure of filler behaviour.",
    ),
    "pause_ms": Dimension(
        dimension_id="pause_ms", appendix_id="E4", label="Pause architecture",
        window_class="CYCLE", aggregation="mean", denominator="per minute",
        min_seconds=30.0, tier="CORPUS_REL", computed=True,
        note="F.4: 30 s minimum, PREFER 40 s — below one planning cycle this "
             "is noise.",
    ),
    "dynamic_db": Dimension(
        dimension_id="dynamic_db", appendix_id="E2", label="Loudness dynamics",
        window_class="CYCLE", aggregation="mean",
        min_seconds=30.0, tier="CORPUS_REL", computed=True,
    ),
    "pitch_center": Dimension(
        dimension_id="pitch_center", appendix_id="E1*", label="Pitch centre",
        window_class="CYCLE", aggregation="mean",
        min_seconds=30.0, tier="CORPUS_REL", computed=True,
        note="NOT E1. E1 is pitch VARIABILITY (range/SD); this is the centre, "
             "a level. The starred id marks the mismatch rather than hiding "
             "it — E1 proper is not computed, so its 'needs multiple IPs to "
             "estimate range' minimum does not transfer cleanly.",
    ),
    "energy": Dimension(
        dimension_id="energy", appendix_id="E2*", label="Energy ratio",
        window_class="CYCLE", aggregation="mean",
        min_seconds=30.0, tier="CORPUS_REL", computed=True,
        note="NOT A6. A6 is energy FRONT-LOAD, which F.4 puts at PROPORTIONAL "
             "(deciles) and Schuller shows relative thirds beat fixed windows "
             "96.5% vs 67.2%. This is a snippet-mean level.",
    ),

    # ── specified in Appendix F.4, NOT built ────────────────────────────────
    "conf": Dimension(
        dimension_id="conf", appendix_id="CONF", label="Vocal confidence",
        window_class="UNIT", aggregation="mean", min_seconds=1.6,
        tier="T2", computed=False,
        note="The only dimension with a scientifically defined window in "
             "seconds: 1.6 s per decision (Inbar 2025), >=10 units before a "
             "talk-level verdict (Quatieri, AUC 0.61 -> 0.83).",
    ),
    "spectral_effort": Dimension(
        dimension_id="spectral_effort", appendix_id="E3",
        label="Vocal effort / spectral", window_class="SESSION",
        aggregation="mean", min_seconds=30.0, computed=False,
        note="LTAS needs a minimum sample; F.4 says 30-60 s.",
    ),
    "terminal_contour": Dimension(
        dimension_id="terminal_contour", appendix_id="E7",
        label="Terminal contour", window_class="UNIT", aggregation="mean",
        denominator="proportion of assertions", min_tokens=None,
        computed=False,
        note="A proportion, not a rate. F.4 minimum is 10 ASSERTIONS.",
    ),
    "concreteness": Dimension(
        dimension_id="concreteness", appendix_id="D1", label="Concreteness",
        window_class="SESSION", aggregation="mean",
        denominator="per content word", min_tokens=100, computed=False,
    ),
    "pronoun_profile": Dimension(
        dimension_id="pronoun_profile", appendix_id="D7",
        label="Pronoun profile", window_class="SESSION",
        aggregation="per_1000_words", denominator="per 1,000 words",
        min_tokens=1000, computed=False,
        note="Low base rate. D20's Beta-Binomial posterior replaces the flat "
             "1,000-word gate.",
    ),
    "hedge_booster": Dimension(
        dimension_id="hedge_booster", appendix_id="D8",
        label="Hedge / booster", window_class="SESSION",
        aggregation="per_1000_words", denominator="per 1,000 words",
        min_tokens=1000, computed=False,
        note="D21 splits this into three lexicons by epistemic direction "
             "(HEDGE / BOOSTER / TIC). Kept as one row until the extractor "
             "exists, then it becomes three.",
    ),
    "arc_peak_ending": Dimension(
        dimension_id="arc_peak_ending", appendix_id="V6-V10",
        label="Arc / peak / ending", window_class="PROPORTIONAL",
        aggregation="none", computed=False,
        note="Deciles. F.4: NEVER fixed seconds.",
    ),
    "slide_alignment": Dimension(
        dimension_id="slide_alignment", appendix_id="V14-V17",
        label="Slide alignment", window_class="PROPORTIONAL",
        aggregation="none", computed=False,
        note="Window IS the slide's own display duration — variable by "
             "design, which is why no seconds value can be stated.",
    ),
}


# ── accessors ───────────────────────────────────────────────────────────────

def get(dimension_id: str) -> Optional[Dimension]:
    """The spec row, or None. None means 'not in Appendix F.4' — which for a
    consumer is the same as 'you invented this dimension', and it should stop
    rather than guess a window."""
    return _REGISTRY.get(str(dimension_id or "").strip())


def all_dimensions() -> tuple[Dimension, ...]:
    return tuple(_REGISTRY.values())


def live_dimensions() -> tuple[Dimension, ...]:
    """Only what the pipeline actually produces today.

    A monitor over a measure nobody computes reports STABLE forever, which is
    indistinguishable from working."""
    return tuple(d for d in _REGISTRY.values() if d.computed)


def window_class_of(dimension_id: str) -> Optional[str]:
    d = get(dimension_id)
    return d.window_class if d else None


def aggregation_of(dimension_id: str) -> Optional[str]:
    d = get(dimension_id)
    return d.aggregation if d else None


def meets_minimum(dimension_id: str, *, seconds: Optional[float] = None,
                  tokens: Optional[int] = None) -> bool:
    """Appendix F.2's minimum-length gate.

    Returns False when the observed window is BELOW the dimension's minimum —
    the caller should then write ``insufficient_data=True`` rather than a
    value, because F.5 makes 'could not compute this' a first-class outcome
    and a value below the gate is noise wearing a number's clothes.

    An UNKNOWN dimension returns False: refusing to measure something the
    spec does not define is the safe direction.
    """
    d = get(dimension_id)
    if d is None:
        return False
    if d.min_seconds is not None:
        if seconds is None or seconds < d.min_seconds:
            return False
    if d.min_tokens is not None:
        if tokens is None or tokens < d.min_tokens:
            return False
    return True


def is_chartable(dimension_id: str) -> bool:
    """May this dimension appear on a p-chart?

    Requires BOTH an ABSOLUTE tier and a real threshold. For CORPUS_REL the
    fire rate is pinned by construction (Appendix G.5) — a 10th-percentile
    threshold fails ~10% of the time definitionally, so charting it yields a
    monitor that can never signal while looking perfectly healthy. And a
    dimension with no `fire_at` has no decision to chart at all.
    """
    d = get(dimension_id)
    return bool(d and d.tier in ("T1", "T2") and d.fire_at is not None)


def adapts(dimension_id: str) -> bool:
    """D24 — T1/T2 thresholds NEVER adapt to ability; T3 and CORPUS_REL may.

    An ability-shifted T1 is no longer the literature-measured value while
    still being labelled T1, which voids the tier system silently.
    """
    d = get(dimension_id)
    return bool(d and d.tier in ("T3", "CORPUS_REL"))


def rollup(values_by_dimension: Any, *, minutes: Optional[float] = None,
           words: int = 0) -> dict:
    """Roll per-snippet values up to a session scalar THE WAY THE SPEC SAYS.

    ``{dimension_id: [values]}`` -> ``{dimension_id: value|None}``, with the
    aggregation read from this registry (Appendix F.4) rather than restated by
    the caller. Change a denominator here and every consumer follows; that is
    the entire point of the file.

    Lives in the registry, not in session_metrics, for two reasons: it is a
    registry operation, and session_metrics imports the DB client, so putting
    it there would make a pure aggregation untestable without a database.

    An UNKNOWN dimension returns None rather than a guessed mean. Refusing to
    aggregate something the spec has not defined is the safe direction — a
    plausible wrong number is worse than an absent one.
    """
    out: dict[str, Optional[float]] = {}
    for dimension_id, values in (values_by_dimension or {}).items():
        clean = [float(v) for v in (values or [])
                 if isinstance(v, (int, float)) and not isinstance(v, bool)]
        how = aggregation_of(dimension_id)
        if not clean or how is None:
            out[dimension_id] = None
            continue
        if how == "mean":
            out[dimension_id] = round(sum(clean) / len(clean), 3)
        elif how == "sum":
            out[dimension_id] = round(sum(clean), 3)
        elif how == "max":
            out[dimension_id] = round(max(clean), 3)
        elif how == "per_minute":
            out[dimension_id] = (round(sum(clean) / minutes, 3)
                                 if minutes else None)
        elif how == "per_1000_words":
            out[dimension_id] = (round(sum(clean) / words * 1000.0, 3)
                                 if words else None)
        else:
            # `none`: the registry is saying this dimension does not roll up
            # to a session scalar at all. PROPORTIONAL dimensions are deciles,
            # not a number, and forcing one would be a fabricated reading.
            out[dimension_id] = None
    return out


def validate() -> list[str]:
    """Self-check the registry against its own vocabulary. Returns a list of
    problems; empty means consistent. Called by the test suite so a bad edit
    fails CI rather than reaching a consumer."""
    problems: list[str] = []
    for key, d in _REGISTRY.items():
        if key != d.dimension_id:
            problems.append(f"{key}: key does not match dimension_id")
        if d.window_class not in WINDOW_CLASSES:
            problems.append(f"{key}: unknown window_class {d.window_class!r}")
        if d.tier not in TIERS:
            problems.append(f"{key}: unknown tier {d.tier!r}")
        if d.aggregation not in AGGREGATIONS:
            problems.append(f"{key}: unknown aggregation {d.aggregation!r}")
        if (d.fire_at is None) != (d.clear_at is None):
            problems.append(
                f"{key}: hysteresis is half-defined — every benchmark needs "
                f"BOTH fire_at and clear_at (Appendix D, Schmitt trigger)")
        # Only a LIVE dimension must have its threshold wired. A T1/T2 row
        # that is specified-but-not-built legitimately has fire_at=None: the
        # tier records the benchmark's PROVENANCE (Appendix D), which is a
        # different fact from whether the threshold reached code yet.
        if d.computed and d.tier in ("T1", "T2") and d.fire_at is None:
            problems.append(
                f"{key}: live dimension claims measured tier {d.tier} but "
                f"fire_at is None — the threshold never reached code")
    return problems
