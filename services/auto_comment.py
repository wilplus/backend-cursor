"""Deterministic qualitative observations for one spoken piece.

The comment compares pace, pausing, and energy with the rest of the take. It
does not infer a psychological state or surface a model label.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from services.say_it_stronger import _guard_copy, qualitative_self_comparison

logger = logging.getLogger(__name__)

def _observations(metrics: Any, session_means: Any) -> list:
    """The non-average self-comparison clauses for this piece (plain words,
    no numbers). Shared by both surfaces. Pure."""
    comparisons = qualitative_self_comparison(metrics, session_means) or {}
    out = []
    pace = comparisons.get("pace")
    if pace and "about" not in pace:
        out.append(f"the pace here was {pace}")
    pausing = comparisons.get("pausing")
    if pausing and "about" not in pausing:
        out.append(f"you took {pausing}")
    energy = comparisons.get("energy")
    if energy and "about" not in energy:
        out.append(f"it came through {energy}")
    return out


def build_auto_comment(metrics: Any, session_means: Any) -> Optional[str]:
    """One qualitative self-comparison. Silence beats filler."""
    observations = _observations(metrics, session_means)
    if not observations:
        return None
    return _guard_copy(
        "In this moment, " + " and ".join(observations[:2]) + "."
    )
