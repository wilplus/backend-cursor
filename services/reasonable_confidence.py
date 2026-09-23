"""Reasonable confidence — the reason layer that orders the voice layer.

FOUNDER, 2026-09-23, signing contract clause 24j:

    A moment qualifies when the words carried the point they were meant to
    carry, and the delivery sounded more assured than that speaker's own norm.

THE TWO HALVES ARE SEQUENCED, NEVER BLENDED, and that distinction is the whole
reason this module is small. A weighted sum of "sounded assured" and "made the
point" produces a number nobody can name: 0.4 could be fine delivery of nothing
or a mumbled bullseye. Under the CONSTRUCT fence a measured state must ask
exactly one thing, and a blend asks two at once — the defect that retired the
charisma construct on 2026-08-13.

Ordering does not have that problem. The tier decides WHICH candidates compete;
`voice_confidence` still decides which of them wins, and it still answers its
one question about delivery. Selection criteria are not measurements. That is
why `conf-q-v2` in services/state_ratings.py is untouched by this file and must
stay untouched: the rater is asked about the delivery of the clip they are
shown, which remains exactly true when a tier chose the clip.

NOTHING IS DELETED (24b holds). The bottom tier is never empty, so every valid
block still yields exactly one item on every Take. A moment that made no point
wins only when nothing in its block made one — the honest report rather than a
bypass. Two independent reasons this matters:

  * the exercise lane (24f) fires on the weakest item below the neutral band,
    so deleting the weak end would starve it;
  * the owner is only ever asked about what surfaces, so surfacing one end of
    the range would collect judgements from one end of the range — and the
    validation this all eventually rests on needs a clean spread across
    confident, middling and not.

NO NEW PARAMETER. There is no blend weight and no threshold. `on_slide_score`
in services/slide_alignment.py returns `max(_STRENGTH)` over the slide's
claims, and `_STRENGTH` is `{covered: 1.0, partial: 0.5, not: 0.0}` — so the
stored composite IS the verdict, already categorical. This module reads it back
as one of three names rather than cutting a continuum, which is why there is no
number here for anyone to tune.

DEGRADED VERDICTS ARE CARRIED, NOT HIDDEN. Every piece is scored against its
slide, but only the LLM-budget subset gets true entailment; the rest get
`_lexical_verdict`, which is word overlap. Word overlap is precisely the
"keyword matching" the product does not want to be, so a tier derived from it
is marked `degraded` and travels that way. It still orders — a coarse read
beats no read — but nothing downstream may mistake it for the measured kind.

AC-9. Tier names and the degraded flag are internal ordering facts and stop at
`_presentable` in services/take_feedback_policy_v3_service.py, beside
`candidate_score`. Not because they are harmless — `"not"` IS a verdict about
what the words did, which is exactly the kind of thing AC-9 bans — but because
that is the one place the visible copy of a row is built. The screen is drawn
from `bookmark_tier` and `why_key`, which are founder-signed keys.
"""
from __future__ import annotations

from typing import Any, Optional

#: The three verdicts, strongest first. The order IS the ranking.
TIERS: tuple[str, ...] = ("covered", "partial", "not")

#: Where a candidate with no slide read at all sorts: last, never excluded.
#: Excluding it could empty a block and break 24b; ranking it last means an
#: unmeasured moment can never beat a measured one, which was the point.
UNMEASURED_RANK = len(TIERS)


def enabled() -> bool:
    """Does the reason layer order the candidates yet?

    ``REASONABLE_CONFIDENCE_ENABLED``, default OFF. With it off, `ordering_rank`
    returns one constant for every candidate, so the existing ordering is
    byte-for-byte unchanged — the flag is a true rollback rather than a
    half one.

    Read through `Config`, not `os.getenv`: the CONFIG-FIRST rule is only
    checkable when there is one place the code reads from (audit Q-A5,
    tests/test_config_reads_fence.py). Imported inside the function because
    this module is imported from the policy's hot path and `config` pulls in
    the secret loader.
    """
    from config import Config

    return bool(Config.REASONABLE_CONFIDENCE_ENABLED)


def reason_tier(metrics: Any) -> tuple[Optional[str], bool]:
    """``(tier, degraded)`` for one piece, from its stored slide read.

    ``(None, False)`` when the piece carries no usable slide score — a slide
    with no text, a transcript too short to judge, or a piece the cutter could
    not map. That is an absence, never a zero: "we did not look" and "you said
    nothing of the point" are different facts and only one of them is a
    judgement.

    Pure. Reads ``metrics["slide_stickiness"]``, written by
    `services.recording_persistence` from `compute_piece_slide_scores`.
    """
    read = metrics.get("slide_stickiness") if isinstance(metrics, dict) else None
    if not isinstance(read, dict):
        return None, False
    composite = read.get("composite")
    if not isinstance(composite, (int, float)) or isinstance(composite, bool):
        return None, False
    degraded = bool(read.get("degraded"))
    value = float(composite)
    # The composite is `max(_STRENGTH)` over the slide's claims, so it arrives
    # as one of {1.0, 0.5, 0.0}. Compared with `>=` rather than `==` because a
    # rounded float is not worth trusting to the bit, and because a future
    # averaging change upstream should degrade to the nearest verdict rather
    # than fall through to "not".
    if value >= 1.0:
        return "covered", degraded
    if value >= 0.5:
        return "partial", degraded
    return "not", degraded


def tier_rank(tier: Optional[str]) -> int:
    """Sort key for a tier: lower wins. Unmeasured sorts last."""
    if tier in TIERS:
        return TIERS.index(tier)
    return UNMEASURED_RANK


def selection_summary(blocks: Any) -> str:
    """One line per Take: how the reason layer actually ranked it.

    WHY THIS EXISTS. 24j went live for everyone at once, which was defensible
    — it cannot crash, cannot empty a block, and rolls back with the flag —
    but the failure it CAN have is not loud. If the words read badly, nothing
    errors; the bookmarks are just quietly on worse moments, for everyone,
    looking entirely normal. A canary is one way to catch that and being able
    to SEE it is the other, and this is the cheap half of the second.

    Reads as: how often did the winner actually carry the slide's point, and
    how often was that verdict the coarse word-overlap kind rather than the
    measured one. A Take that reports `not=9 degraded=11` is telling you the
    gate is barely gating.

    AC-9. Counts and tier names only — no quote, no transcript, no score, and
    nothing here reaches a speaker. `_row_rejection` in
    take_feedback_policy_v3_service.py says the same of its own log values:
    the fence is about what a user sees, and a deploy log is not that.

    NEVER RAISES. It is called on the live path for the sake of a log line,
    and a log line is never worth a failed Take (live loop).
    """
    counts = dict.fromkeys(TIERS, 0)
    unmeasured = degraded = selected = 0
    try:
        for block in blocks or []:
            if not isinstance(block, dict):
                continue
            chosen_id = block.get("selected_candidate_id")
            if not chosen_id:
                continue
            row = next(
                (
                    candidate
                    for candidate in block.get("confidence_candidates") or []
                    if isinstance(candidate, dict)
                    and candidate.get("candidate_id") == chosen_id
                ),
                None,
            )
            if row is None:
                continue
            selected += 1
            tier = row.get("reason_tier")
            if tier in counts:
                counts[tier] += 1
            else:
                unmeasured += 1
            if row.get("reason_degraded"):
                degraded += 1
    except Exception:  # pragma: no cover - see NEVER RAISES above
        return "summary_unavailable"
    ordered = " ".join(f"{tier}={counts[tier]}" for tier in TIERS)
    return (
        f"enabled={int(enabled())} selected={selected} {ordered} "
        f"unmeasured={unmeasured} degraded={degraded}"
    )


def ordering_rank(candidate: Any) -> int:
    """The leading element of a candidate's sort key.

    One constant for everything while the flag is off, so the served order
    cannot move until it is deliberately turned on.
    """
    if not enabled():
        return 0
    tier = candidate.get("reason_tier") if isinstance(candidate, dict) else None
    return tier_rank(tier if isinstance(tier, str) else None)
