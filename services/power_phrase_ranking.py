"""Coach-adjusted surfacing score for power phrases (willab Phase 4, 2026-06-15;
re-pointed onto the CONFIDENCE construct 2026-08-13 per SPEC.md §7.2).

The coach is the GATE — they tag (strong / to_work_on) + surface the acoustic
≤10 AFTER selection. This orders that already-approved set into the user's
"power phrases" by blending the human verdict (DOMINANT) with how the moment
was DELIVERED and how well it covered its topic/slide:

    power_score = w_c·coach_term + w_a·activation + w_s·slide_stickiness
                + confidence_term + w_b·album_quorum

WHAT THE 2026-08-13 RE-POINT CHANGED, AND WHY IT WAS NOT COSMETIC. The old
blend carried a ``direction`` term over {challenge, threat, ambiguous} — the
charisma construct. Two things were wrong with it. It had no written
operational definition, so nothing could say what a rater was being asked (the
defect SPEC §1.4 exists to prevent), and it was SUBJECTIVE where the rest of
this blend is measured. It is replaced by ``confidence`` (``conf-q-v1``, SPEC
§17): "how assured the speaker sounds in their delivery of this moment. A
property of the voice, not of the content." Single-barrelled, externally
anchored (Jiang & Pell 2017), and rated by a blind panel on the ternary
instrument every other state uses.

- coach_term: strong=+1, to_work_on=-1, untagged=0 — DOMINANT, so a coach-strong
  moment always outranks a to-work-on one. SMOOTHING: untagged → 0 → the order
  falls back to the automatic terms (no cold-start cliff before the coach
  reviews). NOT a percept, so it stays privileged (SPEC §7.2): strong /
  to_work_on is an EXPERT ASSESSMENT of whether the phrase is good, which is
  Feedback-type by §2's routing principle. Expert authority is appropriate
  there and inappropriate for a percept.
- activation: ``metrics["overall_score"]`` (~0-1); rank-derived proxy (1/rank)
  when it is absent. NAMING WARNING: despite the name this is NOT acoustic
  activation. services/lab_recording.py computes overall_score as
  ``0.5·topic_stickiness + 0.5·slide_stickiness`` — two LLM reads over the
  transcript TEXT. It is the CONTENT term. (The acoustic salience composite is
  transient and never persisted — services/snippet_salience.py — so it cannot
  reach this function; acoustics gate WHICH pieces are eligible to be ranked,
  which is a different thing.) The key is kept for compatibility.
- slide_stickiness: how well the talk covered the slide (~0-1).
- CONFIDENCE — the DELIVERY term, and what makes the ranking BLENDED (L2)
  rather than content-only. It enters EXACTLY ONCE, panel-sourced or
  machine-sourced, NEVER SUMMED (SPEC §7.2 / D8), because summing them would
  double-count one property of one clip:
    * panel — the blind multi-rater aggregate (services/state_ratings.py),
      weighted by ``quality`` = f(n_raters, agreement) so a two-rater split
      cannot move ranking as far as a five-rater consensus. The peer lane
      strengthens this term automatically as it grows, with no weight change.
    * machine — services/voice_confidence.py's speaker-relative composite in
      [-1, 1], used only where no panel label exists. NOT bucketed into three
      classes: that would destroy the variance needed to break ties across the
      unlabelled majority, which is most of the corpus.
- album_quorum: the redefined ``_W_B``. Fires when a clip CLEARS THE ALBUM
  QUORUM — multi-rater agreement (SPEC §9.1) — not when one person calls it
  confident. That distinction is what keeps it clear of the double-count ban:
  the confidence term is ONE AGGREGATED JUDGMENT on a clip, this is a
  CONSENSUS EVENT. Because nothing ages out of the album (§9.2), "cleared
  quorum" and "is in the album" are the same predicate, so the bonus does not
  decay — had the album rotated, ranking would drift for reasons unconnected
  to the speech.

THE ORDERING OF AUTHORITY IS THE INVARIANT, and it survives the re-point
(SPEC §7.1). Coach verdict dominant (swing 4.0) > breakthrough/quorum bonus
(2.5) > panel confidence (swing 3.0 at perfect quality, and quality is bounded
below 1) > machine confidence (swing 2.0) ≈ the content term. Delivery informs
the pick; it never overrules a human verdict.

Selection of the ≤10 stays PURELY acoustic (snippet_salience) — this only
reorders what the coach approved. AC-9: the score is internal, never surfaced.
Pure + unit-tested; no DB, no LLM, no user/coach-as-verdict surface.
"""
from __future__ import annotations

from typing import Any, Optional

_COACH_TERM = {"strong": 1.0, "to_work_on": -1.0}
# w_c dominant (human EXPERT verdict) > w_b quorum (consensus event) > the rest.
_W_C, _W_A, _W_S = 2.0, 1.0, 0.6
_W_B = 2.5

# Two weights for confidence because the two sources are on DIFFERENT SCALES
# and carry different reliability: the panel emits three discrete values
# aggregated over raters, the machine emits a continuous tanh read with a dead
# zone. One shared weight over both would be a scale mismatch dressed as
# simplicity. Sized so the panel sits above the machine and below the coach gap
# (4.0) — a percept never overrules an expert assessment of the phrase.
_W_CONF_PANEL = 1.5      # swing 3.0 at quality=1.0 (unreachable; bounded below)
_W_CONF_MACHINE = 1.0    # swing 2.0 — unchanged from the retired _W_V

# Stamped on the caller's blob beside sex_source (SPEC §7.2) so a ranking can
# be explained after the fact: which lane actually supplied the confidence.
SOURCE_PANEL = "human"
SOURCE_MACHINE = "machine"
SOURCE_NONE = "none"


def _num(v: Any) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def confidence_term(panel_confidence: Any = None,
                    machine_confidence: Any = None) -> tuple[float, str]:
    """The single confidence contribution + the lane that supplied it.

    ``(term, source)``. Split out from ``power_score`` because the SOURCE is
    reportable — the caller stamps ``label_source`` on the blob — and because
    the "exactly once" rule (D8) is the kind of invariant that should be
    readable in one place instead of inferred from an if/else inside a sum.

    The panel wins whenever it exists, at ANY quality: a one-rater panel is
    already discounted to 0.33 by ``quality`` and that discount is the designed
    answer to a thin panel. Falling back to the machine because the panel is
    small would silently prefer an unvalidated estimate over a real human
    judgment. Pure."""
    if isinstance(panel_confidence, dict):
        value = _num(panel_confidence.get("value"))
        quality = _num(panel_confidence.get("quality"))
        return _W_CONF_PANEL * quality * value, SOURCE_PANEL
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
    panel_confidence: Any = None,
    machine_confidence: Any = None,
    album_quorum: bool = False,
) -> float:
    """Coach-adjusted surfacing score (higher = better power phrase).

    ``panel_confidence`` is the ``services.state_ratings.aggregate`` blob
    (``{"value", "quality", …}``) or None. ``machine_confidence`` is
    ``services.voice_confidence.rank_term``'s float or None — and that helper
    already returns None whenever ``VOICE_CONFIDENCE_RANKING_ENABLED`` is off,
    so THE FLAG IS HONOURED WITHOUT ANY FLAG LOGIC IN HERE (SPEC §7.3: the flag
    now asks "is the machine fallback trusted yet", and with it off an
    unlabelled clip contributes 0 for confidence and ranks exactly as it did
    before the re-point).

    Every confidence input defaults to no-op, so a caller that has not been
    taught about the panel (the /strengths path, the master-document mean)
    scores byte-for-byte what it scored before — an unstamped piece is never
    penalised against a stamped one."""
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
    conf, _source = confidence_term(panel_confidence, machine_confidence)
    b = _W_B if album_quorum else 0.0
    return _W_C * coach + _W_A * a + _W_S * s + conf + b
