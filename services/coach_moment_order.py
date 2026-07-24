"""Coach-panel moment ordering — key moments first (founder 2026-07-24, T1 · 1.2).

WHAT THIS IS
------------
A pure ordering function over the coach review packet's already-shaped
moments. It puts the MOST SIGNIFICANT moment first (key → close-to-key →
least distinctive) so the coach lands on the moments worth their scarce
attention before the flat ones, instead of scrolling a purely chronological
list.

It keys ONLY on the per-moment ``acoustic_read`` blob that
``services/acoustic_read.py`` already computes and the coach packet already
carries:
  * ``potentiometer`` ∈ [-1, 1] — the deterministic stress↔charisma read
    (−1 shaky/stress-leaning … +1 controlled/charisma-leaning). SIGN is the
    direction; MAGNITUDE is the strength of the lean.
  * ``outside_normal_range`` (bool) — the founder-2026-07-14 "potentially a
    key moment" triage flag (any control component ≥ 2σ from the speaker's
    own baseline).

HARD FENCES (read before touching)
----------------------------------
  * BLIND COACH. This orders on the DETERMINISTIC acoustic_read only — never
    the learned shadow model's guess. acoustic_read is fixed-weight and never
    trained, so surfacing/ordering by it "cannot anchor labels to a model's
    opinion" (services/acoustic_read.py). The shadow prediction stays
    fire-and-forget in the route and is NEVER fed into this ordering.
  * AC-9 / COACH-ONLY. This reorders the COACH packet only. It must never be
    applied to a user-facing payload — the user readout never carries
    acoustic_read (fence-tested in test_moment_suggestions.py), so it has
    nothing to order by anyway, but the intent is explicit: coach surface
    only.
  * NO NEW NUMBER SURFACED (CONSTRUCT). This attaches NOTHING to the moments —
    it only reorders the same dicts. The potentiometer / flag it reads are
    already on the coach packet by founder decision; this adds no score.

By MAGNITUDE, a hyper-positive (charisma) moment and a hyper-negative
(stress) moment rank equally high — so neither signed extreme is ever buried
under the other. Degrades to chronological when nothing carries an
acoustic_read (cold-start / legacy packet), so the panel reads exactly as it
does today until the signal exists.
"""
from __future__ import annotations

from typing import Any


def coach_moment_significance_key(snip: dict) -> tuple:
    """Sort key placing the most-significant coach moment FIRST.

    Order (each term descending-significance, negated for an ascending sort):
      1. ``outside_normal_range`` True first — the explicit key-moment flag.
      2. ``|potentiometer|`` desc — distinctiveness magnitude (both signed
         extremes rank high, so neither is buried).
      3. ``start_offset_ms`` asc — a stable, honest chronological tiebreak so
         neutral / cold-start rows keep the "what happened" order.

    Null-safe: a missing / non-dict acoustic_read, a non-numeric
    potentiometer, or a missing start all read as neutral and never raise.
    """
    ar = snip.get("acoustic_read")
    ar = ar if isinstance(ar, dict) else {}
    outside = 1 if ar.get("outside_normal_range") else 0
    pot = ar.get("potentiometer")
    magnitude = abs(float(pot)) if isinstance(pot, (int, float)) else 0.0
    start = snip.get("start_offset_ms")
    start = start if isinstance(start, (int, float)) else 0
    return (-outside, -magnitude, start)


def order_coach_moments_by_significance(snippets: list[dict]) -> list[Any]:
    """Return ``snippets`` most-significant-first (key → close-to-key → least
    distinctive), via :func:`coach_moment_significance_key`.

    A pure, stable reorder: the SAME dicts, no field attached, no score
    surfaced. ``sorted`` is stable, so rows that tie on every significance
    term keep their input order (the tiebreak already prefers chronological).
    """
    if not snippets:
        return list(snippets or [])
    return sorted(snippets, key=coach_moment_significance_key)
