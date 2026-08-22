"""Product-only ranking for candidate presentation phrases.

The score blends an explicit one-sided professional-coach veto, content
coverage, slide coverage, and the stored machine confidence read:

    power_score = w_c·coach_term + w_a·activation + w_s·slide_stickiness
                + machine_confidence_term

Blind peer ratings and quorum are deliberately outside this API. They are
internal training/evaluation evidence and cannot influence user feedback,
Manager selection, Ideal Text, styling, key moments, or Voice Album. Unsupported
legacy and album-quorum inputs are rejected rather than silently ignored.

The score is internal and never surfaced. Pure; no DB or LLM.
"""
from __future__ import annotations

from typing import Any, Optional

# ONE-SIDED on purpose (2026-08-14): "strong" is not in this map and must not
# be re-added without a picker that a human actually chooses it with.
_COACH_TERM = {"to_work_on": -1.0}
# w_c dominant (human EXPERT verdict) > the rest.
_W_C, _W_A, _W_S = 2.0, 1.0, 0.6

# Peer labels are internal training/evaluation evidence and never enter this
# product ranking. Machine confidence is the only automatic delivery term;
# explicit coach product decisions remain represented by the coach tag.
_W_CONF_MACHINE = 1.0

# Stamped on the caller's blob beside sex_source (SPEC §7.2) so a ranking can
# be explained after the fact: which lane actually supplied the confidence.
SOURCE_MACHINE = "machine"
SOURCE_NONE = "none"


def _num(v: Any) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def confidence_term(machine_confidence: Any = None) -> tuple[float, str]:
    """The single confidence contribution + the lane that supplied it.

    ``(term, source)``. Split out from ``power_score`` because the SOURCE is
    reportable — the caller stamps ``label_source`` on the blob — and because
    the "exactly once" rule (D8) is the kind of invariant that should be
    readable in one place instead of inferred from an if/else inside a sum.

    Peer and panel inputs are deliberately not accepted: they are internal
    corpus evidence, not a live coaching signal. Pure."""
    m = machine_confidence
    if isinstance(m, (int, float)) and not isinstance(m, bool):
        return _W_CONF_MACHINE * float(m), SOURCE_MACHINE
    return 0.0, SOURCE_NONE


def power_score(
    *,
    activation: Any = None,
    slide_stickiness: Any = None,
    tag: Optional[str] = None,
    rank: Any = None,
    machine_confidence: Any = None,
) -> float:
    """Coach-adjusted surfacing score (higher = better power phrase).

    ``machine_confidence`` is ``services.voice_confidence.rank_term``'s float
    or None — and that helper
    already returns None whenever ``VOICE_CONFIDENCE_RANKING_ENABLED`` is off,
    so THE FLAG IS HONOURED WITHOUT ANY FLAG LOGIC IN HERE (SPEC §7.3: the flag
    now asks "is the machine fallback trusted yet", and with it off an
    unlabelled clip contributes 0 for confidence and ranks exactly as it did
    before the re-point).

    A missing machine value is a no-op, so an unstamped piece is never assigned
    an invented confidence value."""
    coach = _COACH_TERM.get(tag or "", 0.0)
    a = _num(activation)
    if (
        a == 0.0
        and isinstance(rank, (int, float))
        and not isinstance(rank, bool)
        and rank > 0
    ):
        a = 1.0 / float(rank)  # rank 1 → 1.0, rank 2 → 0.5, …
    s = _num(slide_stickiness)
    conf, _source = confidence_term(machine_confidence)
    return _W_C * coach + _W_A * a + _W_S * s + conf
