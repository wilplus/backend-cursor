"""THE ONE DOOR onto the student's document.

Every lane that wants to put a mark on the ideal text — the polish/emphasis
star lane, the profanity lane, the cross-take prior-take lane, the master
model's block upgrades — comes through here, becomes a
``manager_engine.Candidate``, and reaches the screen ONLY if
``arbitrate()`` selects it.

WHY THIS FILE EXISTS. ``services/manager_engine.py`` is a complete, tested
arbitration policy — budget, collisions, cooldown, the certainty floor, the
three randomisation arms — and until this file it had NO CALLER ANYWHERE IN
PRODUCTION. Meanwhile ``_tracked_changes_block`` assembled three lanes by
concatenation and served every one of them. The budget the whole of Appendix
H exists to enforce was not being enforced, because nothing connected the two
halves. That is the gap this closes: not a new policy, a missing wire.

Founder decision 2026-08-07: the manager engine is the SOLE source of
``changes``. A lane that does not pass through ``select()`` does not reach the
user, whatever it looks like.


────────────────────────────────────────────────────────────────────────────
WHAT THE ENGINE ACTUALLY DECIDES TODAY — READ THIS BEFORE TUNING ANYTHING
────────────────────────────────────────────────────────────────────────────

**It enforces the budget, resolves collisions, and picks the form. It does
NOT rank.** Every candidate this adapter builds carries the SAME grade, the
SAME deviation and the SAME ppv, so every priority comes out identical and the
selection order is document order.

That is deliberate, and it is the honest position rather than a shortcut:

* ``deviation`` is "distance from target on this dimension". The LLM lanes
  measure no dimension and have no target, so there is no distance to state.
* ``grade`` is an Appendix D effect size, read from the literature. No lane
  here has one.
* ``ppv`` is THIS detector's measured precision. Nothing has ever measured
  the polish lane's.

Giving them different made-up values would produce a ranking with no evidence
under it — a plausible wrong number, which this codebase has already been
bitten by twice (the decorative ``denominator`` on ``wpm``; the ``pitch_center``
unit that said Hz and meant semitones). A uniform value at least announces
itself as uniform.

TWO THINGS TURN THIS INTO REAL RANKING, and neither is a tuning session:

1. ``dimension_registry.can_fire()`` starts returning True for something.
   It returns False for EVERY row today — not one dimension in the registry
   has a ``fire_at``. The measured lane is completely closed, which is why the
   LLM lanes are admitted under their own keys below rather than being made to
   masquerade as registry dimensions.
2. ``intervention_decision`` rows accumulate (SPEC-parts-locking-and-layers
   §6). "We proposed this and the person it was for said no" is the only
   direct measurement of lane precision this product will ever collect, and it
   is what replaces the assumed PPV with a real one.


────────────────────────────────────────────────────────────────────────────
AC-9
────────────────────────────────────────────────────────────────────────────
``priority``, ``ppv``, ``deviation`` and the arm assignment are arbitration
inputs. NONE of them enters the returned change dicts. What crosses to the
client is exactly what crossed before — span, quote, kind, source, the
existing closed-vocabulary ``why_key`` — minus everything the budget cut.
``kept()`` builds its output by copying the caller's own dicts, so a future
field added here cannot leak by accident: it would have to be written into the
change explicitly.

Pure: no DB, no clock, no randomness. Unit-testable without a session.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from services import manager_engine as me

logger = logging.getLogger(__name__)


# ── the lane keys ───────────────────────────────────────────────────────────
# A lane is NOT a registry dimension, and the prefix is there so nobody ever
# joins these rows to Appendix F.4 by name. `intervention_arms.dimension_id`
# takes whatever string is in `Candidate.dimension`; an un-prefixed "polish"
# sitting in that column next to a real "wpm" is an invitation to average the
# two, and the analyst doing it would have no way to know.
LANE_PREFIX = "lane:"

# The closed vocabulary, mirroring services/tracked_changes._kind_and_source
# plus the two cross-take lanes. An unknown source is REFUSED, not admitted
# under a guessed key: a lane nobody declared here is a lane nobody decided
# should reach the user, and the FE's own `source` validation would drop it
# one layer later anyway.
LANE_SOURCES = (
    "polish",       # light continuity polish offered as an approvable star
    "wording",      # say-it-stronger replace
    "profanity",    # lexicon hit
    "delivery",     # advice — delivery star
    "structural",   # advice — structural star
    "prior_take",   # cross-take: an earlier take said it better
    "new_take",     # master model: a newer take beat this block
)


def lane_of(change: Any) -> Optional[str]:
    """The manager key for one change, or None when the lane is undeclared."""
    src = (change or {}).get("source") if isinstance(change, dict) else None
    if src in LANE_SOURCES:
        return LANE_PREFIX + str(src)
    return None


# ── the three values the engine needs and no lane can supply ────────────────
#
# ONE constant each, in one place, with the provenance written down. Sprinkling
# per-lane numbers through the adapter would hide that they are all guesses.

# AT THE FLOOR, ON PURPOSE. `may_submit` compares `>=`, so 0.70 passes by
# exactly nothing. This is the weakest claim that still lets a lane ship: we
# are asserting the Wickens & Dixon minimum and not one point more. A lane
# later MEASURED below it dies here automatically, which is the whole reason
# the floor is stated in PPV rather than accuracy.
#
# Deliberately NOT varied by lane. Profanity is a deterministic lexicon match
# and its DETECTOR precision is ~1.0 — but the certainty floor is about the
# INTERVENTION being right ("you should change this word"), and that has never
# been measured for any lane here. A per-lane spread would be a ranking dressed
# as a measurement.
LANE_PPV = me.PPV_FLOOR

# EFFECT_SIZE["B"] = 0.6. Not "A" (that claims a large literature effect none
# of these lanes has) and not "C" (which is 0.0 and would mean nothing ever
# surfaces — the §11.1 routing gate is arithmetic).
LANE_GRADE = "B"

# `priority` scales linearly with this, so a uniform value means it cancels
# and the order falls to the stable sort — i.e. document order. Stated as a
# constant so that is visible rather than emergent.
LANE_DEVIATION = 1.0

# THE BUDGET DIAL, and the one place a reader should look for "why 3".
#
# `budget()` reads the LEADING candidate's progression state and caps NOVICE at
# exactly one note. There is no progression tracking for the LLM lanes, so an
# empty UserState would default every lane to NOVICE and quietly ship a
# budget of 1 — not by decision, by omission. The founder's stated budget is 3
# (SPEC-parts-locking-and-layers §R1, "max 3 interventions per take, total,
# across both layers"), so the lane state is DECLARED here.
#
# When real progression tracking lands, read the user's actual state and delete
# this. Until then it is a policy dial with a name, not an inferred fact.
LANE_STATE = me.APPRENTICE


def _controls_enabled() -> bool:
    """The three randomisation arms (gamma_control / withhold / explore).

    DEFAULT OFF, and this is a scientific decision rather than a caution.
    Switching them on starts a real experiment whose UNIT IS THE LANE — 12% of
    (user, lane) pairs would permanently receive nothing from that lane, and
    20% of winning notes would be suppressed. That is a founder call about
    running an RCT on LLM lanes, not a side effect of wiring the budget.

    The mechanism is `user_id`: `in_control("")` and `is_withheld("")` both
    return False by construction, so withholding the id makes the arms inert
    without touching arbitrate()'s policy. Flipping this flag therefore turns
    the experiment on in exactly one place — AND obliges the caller to persist
    `arm_rows()`, because the module is explicit that running the arms without
    storing them is strictly worse than not running them at all.

    DEFAULT FLIPPED ON 2026-08-10, after all three exit conditions landed in
    one change (founder approval, Task II):

      * `arm_rows()` is persisted — `_record_arms` in the ideal-text serve
        path, gated on the controls actually having run;
      * the exploration quota has a REAL roll — `exploration_roll`, stable per
        (user, session) rather than random, because this surface is polled;
      * the session key is the arc's latest spoken take, not the doc-level id
        (None under the master flag, which would have silenced the withhold
        arm and dropped every arm row).

    Setting MANAGER_CONTROLS_ENABLED=0 in the environment still switches the
    whole experiment off in one place, with no code change.
    """
    return (os.getenv("MANAGER_CONTROLS_ENABLED") or "1").strip().lower() \
        in ("1", "true", "yes")


def _span(change: Any) -> Optional[tuple]:
    """(start, end) as floats, or None when the change has no usable span.

    A ZERO-WIDTH SPAN IS REFUSED, and this is load-bearing rather than
    defensive. `master_document.upgrade_changes` emits candidate block
    additions as ``kind: "insert"`` anchored at ``{start: len(doc), end:
    len(doc)}`` — nothing to strike, nothing to bold. The FE has always
    dropped those (`mapDocumentSuggestions` requires `end > start` and only
    accepts replace/bold/advice), so before the gate they cost nothing.

    Behind a budget they would cost a SLOT: an invisible candidate would win
    one of three places and the student would see two marks where the engine
    thinks it served three. Anything that cannot become a visible mark must
    not be arbitrated over.
    """
    try:
        s = change["span"]
        start, end = float(s["start"]), float(s["end"])
    except (KeyError, TypeError, ValueError):
        return None
    if end <= start:
        return None
    return (start, end)


def to_candidates(changes: Any) -> list:
    """Change dicts -> Candidates, in the order given.

    A change with no declared lane or no usable span produces NO candidate and
    is therefore dropped: the engine is the only door, so failing to become a
    candidate is failing to reach the user. That is the safe direction — the
    alternative is a lane that bypasses the budget by being malformed.

    `ref` is the change's INDEX in the list handed in, not its `id`: ids are
    lane-generated and two lanes have already been observed to mint the same
    one (`build_tracked_changes` keys on snippet_id; `prior_take` on
    "prior:<snippet_id>"; block offers on "block:<key>"). An index is unique by
    construction and is what `kept()` maps back through.
    """
    out: list = []
    for i, c in enumerate(changes or []):
        if not isinstance(c, dict):
            continue
        lane = lane_of(c)
        anchor = _span(c)
        if lane is None or anchor is None:
            continue
        out.append(me.Candidate(
            dimension=lane,
            grade=LANE_GRADE,
            deviation=LANE_DEVIATION,
            ppv=LANE_PPV,
            anchor=anchor,
            intervention=str(c.get("kind") or ""),
            # `k` is "consecutive impressions shown and NOT acted on", and
            # nothing logs impressions today — only DECISIONS (the ledger,
            # `_applied`), which is a different fact. 0 means FIRST_SHOWING,
            # which is the truthful answer to a question we cannot answer:
            # a non-zero guess would trigger H.4's REFRAME /
            # CHANGE_INTERVENTION_TYPE machinery on a repetition that may
            # never have happened.
            k=0,
            delta_t=0.0,
            ref=str(i),
        ))
    return out


def user_state(candidates: Any) -> me.UserState:
    """The UserState the lanes arbitrate under, built from what is present.

    Derived from the candidate list rather than stored so it CANNOT go stale:
    a lane added later gets its state the moment it produces a candidate, and a
    lane removed leaves nothing behind. `user_id` is deliberately absent here —
    the caller adds it (or does not) and that single choice is what arms the
    experiment. See `_controls_enabled`.
    """
    lanes = {c.dimension for c in (candidates or [])}
    return me.UserState(
        state_by_dimension={lane: LANE_STATE for lane in lanes},
        p_mastery={},
        # 999 = "never fired", so nothing starts inside the refractory period.
        # There is no per-lane firing history to read; an absent key would give
        # the same answer via the same default, but writing it makes the
        # assumption visible instead of inherited.
        sessions_since_fired={lane: 999 for lane in lanes},
    )


# ── Confident Voice, and the rendering registry ─────────────────────────────
#
# "Confident Voice" is the founder-facing name for the charisma-trigger star
# family (the F2 signal; internal trigger string 'charisma'). CONSTRUCT fence:
# it surfaces as a qualitative STAR badge, never a number.
CONFIDENT_VOICE_TRIGGER = "charisma"

# Founder copy, verbatim (SPEC-lockin-loop-and-coach-panel §2). LIVE LOOP:
# changing this string needs founder sign-off.
PENDING_BETTER_VERSION_COPY = "better version pending..."

# ── THE OPS TABLE (Appendix C, wired live — founder GO 2026-08-10) ──────────
#
# C.2's closed set of intervention TYPES is the layer that never grows even
# though findings do, and C.4's rule is that presentation derives from the
# TYPE alone — never from which lane or finding produced the change. The live
# lanes ship a 4-kind wire shape (replace/insert/bold/advice) that predates
# the contract; `intervention_type_of` is the C.2 mapping that closes the
# gap, and everything downstream (the visual, the serve mix caps) reads the
# TYPE ROW, not the lane:
#
#   replace / new_take / prior_take → REWRITE      ("change these words" —
#                                                   the block-upgrade lane
#                                                   offers the NEWER TAKE's
#                                                   words, L1's select)
#   insert                          → ADD
#   bold                            → EMPHASISE    (V5/V11/V12 family)
#   advice                          → EMPHASISE    (delivery/structural
#                                                   prompts — V11–V13)
#   trigger == charisma             → NOTICE       (C.2 lists "confidence
#                                                   moments" here: awareness
#                                                   only, no action verb —
#                                                   the star badge, CONSTRUCT)
#
# Presentation per type (C.4, this surface's three affordances):
#   REWRITE / ADD / CUT → underline (inline diff) · EMPHASISE / DE_EMPHASISE
#   → bold · NOTICE → star.
#
# `serve_cap` is the PER-ARBITRATION mix cap (founder 2026-08-10: block
# rewrites were winning every budget slot — "the interventions are only the
# text rewrites"). Priorities are uniform and ties break by document order,
# so an uncapped REWRITE lane anchored early eats every slot; capping the
# POOL fed to the engine guarantees a metric-driven EMPHASISE / NOTICE slot
# survives whenever one proposed. None = uncapped (the budget still binds).
#
# THE CAP IS DERIVED, not a literal (founder 2026-08-11, when the ceiling
# moved 3 → 2 and the budget's unit became the slide). It was written as the
# number 2 against a ceiling of 3 — "all but one slot" — and a hard-coded 2
# under a ceiling of 2 is not a reservation at all: the rewrites fill the
# budget, document order puts them first, and the accent that Appendix C
# exists to protect never lands. Deriving it keeps the RULE ("one lane may
# not take the last slot") instead of the arithmetic that happened to
# express it.
_VISUAL_COMPOSITION = "underline"     # inline diff — text edits
_VISUAL_ACCENT = "bold"               # behavioural accents
_VISUAL_STAR = "star"                 # NOTICE — Confident Voice only

TYPE_ROWS: dict = {
    "REWRITE":      {"visual": _VISUAL_COMPOSITION,
                     "serve_cap": max(1, me.BUDGET_CEILING - 1)},
    "RESTRUCTURE":  {"visual": _VISUAL_COMPOSITION, "serve_cap": None},
    "ADD":          {"visual": _VISUAL_COMPOSITION, "serve_cap": None},
    "CUT":          {"visual": _VISUAL_COMPOSITION, "serve_cap": None},
    "EMPHASISE":    {"visual": _VISUAL_ACCENT,      "serve_cap": None},
    "DE_EMPHASISE": {"visual": _VISUAL_ACCENT,      "serve_cap": None},
    "NOTICE":       {"visual": _VISUAL_STAR,        "serve_cap": None},
    "REHEARSE":     {"visual": _VISUAL_ACCENT,      "serve_cap": None},
}


def intervention_type_of(change: Any) -> str:
    """The C.2 closed-set type of one live change. The ONE mapping."""
    c = change if isinstance(change, dict) else {}
    if c.get("trigger") == CONFIDENT_VOICE_TRIGGER:
        return "NOTICE"
    kind = c.get("kind")
    if kind == "insert":
        return "ADD"
    if kind in ("bold", "advice"):
        return "EMPHASISE"
    return "REWRITE"


def visual_of(change: Any) -> str:
    """Which visual a change renders as — derived from its C.2 TYPE and
    nothing else (C.4's one rule: presentation never keys on the lane)."""
    return TYPE_ROWS[intervention_type_of(change)]["visual"]


def filter_by_type_caps(changes: Any, group_of: Any = None) -> list:
    """The mix caps, applied to the POOL the engine arbitrates over.

    COUNTED IN THE SAME UNIT AS THE BUDGET (founder 2026-08-11). The budget
    is per slide now; a cap counted across the whole document would reserve
    one accent slot for a TEN-SLIDE deck and starve nine slides of their
    rewrites — a global cap and a per-slide budget silently disagree about
    what "the mix" is. `group_of` absent counts document-wide, which is the
    old behaviour and what a caller without the document gets.

    A cap RESERVES space, it does not ration: it binds ONLY while another
    type is actually proposing. An all-rewrite pool passes untouched — with
    nothing to mix, serving two of an available three would starve the
    student for no benefit — but the moment a metric-driven EMPHASISE or a
    NOTICE proposes alongside, the capped type stops being able to fill
    every slot ahead of it.

    BEFORE arbitration on purpose: the engine's budget is flat and its
    tie-break is document order, so capping afterwards would return fewer
    than three when three were available. Within a capped type the kept
    entries are the FIRST in the incoming list — document order, the same
    tie-break the engine itself uses, so which rewrites survive is the same
    answer the uncapped system gave. Pure."""
    rows = [c for c in (changes or []) if isinstance(c, dict)]

    def _servable(c: dict) -> bool:
        # A zero-width span is refused at to_candidates and can never win a
        # slot — it must neither count as "another type proposing" (which
        # would arm the cap over a phantom mix) nor spend a capped type's
        # allowance.
        span = _span(c)
        return span is not None and span[1] > span[0]

    def _g(c: dict) -> Any:
        return group_of(c) if callable(group_of) else None

    # "Another type is proposing" is a per-GROUP fact too: a bold on slide 7
    # must not arm the cap over slide 2's rewrites, where nothing else is
    # competing for the slot.
    types: dict = {}
    for c in rows:
        if _servable(c):
            types.setdefault(_g(c), set()).add(intervention_type_of(c))
    counts: dict = {}
    kept: list = []
    for c in rows:
        if not _servable(c):
            kept.append(c)   # passes through; to_candidates refuses it
            continue
        t = intervention_type_of(c)
        g = _g(c)
        cap = (TYPE_ROWS.get(t) or {}).get("serve_cap")
        others_propose = any(x != t for x in types.get(g, ()))
        if cap is not None and others_propose and counts.get((g, t), 0) >= cap:
            continue
        counts[(g, t)] = counts.get((g, t), 0) + 1
        kept.append(c)
    return kept


def filter_by_layer(changes: Any, parts: Any) -> list:
    """R1, second generation — the founder's locked-text rule (2026-08-10).

    RUNS BEFORE BUDGET SELECTION, and the order is the rule rather than an
    implementation detail. Filtering afterwards would spend budget slots
    proposing rewrites on text the speaker has already committed to memory:
    the slots would be consumed, the notes would be dropped at render time, and
    the student would see one intervention where the engine believes it served
    three.

    THE RULE (SPEC-lockin-loop-and-coach-panel §2, verbatim founder decision):

      * an OPEN part takes EVERYTHING — composition (rewrites) and
        accentuation (bold/advice) both pass, and the budget decides.
      * a LOCKED part takes NOTHING — "ordinary AI corrections skip locked
        text entirely" — with ONE exception: a Confident Voice detection
        passes through TAGGED (`pending_better_version` + the founder's
        copy), so the FE renders a small prompt instead of a normal offer.

    This supersedes the first generation, which allowed the whole
    accentuation layer on locked parts and refused accentuation on open ones.
    The founder overruled both halves in the same decision: locked text is
    the speaker's committed memory — styling it is still touching it — and an
    open paragraph may legitimately carry a delivery accent while its wording
    is still moving.

    `parts` empty or absent → EVERY change passes. A document with no stored
    identity has no locks either, so there is nothing to enforce; gating on
    absent parts would silence the whole surface the moment a document had not
    been saved yet.

    Two things are dropped rather than resolved, unchanged from gen one:

      * a change whose `kind` no layer classifies. An unnamed lane is one
        nobody decided the phase rules for, and defaulting it in would let an
        unnamed lane touch locked text.
      * a change whose span STRADDLES two parts. Half of it is in a locked
        paragraph and half is not, and there is no honest rule for that.

    This is what enforces L1 mechanically rather than by convention: nothing
    rewrites committed text, and the filter is where "must never" stops being
    a comment.
    """
    from services.ideal_text_parts import layer_of_kind, part_at, part_spans
    rows = [c for c in (changes or []) if isinstance(c, dict)]
    spans = part_spans(parts)
    if not spans:
        return rows
    kept: list = []
    for c in rows:
        if layer_of_kind(c.get("kind")) is None:
            continue
        span = _span(c)
        if span is None:
            continue
        part = part_at(spans, span[0], span[1])
        if part is None:
            continue
        locked = bool((part or {}).get("locked_at"))
        if not locked:
            kept.append(c)
            continue
        if c.get("trigger") == CONFIDENT_VOICE_TRIGGER:
            kept.append({**c, "pending_better_version": True,
                         "pending_copy": PENDING_BETTER_VERSION_COPY})
            continue
        # THE POST-LOCK STYLE LANE IS PARKED (founder 2026-08-11: "for now
        # we will dump the colours and styling interventions"). That
        # parenthetical retracts the lane he had asked for one message
        # earlier — bold/colour offers on ALREADY-LOCKED text — and nothing
        # wider: emphasis on OPEN text is an older, shipped lane and rides
        # the ordinary budget untouched, which is why this sits inside the
        # locked branch rather than above it.
        #
        # Refused rather than deleted through five files: "for now" is a
        # park, and the routing it would need back is worth more intact than
        # re-derived. One gate, one ruling, one line to reverse.
        if c.get("kind") == "bold":
            continue
        # R1, THIRD generation (founder 2026-08-11, the deck respec): a
        # locked part takes the STYLE LANE — bold/colour proposals that
        # touch presentation, never the words ("this next suggestion is
        # less intrusive and needs to keep the text coherent"). Tagged,
        # not merged: the caller routes tagged rows OUTSIDE the ≤3 budget
        # (ruling 4: "Outside") and the FE surfaces them only inside the
        # chunk's modal — locked text is never re-underlined on the page.
        # Composition on locked text stays dropped: L1's mechanical
        # enforcement is unchanged — nothing rewrites committed words.
        # R1, FOURTH generation (founder 2026-08-11, later the same day):
        # "when the engine is locked in keep it there… but if something new
        # appears there keep iterating and showing the suggestions" — a
        # locked part now takes NEW COMPOSITION again, and the chunk
        # re-enters the review cycle: accept or discard, then lock again.
        #
        # This SUPERSEDES gen three's "composition on locked text stays
        # dropped". It does not touch L1, and the distinction is the whole
        # point: L1 forbids the machine REWRITING committed words, not the
        # speaker being OFFERED a better version of them and choosing. The
        # offer is still an offer; the lock is what the student re-applies.
        #
        # Nothing decided reaches here to be re-offered: a dismissed
        # proposal's row is deleted and an approved one is baked into the
        # document, so "new" is the only thing left.
        #
        # ADVICE COMES TOO (founder 2026-08-11, answering the question this
        # code asked): "advices are suggested always cause it is the feedback
        # — it just is next to the intervention in the text like cut off or
        # rewrite." Advice is not a lane of its own competing for the tap; it
        # is the note that rides BESIDE the cut or the rewrite. A locked part
        # that takes the rewrite and refuses its explanation would serve the
        # instruction without the reason.
        kept.append({**c, "reopens_locked": True})
    return kept


def suppress_style_where_feedback_waits(changes: Any, group_of: Any = None
                                        ) -> list:
    """THE ORDER OF THE TWO LANES (founder 2026-08-11).

    "The style intervention appears if it was locked in and no new feedback
    is queued" — style is what a chunk gets when it has nothing louder to
    say. A bold/colour proposal beside an unread rewrite competes with it for
    the same tap, and the rewrite is the one that changes what the speech
    SAYS; presentation is the finishing pass, not a parallel one.

    Suppressed, not dropped: the style row simply is not offered on this
    serve. It returns the moment the chunk has no content feedback waiting,
    which is exactly the "if no new feedback is queued" condition — no state
    to store, nothing to expire.

    Counted per GROUP (the slide/paragraph, same unit as the budget): a
    rewrite waiting on slide 2 must not silence the accent on slide 7.

    NO GROUPING ⇒ NO SUPPRESSION. Without the document there is no way to
    tell whether the rewrite and the accent are even on the same paragraph,
    and treating the whole take as one group would let a rewrite anywhere
    silence every accent everywhere — the same drop-never-guess rule the rest
    of this pipeline follows, pointed the safe way. Pure.
    """
    rows = [c for c in (changes or []) if isinstance(c, dict)]
    if not callable(group_of):
        return rows
    busy = {group_of(c) for c in rows if not c.get("style_lane")}
    return [c for c in rows
            if not c.get("style_lane") or group_of(c) not in busy]


def filter_by_window(changes: Any) -> list:
    """§F.4 (founder 2026-08-10) — the precision gate on ACCENT-class offers.

    The windows table assigns emphasis and rhetorical devices the intonation
    UNIT (~1.6 s, Chafe ~4.84 words); `ACCENT_WINDOW_MAX_WORDS` in
    ideal_text_block is that ceiling, shared with the ledger bake so the
    offer gate and the paint gate can never disagree. Rules:

      * bold / advice (the ACCENTUATION layer) with a quote beyond the
        window → dropped. Accepting one would paint sentences orange — the
        founder's exact complaint — and the bake would refuse it anyway.
      * a Confident Voice change passes REGARDLESS of size: it renders as a
        star badge at the span's end, never as a painted wash, so the window
        rule does not bind it (CONSTRUCT: the badge is the surface).
      * composition (replace / insert) passes untouched — block upgrades are
        legitimately block-sized, with their own UI.
      * a change with no quote cannot be measured → dropped, same
        never-guess rule as an unclassified kind.
    """
    from services.ideal_text_block import within_accent_window
    from services.ideal_text_parts import ACCENTUATION, layer_of_kind
    kept: list = []
    for c in (changes or []):
        if not isinstance(c, dict):
            continue
        if layer_of_kind(c.get("kind")) != ACCENTUATION:
            kept.append(c)
            continue
        if c.get("trigger") == CONFIDENT_VOICE_TRIGGER:
            kept.append(c)
            continue
        if within_accent_window(c.get("quote")):
            kept.append(c)
    return kept


def select(changes: Any, *, user_id: str = "", session_id: str = "",
           parts: Any = None, decided_count: int = 0,
           served_text: Any = None, spent_by_paragraph: Any = None) -> dict:
    """Run every change through the manager and return the survivors.

    Returns ``{"changes": [...], "result": <arbitrate() dict>|None}``. The
    changes come back in DOCUMENT ORDER — arbitrate() returns them ranked, and
    the FE renders the document top to bottom, so serving the engine's order
    would scatter the marks.

    `decided_count` is the take's SPENT budget (founder 2026-08-10): the
    number of served interventions the student has already decided on this
    take. It rides into arbitrate() as `budget_spent`, so the ≤3 is
    cumulative per take — the set on screen is chosen once, waits whole, and
    only shrinks as decisions land. Selection is deterministic (document
    order, uniform priorities, a per-(user, session) stable roll), so the
    undecided members persist across refetches rather than being redrawn.

    The input is sorted by (start, end) BEFORE arbitration on purpose.
    `independent_subset` is a stable greedy sort by priority, and with today's
    uniform priorities that makes input order the tie-break; sorting first
    reproduces exactly the earliest-then-narrowest preference `drop_overlaps`
    used to apply, so removing that call changes no behaviour it was
    responsible for. Collision resolution itself now belongs to the engine,
    which resolves transitive chains correctly (A/B/C where A and C do not
    overlap) where a linear sweep drops one span too many.

    Never raises: on any failure it returns NOTHING rather than the unbudgeted
    list. A gatekeeper that fails open is not a gatekeeper.
    """
    try:
        rows = [c for c in (changes or []) if isinstance(c, dict)]
        # THE FUNNEL (founder 2026-08-11). Eight gates stand between a stored
        # suggestion and the screen and every one of them drops SILENTLY, so
        # "five rows in the table, one note on the page" was a night of
        # guessing to narrow down. arbitrate() has computed the reason for
        # every rejection all along and the caller threw it away; this
        # records the count at each stage and logs the whole shape once.
        # Server-side only — AC-9 is about what a USER sees, and nothing here
        # goes near a payload.
        funnel: dict = {"in": len(rows)}
        if not rows:
            return {"changes": [], "result": None, "controls": False,
                    "funnel": funnel}
        # THE COUNTING UNIT (founder 2026-08-11: "do it per slide up to 2").
        # One paragraph per slide, and the paragraph is the chunk the student
        # decides on — so the mix caps below and the budget further down are
        # counted in the same unit the student acts in. None without the
        # document: every rule falls back to document-wide, unchanged.
        _para_of = None
        if isinstance(served_text, str) and served_text:
            from services.intervention_spend import paragraph_index_at

            def _para_of(c: dict) -> int:   # noqa: F811 — the guarded form
                return paragraph_index_at(
                    served_text, (c.get("span") or {}).get("start", 0))
        # R1 — the layer filter runs HERE, before anything is scored or
        # budgeted. See filter_by_layer for why the order is the rule.
        rows = filter_by_layer(rows, parts)
        funnel["after_layer"] = len(rows)
        # THE STYLE LANE (R1 gen-3, founder 2026-08-11) splits off before
        # the budget machinery: style rows ride OUTSIDE the ≤3 (ruling 4),
        # so they see neither the type caps nor arbitrate — but they DO
        # keep the §F.4 accent window (a style accent past the intonation
        # ceiling would paint sentences on accept, lock or no lock), and
        # they take no arm assignment: the experiment measures the
        # budgeted serve, and free-lane rows would distort its record.
        # CONTENT FIRST, STYLE WHEN THERE IS NOTHING LOUDER (founder
        # 2026-08-11). Runs before the split so the decision sees both lanes
        # at once, on the same paragraph key the budget is counted in.
        rows = suppress_style_where_feedback_waits(rows, group_of=_para_of)
        style_rows = [c for c in rows if c.get("style_lane")]
        rows = [c for c in rows if not c.get("style_lane")]
        style_rows = filter_by_window(style_rows)
        for c in style_rows:
            c["visual"] = visual_of(c)
        style_rows.sort(key=lambda c: (
            (c.get("span") or {}).get("start", 0),
            (c.get("span") or {}).get("end", 0)))
        _style = {"style_changes": style_rows} if style_rows else {}
        funnel["style_lane"] = len(style_rows)
        if not rows:
            # THE EMPTY SERVE is the case the funnel exists for: nothing on
            # screen, and this is the only witness to which gate did it.
            logger.info("intervention funnel session=%s %s (empty after the "
                        "layer filter)", session_id, funnel)
            return {"changes": [], "result": None, "controls": False,
                    "funnel": funnel, **_style}
        # §F.4 — the emphasis WINDOW gate, same before-budget reasoning: an
        # accent-class offer whose quote exceeds the intonation-unit ceiling
        # would paint sentences on accept (the bake now refuses it), so a
        # budget slot spent on it is a slot spent on nothing. Composition
        # offers (replace/insert) pass untouched — a block upgrade is
        # legitimately block-sized and has its own UI; the window rule is
        # about PAINT, and composition paints a diff, not a wash.
        rows = filter_by_window(rows)
        funnel["after_window"] = len(rows)
        if not rows:
            return {"changes": [], "result": None, "controls": False,
                    "funnel": funnel, **_style}
        # Appendix C mix caps (founder GO 2026-08-10): cap the POOL per
        # C.2 type so one lane cannot monopolise the flat budget — see
        # filter_by_type_caps for why this runs before arbitration.
        rows = filter_by_type_caps(rows, group_of=_para_of)
        funnel["after_type_caps"] = len(rows)
        if not rows:
            return {"changes": [], "result": None, "controls": False,
                    "funnel": funnel, **_style}
        rows.sort(key=lambda c: (
            (c.get("span") or {}).get("start", 0),
            (c.get("span") or {}).get("end", 0)))

        candidates = to_candidates(rows)
        # to_candidates refuses zero-width and malformed spans — the one
        # stage whose loss is invisible in the row list itself.
        funnel["arbitrated"] = len(candidates)
        if not candidates:
            return {"changes": [], "result": None, "controls": False,
                    "funnel": funnel, **_style}

        controls = _controls_enabled()
        state = user_state(candidates)
        if controls and user_id:
            state = me.UserState(
                user_id=str(user_id),
                state_by_dimension=state.state_by_dimension,
                p_mastery=state.p_mastery,
                sessions_since_fired=state.sessions_since_fired)

        # THE EXPLORATION QUOTA, armed with the controls. `exploration_roll`
        # is DETERMINISTIC per (user, session) — never random.random, because
        # this surface is polled and a fresh draw per request would re-decide
        # the branch every few seconds, swapping the notes on screen while the
        # student watched. It returns None without a stable key, and arbitrate
        # then skips the branch entirely.
        _sid = str(session_id or "")
        # THE BUDGET IS COUNTED PER PARAGRAPH when the caller hands over the
        # served text (founder 2026-08-11: "do it per slide up to 2"). The
        # document carries one paragraph per slide and the paragraph IS the
        # chunk the student decides on, so this is the slide, the chunk and
        # the budget unit all at once. Without the text it falls back to the
        # flat per-take cap — unchanged behaviour, and the guests / callers
        # that have no document keep working.
        _grp = None
        _spent_g = None
        if _para_of is not None:
            _by_ref_para = {str(i): _para_of(row)
                            for i, row in enumerate(rows)}

            def _grp(c: Any) -> Any:   # noqa: F811 — the guarded form
                return _by_ref_para.get(c.ref, 0)

            _spent_g = dict(spent_by_paragraph or {})
        result = me.arbitrate(
            candidates, state,
            session_id=_sid if controls else "",
            roll=(me.exploration_roll(str(user_id or ""), _sid)
                  if controls else None),
            controls=controls,
            budget_spent=max(0, int(decided_count or 0)),
            group_of=_grp, spent_by_group=_spent_g)

        by_ref = {str(i): row for i, row in enumerate(rows)}
        kept: list = []
        for c in result.get("selected") or ():
            row = by_ref.get(c.ref)
            if row is not None:
                # The rendering registry stamps every SURVIVOR (SPEC §3):
                # Confident Voice = star, rewrites = underline, accents =
                # bold. Stamped here — after the budget, before the FE — so
                # one table governs every surface and the FE never derives a
                # visual from kind on its own. IN PLACE, not a copy: the
                # returned dicts must stay the caller's own objects (the
                # identity contract that keeps take_index/block_key/why_key
                # alive through this adapter).
                row["visual"] = visual_of(row)
                kept.append(row)
        kept.sort(key=lambda c: (c["span"]["start"], c["span"]["end"]))
        funnel["served"] = len(kept)
        # WHY the rest went, in the engine's own words. `rejected` has always
        # carried (dimension, reason) and nothing ever read it — so a pool
        # that emptied on the PPV floor and one that emptied on cooldown were
        # indistinguishable from the outside, which is how "why is there only
        # one note?" became unanswerable without a database session.
        why: dict = {}
        for _dim, reason in (result.get("rejected") or ()):
            why[reason] = why.get(reason, 0) + 1
        if result.get("budget_lost"):
            why["budget"] = len(result["budget_lost"])
        funnel["rejected"] = why
        logger.info("intervention funnel session=%s %s", session_id, funnel)
        # `controls` rides back so the caller knows whether an EXPERIMENT ran.
        # It gates arm persistence: `intervention_arms` is the experiment's
        # record, and rows written with the arms inert would carry the policy
        # (gamma, withhold_rate) as if an assignment had happened when none
        # did — a table that reads as populated while measuring nothing.
        return {"changes": kept, "result": result, "controls": controls,
                "funnel": funnel, **_style}
    except Exception as e:
        logger.warning("intervention selection failed: %s", e)
        return {"changes": [], "result": None, "controls": False}
