"""willab — the token price list and tier grants. THE single source of truth.

docs/PRICING-TOKENS-PLAN.md §2/§3. Founder-approved 2026-07-27/28.

WHY THIS IS A FLAT TABLE AND NOT A CALCULATION
----------------------------------------------
Every price here is a fixed published number. None of them is derived at charge
time from what the call actually cost us — that is fence §6.2, and it is not a
style preference: a price that moves with the user's own output is a quality
score wearing a billing costume, which AC-9 forbids outright.

``services/llm_usage.py`` measures what we pay OpenAI. It informs these numbers
BETWEEN releases, by a human reading a report and editing this file. It is never
read at charge time. Nothing in this module imports it, and a test enforces that.

Duration BANDS are the one legitimate variability: duration is not quality, the
bands are coarse, and the band is shown before the user records — never computed
after from how it went.

REPRICING
---------
Bump ``PRICE_VERSION`` in the same commit as any number below. Every ledger row
records the version that produced it, so historical charges keep meaning what
they meant and a repricing is auditable instead of retroactive.
"""
from __future__ import annotations

from typing import Optional


PRICE_VERSION = "2026-07-28-v1"
"""Bump on ANY change to the numbers in this file."""


# ── Tiers ────────────────────────────────────────────────────────────
#
# Founder 2026-07-28: every tier renews monthly, free included, and NOTHING
# rolls over. `tokens` is SET at each period roll, never added to.
#
# `coach_reviews` is a SECOND, independent limit. It deliberately does not
# follow the 1×/6×/30× token ladder: at ~15 minutes of the founder's own time
# per review, scaling it 30× would sell his calendar at $13/hour. The cap
# protects the calendar, not the margin (plan §5.1). The tighter of the two
# limits binds — a Max user can hold 1.4M tokens and still be out of reviews.

TIERS: dict[str, dict] = {
    "free":    {"tokens":    12_000, "coach_reviews":  0, "usd": 0},
    "starter": {"tokens":    50_000, "coach_reviews":  1, "usd": 5},
    "pro":     {"tokens":   300_000, "coach_reviews":  6, "usd": 25},
    "max":     {"tokens": 1_500_000, "coach_reviews": 10, "usd": 100},
}

DEFAULT_TIER = "free"


def normalize_tier(tier: Optional[str]) -> str:
    """Unknown or NULL reads as free. Never raises — a bad tier string must
    degrade to the smallest grant, never to an exception on a balance read."""
    t = (tier or "").strip().lower()
    return t if t in TIERS else DEFAULT_TIER


def grant_for(tier: Optional[str]) -> int:
    """Tokens granted at each period roll. SET, not added — no rollover."""
    return int(TIERS[normalize_tier(tier)]["tokens"])


def coach_reviews_for(tier: Optional[str]) -> int:
    """Human-coach reviews allowed per period."""
    return int(TIERS[normalize_tier(tier)]["coach_reviews"])


# ── Action prices ────────────────────────────────────────────────────
#
# Machine prices are measured cost × 7 (plan §2). The unlock-style actions
# (moment_explanation, game, insights) have NO marginal cost at all — their
# content is generated during the take — so ×7 cannot apply and they are
# value-priced. coach_review is priced against the founder's calendar.

PRICES: dict[str, int] = {
    # Recording. Bands by duration; chosen BEFORE recording, never after.
    "take_short":         1_000,   # < 2 min — 68% of all takes ever recorded
    "take_medium":        3_000,   # 2–6 min
    "take_long":          6_000,   # 6–15 min
    "reread":             1_500,   # paired re-read; never counts as a take
    # Assembly + overlays
    "assembly":             500,
    "say_it_stronger":      500,
    "piece_retranscribe":    300,
    # Deliverables (zero marginal cost — value-priced)
    "moment_explanation": 2_500,
    "game":               1_500,
    "insights":           1_000,
    # Conversation
    "chat":                 150,
    "life_panel":           800,
    # Human
    "coach_review":      35_000,   # verify pass + key-moment comment, ONE sitting
}

COACH_ACTIONS = frozenset({"coach_review"})
"""Actions that also consume the per-period coach-review allowance. Kept as a
set rather than a flag on the price so the two limits stay visibly separate."""


# ── Recording bands ──────────────────────────────────────────────────
#
# (max_seconds, action). Nothing above 15 min is published: production data
# (plan §8.1) says the longest take ever recorded is 5.3 minutes and ZERO have
# exceeded 6, so the 6–15 band is already generous headroom. Longer uploads are
# still ACCEPTED and charged at the top band — we never drop audio (fence §6.1).

BANDS: tuple[tuple[int, str], ...] = (
    (120,  "take_short"),
    (360,  "take_medium"),
    (900,  "take_long"),
)

TOP_BAND_ACTION = "take_long"


def price_of(action: str) -> int:
    """Tokens for one action. Unknown action = 0 (free), never an exception.

    Charging zero for something we forgot to price loses a little revenue.
    Raising here would break the user's action instead, on the live loop, over
    a billing detail — strictly the worse failure."""
    return int(PRICES.get((action or "").strip(), 0))


def band_for_seconds(seconds: Optional[float]) -> str:
    """Which recording band an actual duration falls into.

    Anything past the top band charges the top band rather than being rejected:
    losing a user's take is worse than under-charging for it."""
    try:
        s = float(seconds or 0)
    except (TypeError, ValueError):
        s = 0.0
    for limit, action in BANDS:
        if s <= limit:
            return action
    return TOP_BAND_ACTION


def band_for_balance(balance: Optional[int]) -> Optional[dict]:
    """The longest recording a balance can pay for, for the record-start gate.

    Returns {max_seconds, action, price} or None when even the shortest band is
    unaffordable. ADVISORY ONLY — it shapes the recorder UI. The upload endpoint
    must accept any duration regardless (fence §6.1)."""
    try:
        bal = int(balance or 0)
    except (TypeError, ValueError):
        bal = 0
    best = None
    for limit, action in BANDS:
        if bal >= price_of(action):
            best = {"max_seconds": limit, "action": action,
                    "price": price_of(action)}
    return best


def public_price_list() -> dict:
    """What GET /v2/tokens/prices serves. The FE must read prices from here
    rather than hardcoding them — these numbers change once Phase 0's
    measurements land, which is the entire point of Phase 0."""
    return {
        "price_version": PRICE_VERSION,
        "actions": dict(PRICES),
        "bands": [{"max_seconds": s, "action": a, "price": price_of(a)}
                  for s, a in BANDS],
        "tiers": {
            name: {"tokens_per_month": t["tokens"],
                   "coach_reviews_per_month": t["coach_reviews"],
                   "usd_per_month": t["usd"]}
            for name, t in TIERS.items()
        },
    }
