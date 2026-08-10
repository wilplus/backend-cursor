"""The manager engine — arbitration over feedback-engine candidates.

SPEC.md v3 §8.2 / §11, Appendix B (progression), Appendix D (grades),
Appendix H (these parameters). PURE: no DB, no clock, no randomness of its
own. Everything a caller cannot derive is passed in, so the whole policy is
unit-testable without a session.

WHAT THIS IS. `registry.can_fire()` answers "do I have a candidate" — a
SUBMISSION gate, not a decision to surface. This module decides what actually
reaches the user: which candidate wins, how many, in what form, and whether
anything surfaces at all. An engine proposes; the manager disposes.

THE ASYMMETRY EVERY PARAMETER INHERITS (H.0). A miss costs one opportunity;
there will be another recording. A FALSE POSITIVE COSTS TRUST — and Dixon,
Wickens & McCarley (2007) found false-alarm-prone automation degrades both
compliance AND reliance, where miss-prone automation degrades only reliance.
A detector that misses discredits itself. A detector that cries wolf
discredits THE MANAGER, and therefore every other detector behind it. With
C(FA) >> C(Miss) and P(signal) low, the optimal criterion sits high. When a
choice here is arguable, it goes toward silence.

AC-9. Nothing this module computes is user-facing. Priority values, PPV
estimates, mastery probabilities and deviation multiples are internal
arbitration inputs and must never enter a client-facing schema or any
user-visible copy. What reaches the user is a qualitative note, chosen here.

WHAT IS NOT SETTLED (H.8). Three of the six slots rest partly on inference,
and the flags are kept next to the constants rather than in a footnote,
because a constant with no visible provenance gets tuned by whoever is
annoyed by it first.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field, replace
from typing import Callable, Iterable, Optional, Sequence

# ── Progression states (Appendix B) ─────────────────────────────────────────
# FRAGILE is NOT on the fading arc: high performance, low calibration, and
# B.3 gives it no promotion path. It is listed here because leaving it out is
# how it silently gets treated as APPRENTICE.
NOVICE = "NOVICE"
APPRENTICE = "APPRENTICE"
FRAGILE = "FRAGILE"
GRADUATE = "GRADUATE"
STATES = (NOVICE, APPRENTICE, FRAGILE, GRADUATE)

# ── H.2 · Certainty floor ───────────────────────────────────────────────────
# 0.70 is DERIVED, not chosen: Wickens & Dixon (2007), meta-analysis of 20
# studies / 35 data points, found 0.70 the crossover below which automation
# produces WORSE performance than no aid at all. Above it, benefit scales
# roughly linearly — no cliff, so 0.85 is a target rather than a second gate.
#
# STATED IN PPV, NOT ACCURACY, and this is the part that bites. At low
# prevalence a nominally accurate detector is mostly wrong: 99% sensitivity
# and 99% specificity at 0.1% prevalence gives PPV ~9%. A "70% accurate"
# detector on a rare finding can sit in the teens. The floor is therefore
# precision, calibrated per detector against ITS OWN candidate base rate — a
# single global accuracy constant is the wrong shape.
PPV_FLOOR = 0.70
PPV_TARGET = 0.85

# ── H.1 · Budget ────────────────────────────────────────────────────────────
# Flat. NOT scaled to recording length: the bottleneck is the coachee's uptake
# capacity, and that does not grow with the material. Cowan (2001) puts true
# chunk capacity for novel un-rehearsed items at 3-5, centrally ~4; corrective
# feedback is exactly that case. Kulhavy et al. (1985) found feedback
# complexity INVERSELY related to both error correction and learning
# efficiency — the simplest feedback beat the most elaborate on both.
BUDGET_BASE = 1
BUDGET_CEILING = 3

# ── H.6 · Cooldown and mastery ──────────────────────────────────────────────
# Going quiet is better for RETENTION than staying on. Winstein & Schmidt
# (1990): faded 50% knowledge-of-results produced 35% less error at 24-hour
# retention (F(1,56)=6.24, p<.01) DESPITE equal or worse performance during
# acquisition. Continued feedback on a corrected behaviour is not maintenance,
# it is a crutch that suppresses the learner's own error detection.
COOLDOWN_SESSIONS = 2
MASTERY_THRESHOLD = 0.95          # Bayesian Knowledge Tracing standard
                                  # (Corbett & Anderson 1995)

# ── §8.2 / B.4 · Suppression floor ──────────────────────────────────────────
# R and G are both suppressors and must not compound into silence. The floor
# is asserted ON THE PRODUCT, never on each factor: two suppressors each above
# their own floor still multiply below both, which is how a GRADUATE-state
# dimension with one unacted impression falls through twice and never returns.
PRIORITY_FLOOR = 0.15
SPIKE_MULTIPLE = 2.0              # a deviation spike this size overcomes
                                  # cooldown AND decay (§8.2, B.4)

# Appendix D grades, D18. C = 0.0 makes the §11.1 routing gate ARITHMETIC, so
# the gate and the priority formula cannot drift apart.
EFFECT_SIZE = {"A": 1.0, "B": 0.6, "C": 0.0}

# G(state) — LONG-TERM per-dimension suppressor. BASELINE VALUES, founder-
# approved 2026-08-06. Derived from the FREQUENCY row of Appendix B.2 (every
# attempt / ~75% / ~50% or bandwidth-only), which is the only numeric anchor
# B gives; B.4 names G(state) without values. FRAGILE is 1.0 because B.2.1
# says do not fade it — it performs well and cannot tell why, so fading
# produces regression the user will not detect.
#
# These are the official baseline, not a placeholder. They still move on the
# outcome anchor rather than on preference — D24's rule that a measured
# threshold never adapts does NOT apply, because these are policy dials, not
# literature-measured values.
G_BY_STATE = {NOVICE: 1.0, APPRENTICE: 0.75, FRAGILE: 1.0, GRADUATE: 0.5}

# ── H.5 · Trading dimensions ────────────────────────────────────────────────
# Pairs whose targets move in OPPOSITE directions. Surfacing both is not
# merely crowded, it is self-contradictory advice — the user is told to move
# the same dial two ways. Suppressed at ANY distance, unlike a span overlap.
# Kept explicit and short; a general rule would over-suppress.
TRADES_AGAINST = {
    "concreteness": "abstraction",      # D1 / D2, one axis with opposite signs
    "abstraction": "concreteness",
}

# ── H.4 · Form, for a finding that was shown and not acted on ───────────────
FIRST_SHOWING = "FIRST_SHOWING"
REPEAT_AS_IS = "REPEAT_AS_IS"
REFRAME = "REFRAME"
CHANGE_INTERVENTION_TYPE = "CHANGE_INTERVENTION_TYPE"

# SPECIFIED, not invented: the decisions log sets ε_explore at ~10-20%.
# Bottom of the band, per H.0 — an exploration swap surfaces a rank-2 finding
# instead of rank 1, so the quota trades a known-better note for information.
EXPLORATION_RATE = 0.10

# ── THE SCIENCE CONTROLS (decisions log §B) ─────────────────────────────────
# THESE CANNOT BE RETROFITTED. Both must be running WHILE the data
# accumulates, or the accumulated data cannot answer the question they exist
# to answer — the same argument as the frozen drift reference (Appendix G.7).
# Every recording taken without them is a recording that can never contribute
# to a causal claim.
#
# THREE ORTHOGONAL RANDOMISATIONS, each answering a different question. They
# are easy to confuse and confusing them silently ruins the experiment:
#
#   gamma_control   PERMANENT, per (user, dimension).   BETWEEN-subject.
#                   "Does feedback on this dimension do anything at all, or
#                    do people improve just by recording more?"
#   withhold (20%)  PER SURFACING, per (user, dim, session).  WITHIN-subject.
#                   "Did THIS note change take N -> N+1?"
#   epsilon_explore PER SESSION, which RANK surfaces.
#                   "Is rank 1 actually the best thing to have said?"
GAMMA_CONTROL = 0.12              # decisions log: ~10-15%, midpoint
INTERVENTION_RANDOMISATION = 0.20  # decisions log: 20%

# Changing either salt RESHUFFLES EVERY ASSIGNMENT and silently splices two
# incompatible experiments together. Versioned so that is a deliberate act
# with a name, not an edit.
CONTROL_SALT = "willab-gamma-v1"
WITHHOLD_SALT = "willab-withhold-v1"
EXPLORE_SALT = "willab-explore-v1"


def _stable_fraction(*parts: str, salt: str) -> float:
    """A stable [0,1) from the parts — SHA-based, NOT Python's hash().

    `hash()` on a str is salted per process (PYTHONHASHSEED), so using it
    would REASSIGN EVERY USER ON EVERY DEPLOY. A control group that
    reshuffles is not a control group; it is noise that looks like one, and
    nothing downstream would ever report the problem.
    """
    digest = hashlib.blake2b("\x1f".join((salt,) + parts).encode("utf-8"),
                             digest_size=8).digest()
    return int.from_bytes(digest, "big") / float(1 << 64)


def in_control(user_id: str, dimension: str, *,
               gamma: float = GAMMA_CONTROL) -> bool:
    """gamma_control — this (user, dimension) pair receives NOTHING, ever.

    PER PAIR, NOT PER USER. A control user still gets normal feedback on
    every other dimension, so their experience is intact and the comparison
    is within-person across dimensions as well as between people.

    PERMANENT AND DETERMINISTIC. A per-session coin flip would put the same
    pair in and out of control and make the comparison meaningless — you
    would be measuring a user who sometimes got feedback, which is neither
    arm of the experiment.

    Without this you credit yourself with the practice effect: users improve
    by recording more, feedback or not, and nothing in the data separates the
    two.
    """
    if not user_id or gamma <= 0:
        return False
    return _stable_fraction(user_id, dimension, salt=CONTROL_SALT) < gamma


def is_withheld(user_id: str, dimension: str, session_id: str, *,
                rate: float = INTERVENTION_RANDOMISATION) -> bool:
    """Intervention randomisation — a note that WON is deliberately not shown.

    WHICH READING, locked by the founder 2026-08-06. The decisions log's
    "intervention randomisation, 20%" could have meant randomising the
    intervention TYPE instead. It does not: it randomises WHETHER an eligible
    note surfaces. Type-randomisation would leave "note vs no note" untested
    and risks incoherent advice — UNDERLINE on A2's overlap run when the
    contract's remedy is CUT points at the right words and asks the wrong
    thing.

    The within-subject arm. The same (user, dimension) pair produces both
    treated and untreated take-transitions, so take N -> N+1 change can be
    attributed to the note rather than to the take.

    UNLIKE gamma_control, THE SLOT IS CONSUMED. Backfilling with rank 2 would
    mean the user always receives something, and the untreated condition
    would never exist — the withhold would measure "rank 1 vs rank 2" instead
    of "note vs no note", which is what epsilon_explore already measures.

    Deterministic on the triple so a retried scoring pass reaches the same
    decision; an RNG here would make the arm depend on how many times the
    pipeline happened to run.
    """
    if not user_id or not session_id or rate <= 0:
        return False
    return _stable_fraction(user_id, dimension, session_id,
                            salt=WITHHOLD_SALT) < rate


def exploration_roll(user_id: str, session_id: str
                     ) -> Optional[Callable[[], float]]:
    """The roll `arbitrate` uses for the exploration quota — DETERMINISTIC.

    NOT `random.random`, and this is the whole point of the function existing.
    The surface that consumes this arbitration is POLLED: the ideal-text GET
    re-runs every few seconds while a take is analysing. A fresh random draw
    per request would re-decide the exploration branch on every poll, so the
    notes on screen would swap between rank 1 and rank 2 while the student
    watched — and the experiment would be measuring how many times the
    pipeline happened to run, not whether rank 1 is the best thing to say.

    Same reasoning `is_withheld` already states for its own arm, and the same
    SHA-based construction: `hash()` is salted per process, so it would
    reassign on every deploy.

    ONE DRAW PER (user, session). The quota is "which RANK surfaces this
    session" (§ THE SCIENCE CONTROLS), so the session is the unit and the
    draw must be stable across every read of it.

    None when there is no stable key — arbitrate then skips the branch
    entirely. Silence over a coin-flip that cannot be reproduced (H.0).
    """
    if not user_id or not session_id:
        return None
    value = _stable_fraction(user_id, session_id, salt=EXPLORE_SALT)
    return lambda: value


@dataclass(frozen=True)
class Candidate:
    """One engine's submission. The manager never recomputes a measurement."""
    dimension: str
    grade: str                          # A / B / C -> EFFECT_SIZE
    deviation: float                    # distance from target on this dimension
    ppv: float                          # THIS detector's precision, not accuracy
    anchor: tuple[float, float]         # (start, end) of the INTERVENTION span
    intervention: str = ""
    remediability: float = 1.0          # does the fix fit one rehearsal cycle
    k: int = 0                          # consecutive unacted impressions
    delta_t: float = 0.0                # sessions since last shown
    baseline_deviation: Optional[float] = None
    # An OPAQUE caller handle. The manager never reads it, never compares on
    # it, and carries it through `replace()` untouched.
    #
    # WHY IT EXISTS. arbitrate() returns Candidates, and a caller has to get
    # from those back to whatever object it submitted — a change row, a
    # suggestion, a span. Nothing else on this dataclass can do that job:
    # every field is either a measurement (two candidates may legitimately
    # share all of them) or is REWRITTEN by arbitrate(), so identity is lost
    # the moment `replace()` runs. Correlating on `anchor` instead works only
    # while no two lanes ever propose the same span, which is precisely the
    # case collision resolution exists to handle.
    ref: str = ""
    # Filled by arbitrate(); not an input.
    priority: float = 0.0
    form: str = FIRST_SHOWING
    exploration: bool = False


@dataclass
class UserState:
    """Everything about the user the manager reads. No DB handle."""
    user_id: str = ""                   # control-arm assignment key
    state_by_dimension: dict = field(default_factory=dict)
    p_mastery: dict = field(default_factory=dict)
    sessions_since_fired: dict = field(default_factory=dict)

    def state(self, dimension: str) -> str:
        return self.state_by_dimension.get(dimension, NOVICE)

    def budget_state(self, leading: Optional[str]) -> str:
        """Which state governs the budget — THE LEADING CANDIDATE'S dimension.

        Founder decision 2026-08-06: only NOVICE is capped at one; APPRENTICE,
        FRAGILE and GRADUATE may each see up to three. Appendix B makes state
        PER-DIMENSION, so there is no single "user state" to branch on and one
        has to be picked.

        The leading candidate's dimension is the right one: it is the note
        that will certainly surface, so the user's competence AT THAT THING is
        the load signal that matters. Reading the least-advanced dimension
        anywhere would let one untouched NOVICE dimension cap a GRADUATE at
        one note forever, which is what the founder decision rules out.
        """
        return self.state(leading) if leading else NOVICE


def r_decay(k: int, delta_t: float = 0.0, *, tau: Optional[float] = None) -> float:
    """Short-term within-session inaction decay (§8.2).

    Two forms. The v1.0 in-session form is the default because SPEC §14 says
    to start there; the cadence form activates only when a caller passes tau,
    which requires session-cadence data we do not have.

    A FACTOR WITH A FLOOR, never a multiplicand that can zero the product —
    priority must never reach 0.0 from user inaction alone, or an unacted note
    is deleted rather than demoted.
    """
    if tau is None:
        return max(0.20, 1.0 - 0.35 * max(0, k))
    gamma = 0.5
    return max(0.15, gamma ** max(0, k) + (1.0 - math.exp(-delta_t / tau)))


def g_gate(state: str) -> float:
    """Long-term per-dimension progression gate (Appendix B.4)."""
    return G_BY_STATE.get(state, 1.0)


def is_spike(c: Candidate) -> bool:
    """A deviation this far above the user's own baseline overrides both
    suppressors and the cooldown. A graduate who suddenly falls apart on a
    faded dimension gets the note back immediately (§8.2, B.4, H.6)."""
    base = c.baseline_deviation
    if base is None or base <= 0:
        return False
    return c.deviation >= SPIKE_MULTIPLE * base


def may_submit(c: Candidate, *, floor: float = PPV_FLOOR) -> bool:
    """H.2 — the certainty floor, on PPV.

    Below Wickens & Dixon's 0.70 crossover the aid is worse than no aid, so
    this is not a preference dial. Bias UPWARD for a detector whose errors
    skew toward false positives: it damages the manager, not only itself.
    """
    return c.ppv >= floor


def in_cooldown(user: UserState, dimension: str) -> bool:
    """H.6 — refractory period, plus a mastery gate that goes SILENT.

    Mastery is REVOCABLE: p_mastery falling back below threshold returns the
    dimension to rotation. A one-way ratchet strands the user, which is the
    same defect as a promotion-only progression state (Appendix B.3).
    """
    if user.p_mastery.get(dimension, 0.0) >= MASTERY_THRESHOLD:
        return True
    return user.sessions_since_fired.get(dimension, 999) < COOLDOWN_SESSIONS


def priority(c: Candidate, user: UserState, *,
             importance: Optional[Callable[[str], float]] = None) -> float:
    """§8.2 — bounded decay, never zero (D6).

        priority = (deviation x effect_size x remediability) x R(k, dt) x G(state)

    The floor lands on the PRODUCT R x G. A spike bypasses both suppressors
    entirely rather than merely clearing the floor — the point of the escape
    hatch is that a collapse resurfaces at full weight, not at 0.15.
    """
    weight = EFFECT_SIZE.get(c.grade, 0.0)
    if importance is not None:
        weight *= importance(c.dimension)
    base = abs(c.deviation) * weight * c.remediability

    if is_spike(c):
        return base
    suppressor = r_decay(c.k, c.delta_t) * g_gate(user.state(c.dimension))
    return base * max(PRIORITY_FLOOR, suppressor)


def _conflicts(a: Candidate, b: Candidate) -> bool:
    """Trading pair at any distance, or an overlapping intervention span."""
    if TRADES_AGAINST.get(a.dimension) == b.dimension:
        return True
    a0, a1 = a.anchor
    b0, b1 = b.anchor
    return a0 < b1 and b0 < a1


def independent_subset(candidates: Sequence[Candidate]) -> list[Candidate]:
    """H.5 — the largest non-conflicting set, resolved by priority.

    COLLISION RESOLUTION AND THE INDEPENDENCE COUNT ARE THE SAME OPERATION,
    which is why they are one function. Greedy by priority: keep a candidate
    if it conflicts with nothing already kept. Pairwise resolution would be
    wrong for a transitive chain — A overlaps B, B overlaps C, A and C do not
    — where dropping B alone leaves A and C both eligible.

    No study tests two feedback items on the same moment. The governing
    construct is Sweller's ELEMENT INTERACTIVITY: two findings on one span are
    maximally interactive, because the user must hold both to act on either.
    That is precisely the load Kulhavy et al. showed degrades correction rate.
    """
    kept: list[Candidate] = []
    for c in sorted(candidates, key=lambda x: x.priority, reverse=True):
        if not any(_conflicts(c, k) for k in kept):
            kept.append(c)
    return kept


def budget(user: UserState, independent: Sequence[Candidate]) -> int:
    """H.1 — flat cap, never scaled to recording length.

    A NOVICE gets exactly one at any length. APPRENTICE, FRAGILE and GRADUATE
    may each see up to three — the fading arc governs frequency and phrasing,
    not the per-session ceiling, and `G(state)` already suppresses a
    GRADUATE's candidates on priority so fewer clear the bar anyway. Two
    separate mechanisms, both applying (founder decision 2026-08-06).

    Above NOVICE the cap is the number of GENUINELY INDEPENDENT findings,
    capped at 3 — budgeting on element interactivity rather than on a raw
    count, because two findings the user must hold simultaneously to act on
    either cost far more than two unrelated ones.

    NOT SCALED TO LENGTH ON PURPOSE. No study in any domain — writing, music
    masterclass, surgical debrief, sports video review — varies performance
    length and measures the optimal feedback count. The coaching "rule of
    three" is practitioner folklore. The argument against scaling is
    structural: the bottleneck is the listener, not the material.

    `independent` MUST be priority-sorted; independent_subset() returns it
    that way. The leading candidate decides which state governs.
    """
    leading = independent[0].dimension if independent else None
    if user.budget_state(leading) == NOVICE:
        return BUDGET_BASE
    return min(BUDGET_CEILING, max(BUDGET_BASE, len(independent)))


def on_unacted(k: int) -> str:
    """H.4 — form for a finding shown before and not acted on.

    DO NOT ESCALATE. This slot has the strongest evidence of the six and it
    points against the intuitive answer. Cacioppo & Petty (1979): agreement
    PEAKS at ~3 exposures and declines by 5. Keating & Skurka (2024) put
    message fatigue at r = -.25 (k=18, N=24,236). The reactance literature
    adds that REPEATED behaviours provoke more reactance than one-off asks.

    And the decomposition settles it. A 2025 non-uptake study (n=641) found
    only 14.3% reliably act; ~30% engage but fail to implement (they already
    believe they complied), ~23% are motivated but structurally unable (they
    need a SMALLER step), and ~33% emotionally withdraw. Escalation fixes none
    of the three failure modes and actively worsens the third.
    """
    if k <= 0:
        return FIRST_SHOWING
    if k == 1:
        return REPEAT_AS_IS               # still inside the exposure peak
    if k == 2:
        return REFRAME                    # same point, different framing
    return CHANGE_INTERVENTION_TYPE       # never louder, longer or more insistent


# ── PM-8 · the experiment's record ──────────────────────────────────────────
ARM_CONTROL = "CONTROL"
ARM_WITHHELD = "WITHHELD"
ARM_EXPLORE = "EXPLORE"
ARM_TREATED = "TREATED"
ARM_NOT_SELECTED = "NOT_SELECTED"


def arm_rows(result: dict, *, session_id: str, user_id: str) -> list[dict]:
    """Turn one arbitration into rows for `intervention_arms`.

    ONE ROW PER (session, dimension) CONSIDERED — not per surfaced note. A
    per-note table would give the untreated arms no rows at all and record
    only the treatment group, which is the same defect as measuring only the
    people who answered.

    Running the controls without persisting this is strictly WORSE than not
    running them: 12% of pairs receive nothing and 20% of winning notes are
    withheld, users pay that cost in feedback, and without the arm stored next
    to the outcome no causal claim is recoverable — while it looks from the
    outside exactly like a working experiment.

    THE POLICY IS STAMPED PER ROW, salts included. Assignment is a pure
    function of (salt, user_id, dimension), so rows written either side of a
    salt change belong to two different experiments with no way to tell them
    apart afterwards. Reading the constants at analysis time instead would
    silently re-interpret old rows under a new policy.
    """
    arms = result.get("arms") or {}
    policy = {
        "control_salt": arms.get("control_salt"),
        "withhold_salt": arms.get("withhold_salt"),
        "gamma": arms.get("gamma_control"),
        "withhold_rate": arms.get("intervention_randomisation"),
        "exploration_rate": arms.get("epsilon_explore"),
    }

    def row(dimension, arm, *, priority=None, would=None, surfaced=False,
            form=None):
        return {"session_id": session_id, "user_id": user_id or None,
                "dimension_id": dimension, "arm": arm, "priority": priority,
                "would_have_surfaced": would, "surfaced": surfaced,
                "form": form, **policy}

    rows: list[dict] = []
    seen: set[str] = set()

    for c in result.get("selected") or ():
        seen.add(c.dimension)
        rows.append(row(c.dimension,
                        ARM_EXPLORE if c.exploration else ARM_TREATED,
                        priority=c.priority, would=True, surfaced=True,
                        form=c.form))

    # WITHHELD is the within-subject untreated condition and the single most
    # important arm to record: it is the only evidence the condition occurred
    # at all. `would_have_surfaced` is True by construction — it won.
    for dimension in result.get("withheld") or ():
        if dimension in seen:
            continue
        seen.add(dimension)
        rows.append(row(dimension, ARM_WITHHELD, would=True))

    # CONTROL carries would_have_surfaced=None, not False. The holdout is
    # removed from the pool BEFORE ranking, so whether it would have won is
    # genuinely unknown; writing False would assert something never tested.
    for dimension in result.get("control_held") or ():
        if dimension in seen:
            continue
        seen.add(dimension)
        rows.append(row(dimension, ARM_CONTROL))

    for dimension, _why in result.get("rejected") or ():
        if dimension in seen:
            continue
        seen.add(dimension)
        rows.append(row(dimension, ARM_NOT_SELECTED, would=False))

    return rows


def arbitrate(candidates: Iterable[Candidate], user: UserState, *,
              session_id: str = "",
              importance: Optional[Callable[[str], float]] = None,
              roll: Optional[Callable[[], float]] = None,
              exploration_rate: float = EXPLORATION_RATE,
              controls: bool = True) -> dict:
    """H.7 — the whole policy, in the order the appendix specifies.

    Returns the selected findings AND the counterfactual: what would have
    surfaced without the exploration swap, plus everything filtered and why.
    The counterfactual is what makes the exploration quota worth running — an
    off-policy learner needs the road not taken, and this is the component
    where the experiment nobody has run is cheapest to run.

    `roll` is injected rather than drawn here so the policy stays pure and a
    test can pin the exploration branch instead of retrying until it fires.
    """
    everything = list(candidates)
    rejected: list[tuple[Candidate, str]] = []

    # 0 · gamma_control — the PERMANENT holdout, removed from the POOL.
    #     Removed rather than suppressed at the end on purpose: a control
    #     dimension must not consume a budget slot, because the pair is meant
    #     to receive nothing on THIS dimension while the user's experience on
    #     every other dimension stays intact. Suppressing at the end would
    #     quietly reduce how much feedback control users get overall, which
    #     confounds the very comparison the arm exists to make.
    control_held: list[Candidate] = []
    if controls:
        pool = []
        for c in everything:
            if in_control(user.user_id, c.dimension):
                control_held.append(c)
                rejected.append((c, "gamma_control"))
            else:
                pool.append(c)
    else:
        pool = list(everything)

    # 1 · certainty floor — per-detector PPV, never global accuracy      (H.2)
    live = []
    for c in pool:
        if may_submit(c):
            live.append(c)
        else:
            rejected.append((c, f"ppv {c.ppv:.2f} < {PPV_FLOOR}"))

    # 2 · cooldown and mastery, with the spike escape                    (H.6)
    passed = []
    for c in live:
        if not in_cooldown(user, c.dimension) or is_spike(c):
            passed.append(c)
        else:
            rejected.append((c, "cooldown/mastery"))
    live = passed

    # 3 · priority                                          (§8.2, B.4, H.3)
    live = [replace(c, priority=priority(c, user, importance=importance))
            for c in live]

    # A grade-C dimension has effect_size 0.0, so its priority is exactly 0
    # and it can never win. Dropped explicitly rather than left to sort last:
    # the §11.1 grade gate and this formula must not drift apart (D18).
    scored: list[Candidate] = []
    zeroed: list[Candidate] = []
    for c in live:
        (scored if c.priority > 0 else zeroed).append(c)
    rejected.extend((c, "grade C — effect_size 0.0") for c in zeroed)

    # 4 · collisions, which is also the independence count               (H.5)
    independent = independent_subset(scored)
    dropped = {id(c) for c in independent}
    rejected.extend((c, "collision") for c in scored if id(c) not in dropped)

    # 5 · budget — flat, not length-scaled                               (H.1)
    n = budget(user, independent)
    selected = independent[:n]
    counterfactual = list(selected)

    # 6 · form, for anything previously unacted                          (H.4)
    selected = [replace(c, form=on_unacted(c.k)) for c in selected]

    # 7 · exploration quota — surface rank 2 or 3, log the road not taken
    explored = False
    if roll is not None and len(independent) > n and roll() < exploration_rate:
        swap = independent[n]
        selected = selected[:-1] + [replace(swap, form=on_unacted(swap.k),
                                            exploration=True)]
        explored = True

    # 8 · intervention randomisation — a note that WON is not shown.
    #     Applied LAST, and the slot is CONSUMED rather than backfilled: the
    #     untreated condition has to actually occur, or there is nothing to
    #     compare the treated one against. `withheld` is the counterfactual
    #     and must be persisted alongside the outcome, or the arm produces
    #     suppression with no experiment attached to it.
    withheld: list[Candidate] = []
    if controls and session_id:
        shown = []
        for c in selected:
            if is_withheld(user.user_id, c.dimension, session_id):
                withheld.append(c)
            else:
                shown.append(c)
        selected = shown

    return {
        "selected": selected,
        "counterfactual": counterfactual,
        "exploration": explored,
        "budget": n,
        "considered": len(everything),
        "rejected": [(c.dimension, why) for c, why in rejected],
        # THE EXPERIMENT'S RECORD. Whoever persists this must store all three
        # arms, not just what surfaced — an outcome with no arm attached is
        # an observation, and the whole point of the controls is that these
        # are not observations.
        "control_held": [c.dimension for c in control_held],
        "withheld": [c.dimension for c in withheld],
        "arms": {
            "gamma_control": GAMMA_CONTROL,
            "intervention_randomisation": INTERVENTION_RANDOMISATION,
            "epsilon_explore": exploration_rate,
            "control_salt": CONTROL_SALT,
            "withhold_salt": WITHHOLD_SALT,
        },
    }
