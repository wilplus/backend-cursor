"""Coach-adjusted surfacing score for power phrases (willab Phase 4, 2026-06-15;
re-pointed onto the CONFIDENCE construct 2026-08-13 per SPEC.md §7.2).

The coach is the GATE — they surface the acoustic ≤10 AFTER selection (and may
veto a phrase with to_work_on). This orders that already-approved set into the
user's
"power phrases" by blending the human verdict (DOMINANT) with how the moment
was DELIVERED and how well it covered its topic/slide:

    power_score = w_c·coach_term + w_a·activation + w_s·slide_stickiness
                + confidence_term

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

- coach_term: to_work_on=-1, everything else=0 — a one-sided VETO. NOT a
  percept, so it stays privileged (SPEC §7.2): to_work_on is an EXPERT
  ASSESSMENT of whether the phrase is good, which is Feedback-type by §2's
  routing principle. Expert authority is appropriate there and inappropriate
  for a percept.
- ⚠️ 2026-08-14 — THE ``strong`` HALF OF THIS TERM IS DELETED (founder ruling).
  It was never an assessment. No picker for it exists anywhere in the product:
  the FE wrote ``tag: cs.tag ?? "strong"`` and insights_payload defaults a
  missing tag to "strong" at publish, so the value was manufactured by the act
  of the coach TYPING A NOTE. That handed +1 at the dominant weight — the
  single largest term in this blend — to every snippet a coach happened to
  write on, which is a comment, not a verdict on the phrase. A term firing on
  "someone typed something" is worse than no term: it outranked the measured
  ones. ``to_work_on`` SURVIVES because it is the opposite case — no default
  ever produced it, so the rows that carry it were explicitly chosen (the
  picker that wrote them was removed 2026-08-07, which freezes the value, it
  does not falsify it). The coach's live positive verdict is not lost: it is
  the confidence panel below, where the coach actually rates, and where §17
  says what the rating means. SMOOTHING is unchanged: untagged → 0 → the order
  falls back to the automatic terms (no cold-start cliff before review).
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
- ⚠️ 2026-08-13, SAME DAY, SECOND FOUNDER VERDICT: ``_W_B`` IS DELETED, not
  re-pointed. The morning re-lock moved the 2.5 bonus from the coach's
  challenge mark onto an "album quorum"; the evening audit showed that quorum
  (coach + game_peer) is satisfiable by no production data, and the founder
  ruled the bonus itself a ghost of the retired charisma system: the Voice
  Album paradigm (acoustic moment → user agrees → coach agrees) is an ALBUM
  ENTRY rule, not a ranking term. Nothing about being in the album lifts a
  line's rank; the confidence term already carries everything delivery may
  say here. Do not re-add a bonus without a founder re-lock.

THE ORDERING OF AUTHORITY IS THE INVARIANT (SPEC §7.1), and with the coach
term now one-sided it is stated RELATIVELY, which is both stronger and easier
to check: a ``to_work_on`` phrase can never reach an otherwise-identical
untagged one. Every other term — content, slide coverage, panel, machine — is
available to BOTH phrases, so the 2.0 the veto removes is never earned back by
anything. That holds at any weight, so it cannot rot the way "swing 4.0 beats
swing 3.0" could; deleting ``_W_B`` (below) is what closed the last arithmetic
route around it. Delivery informs the pick; it never overrules a human verdict.

Selection of the ≤10 stays PURELY acoustic (snippet_salience) — this only
reorders what the coach approved. AC-9: the score is internal, never surfaced.
Pure + unit-tested; no DB, no LLM, no user/coach-as-verdict surface.
"""
from __future__ import annotations

from typing import Any, Optional

# ONE-SIDED on purpose (2026-08-14): "strong" is not in this map and must not
# be re-added without a picker that a human actually chooses it with.
_COACH_TERM = {"to_work_on": -1.0}
# w_c dominant (human EXPERT verdict) > the rest.
_W_C, _W_A, _W_S = 2.0, 1.0, 0.6

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
    return _W_C * coach + _W_A * a + _W_S * s + conf
