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


PRICE_VERSION = "2026-10-26-v3.1"
"""Bump on ANY change to the numbers in this file."""


# ── Tiers (v3 — founder 2026-08-14) ──────────────────────────────────
#
# Founder 2026-07-28: every tier renews monthly, free included, and NOTHING
# rolls over. `tokens` is SET at each period roll, never added to.
#
# WHAT v3 CHANGED, AND WHY. The old ladder scaled BOTH limits together
# (1×/6×/30×), which sold the founder's calendar at ~$13/hour at the top:
# 30 reviews × ~15 min = 7.5 hours for $100. v3 separates the two axes —
# TOKENS scale with machine use, PRICE scales with coach reviews — because
# they are different goods. Tokens meter machine work, which is cheap and
# elastic; a coach review is a human sitting, which is neither.
#
# `coach_reviews` is a SECOND, independent limit and the tighter of the two
# binds: an Intensive user can hold plenty of tokens and still be out of
# reviews.

TIERS: dict[str, dict] = {
    # ── SOLD ──
    # Founder 2026-10-14: plans differ by TOKENS ONLY. A coach review is
    # free since N205 item 4 (the coach answers every Take), and no plan
    # carries review slots any more. Shown as Starter / Plus / Pro.
    "free":      {"tokens":    12_000, "coach_reviews": 0, "usd":  0},
    "practice":  {"tokens":   150_000, "coach_reviews": 0, "usd": 12},
    "coaching":  {"tokens":   550_000, "coach_reviews": 0, "usd": 39},
    "intensive": {"tokens": 1_400_000, "coach_reviews": 0, "usd": 89},

    # ── RETIRED, NOT SOLD (founder 2026-08-14: the grandfathering SCHEME is
    # dropped — no aliases, no legacy cards, no special entitlement rules).
    #
    # These three entries remain for ONE reason: an existing subscription's
    # renewal webhook resolves its Stripe price to a tier key, and a key that
    # resolves to nothing grants nothing. Deleting them would charge a live
    # subscriber and hand them a zero balance. That is not grandfathering,
    # it is not breaking live billing.
    #
    # They are absent from SOLD_TIERS, so they cannot be bought, do not
    # appear on the sales sheet, and render no card. If there are no legacy
    # subscribers left, these three lines can simply be deleted.
    "starter": {"tokens":    50_000, "coach_reviews":  1, "usd":   5},
    "pro":     {"tokens":   300_000, "coach_reviews":  6, "usd":  25},
    "max":     {"tokens": 1_500_000, "coach_reviews": 30, "usd": 100},

    # `coached` — the SPELLING this tier shipped under before 2026-08-15, kept
    # resolvable for exactly the reason above. The founder's word is
    # "coaching" ("in my product I have called it coaching") and the frontend
    # already enforces that spelling, but a Railway STRIPE_PRICE_TIER_JSON or
    # a stored subscription row may still say `coached` at the moment this
    # deploys. An unresolvable key grants NOTHING to someone who has paid, so
    # both spellings resolve and only `coaching` is sold. Delete this line
    # once every price map and tier row reads `coaching`.
    "coached": {"tokens": 150_000, "coach_reviews": 3, "usd": 39},
}

SOLD_TIERS: tuple[str, ...] = ("free", "practice", "coaching", "intensive")
"""What may be BOUGHT and what the sales sheet shows.

Separate from TIERS on purpose: TIERS answers "what does this key grant"
(every key that can arrive from a webhook, retired ones included), while this
answers "what is for sale today". Checkout validates against this; a retired
key is rejected, because nothing may create a NEW subscription on a tier that
is no longer sold."""

DEFAULT_TIER = "free"


# ── Pricing v4 (founder 2026-10-26, N198): everything in tokens ──────
#
# Off until Terms 3.7 describe it (N198 item 7): PRICING_V4_ENABLED=1 on every
# Railway service switches it on, and off again just as safely, because
# NOTHING STORED CHANGES. A token as the speaker sees it is DISPLAY_UNIT_V4 of
# the stored units every balance, price and ledger row already holds: a short
# Take is still 1,000 stored and reads 10, the free grant is still 12,000 and
# reads 120. N198's "divided by 100" is this display unit, not a migration.
#
# What v4 does change: the three sold packages (each now holds at least one
# call with the coach), chat (1 shown token, it would be 1.5), the coach's
# time (200 shown tokens a minute, paid at booking), and the review, which is
# no longer charged when the coach sends it (N198 item 5: only when asked).

PRICE_VERSION_V4 = "2026-10-26-v4"
DISPLAY_UNIT_V4 = 100
"""Stored units in one token as shown, while v4 is on."""

TIERS_V4: dict[str, dict] = {
    # Shown as Starter / Plus / Pro, as before; the keys stay as Stripe and
    # existing ledger rows know them.
    "practice":  {"tokens":   390_000, "coach_reviews": 0, "usd":  39},
    "coaching":  {"tokens": 1_100_000, "coach_reviews": 0, "usd":  99},
    "intensive": {"tokens": 1_800_000, "coach_reviews": 0, "usd": 149},
}

COACH_MINUTE_V4 = 20_000
"""The coach's published rate, stored units a minute (200 shown, $2; N187)."""


def v4_enabled() -> bool:
    import os
    return (os.getenv("PRICING_V4_ENABLED") or "0").strip().lower() in ("1", "true", "yes", "on")


def price_version() -> str:
    """The version a ledger row records: v4's while it is on."""
    return PRICE_VERSION_V4 if v4_enabled() else PRICE_VERSION


def display_unit() -> int:
    return DISPLAY_UNIT_V4 if v4_enabled() else 1


def shown(units: Optional[int]) -> Optional[int]:
    """Stored units as the speaker sees them: whole tokens, toward zero, so a
    balance is never shown larger than it is. Every number the app or the
    admin reads passes through here (routes/token_routes.py and the admin
    endpoints); nothing else needs to know the unit."""
    if units is None:
        return None
    n, unit = int(units), display_unit()
    return n // unit if n >= 0 else -((-n) // unit)


def stored(tokens: int) -> int:
    """Tokens as typed (the admin's grant) in stored units."""
    return int(tokens) * display_unit()


def tier_row(tier: Optional[str]) -> dict:
    """One tier's grant and price, v4's for the sold packages while it is on."""
    key = normalize_tier(tier)
    if v4_enabled() and key in TIERS_V4:
        return TIERS_V4[key]
    return TIERS[key]


def normalize_tier(tier: Optional[str]) -> str:
    """Unknown or NULL reads as free. Never raises — a bad tier string must
    degrade to the smallest grant, never to an exception on a balance read."""
    t = (tier or "").strip().lower()
    return t if t in TIERS else DEFAULT_TIER


def grant_for(tier: Optional[str]) -> int:
    """Tokens granted at each period roll. SET, not added — no rollover."""
    return int(tier_row(tier)["tokens"])


def coach_reviews_for(tier: Optional[str]) -> int:
    """Human-coach reviews allowed per period."""
    return int(tier_row(tier)["coach_reviews"])


# ── Action prices ────────────────────────────────────────────────────
#
# Machine prices are measured cost × 7 (plan §2). The unlock-style actions
# (moment_explanation, insights) have NO marginal cost at all — their
# content is generated during the take — so ×7 cannot apply and they are
# value-priced.
#
# EVERY KEY IN HERE IS CHARGED SOMEWHERE (audit 2026-08-14). Five keys used
# to sit in this table with no live charge call site at all — `assembly`,
# `say_it_stronger`, `piece_retranscribe`, `life_panel` and `coach_review` —
# and the wallet rendered every one of them in its "what things cost" list.
# A published price for something that never bills is a lie in the one place
# a user checks before acting, so they are gone. `assembly` fires a real
# (~$0.0007) model call after each spoken take; its cost is carried by the
# take price, which already prices at ×7.
#
# If an action is added back here, it must be charged. test_token_pricing
# pins that direction: a price with no call site fails the suite.

PRICES: dict[str, int] = {
    # Recording. Bands by duration; chosen BEFORE recording, never after.
    "take_short":         1_000,   # < 2 min — 68% of all takes ever recorded
    "take_medium":        3_000,   # 2–6 min
    "take_long":          6_000,   # 6–15 min
    "reread":             1_500,   # paired re-read; never counts as a take
    # Deliverables (zero marginal cost — value-priced)
    "moment_explanation": 2_500,
    "insights":           1_000,
    # Conversation
    "chat":                 150,
    # No coach review here: the coach answers every Take and nobody pays for
    # it (N205 item 4). It cost 35,000 from 2026-10-14 to 2026-10-26; those
    # ledger rows keep their price under the version that charged them.
}

PRICES_V4: dict[str, int] = {
    **PRICES,
    "chat": 100,
    # The coach's time, paid in tokens at booking (N198 item 4): one stored
    # unit per hundredth of a cent, so a booking's own price in cents times
    # this is its charge. A link's or a person's own price counts the same.
    "coach_time": 100,
}
"""v4's price list. Like v3's it has no coach review: the coach answers every
Take and nobody pays for it (N205)."""


def prices() -> dict[str, int]:
    return PRICES_V4 if v4_enabled() else PRICES


PER_ARC_ACTIONS: tuple[str, ...] = (
    "insights", "moment_explanation",
)
"""Actions charged ONCE PER ARC (``ref_id=arc_id``), so every re-open is free.

This tuple exists for the FE, and the reason is not cosmetic. A static
"1,000 tokens" label on a control that has already been paid for is *wrong* —
right the first time and wrong forever after — and a stale price on a button is
worse than no price, because people act on it and it discourages re-reading
something they already own. So the FE needs to know, BEFORE it renders the
control, whether this arc has already been charged. That is what
``GET /v2/tokens/arc/<arc_id>`` answers.

Keep this in step with every ``charge(..., ref_id=arc_id)`` call site — pinned
by test_token_arc_charged.py, which greps the routes for arc-keyed charges and
fails if one is missing here."""


# ── Legacy credit conversion (founder-approved 2026-08-01) ───────────
#
# Credits are retired; tokens are the only currency. Real users still hold
# balances that now buy nothing, so they are honoured ONCE as non-expiring
# bonus tokens. Two numbers decide it, and both are historical facts rather
# than tunables — changing either retroactively rewrites what somebody was
# already paid.
#
# THE RATE comes from this product's own price list, not from a guess. An arc
# unlock cost ARC_UNLOCK_CREDITS = 25 credits, and its historical deliverables
# priced in tokens come to 40,000:
#
#     insights 1,000 + retired deliverable 1,500 + moment_explanation 2,500
#                    + coach_review 35,000  =  40,000  ÷ 25  =  1,600
#
# The 400/credit figure originally written into PRICING-TOKENS-PLAN §4 was ~4×
# too harsh against that arithmetic — it would have written off three quarters
# of what people paid, at a $1-per-credit peg they were sold on.

LEGACY_CREDIT_TOKENS = 1_600
"""Tokens honoured per legacy credit. Arc-equivalence — see above."""

LEGACY_CREDIT_FREE_FLOOR = 25
"""Credits every account already held for free, and which are NOT converted.

`WILLAB_FREE_CREDIT_GRANT` seeded 25 to every new user, and the 2026-07-13
testing bump lifted every existing user to at least 25 — so a flat conversion
would hand every account that ever signed up 40,000 non-expiring tokens (3.3×
the entire free monthly tier) whether or not it ever paid anything. Nothing in
the schema can tell a purchased credit from a granted one: the
`stripe_checkout_credit_grants` table stores only a checkout_session_id, with
no user and no amount. So the floor is the only available separator, and it is
the honest one — the free 25 already delivered its value as the free tier.

Deliberately a literal here rather than a read of
`config.WILLAB_FREE_CREDIT_GRANT`: that value is env-tunable and may move, and
if it did, a re-run would silently convert a different amount than the first
run did."""


def legacy_credit_tokens(credits: Optional[int]) -> int:
    """Tokens owed for a legacy credit balance. Never negative.

    Mirrors the SQL in migrations/add_legacy_credit_conversion.sql exactly; a
    test asserts the two agree, because a drift between them would pay a
    different amount than the ledger row claims."""
    try:
        c = int(credits or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, c - LEGACY_CREDIT_FREE_FLOOR) * LEGACY_CREDIT_TOKENS


COACH_ACTIONS: frozenset[str] = frozenset()
"""Actions that consume the per-period coach-review allowance. EMPTY since
2026-10-14: a coach review was paid in tokens instead, and since N205 it costs
nothing, so nothing spends review slots. Kept so purchased review credits and the RPC's
coach branch stay readable until they are retired.

⚠️ THE MEMBER CHANGED IN v3 (founder 2026-08-14), and it is the fix for a
meter that was dead in production. The only member used to be `coach_review`
— a key NOTHING ever charged. So every part of the machinery below it (the
CAS'd counter, the atomic RPC's coach branch, the per-tier allowance, the
"protects the founder's calendar" fence) ran exactly zero times, while the
key that DID fire at publish, `coach_feedback`, sat deliberately outside this
set and billed tokens instead.

The result was a tier selling "3 coach reviews" against a counter no code
path could move. v3 prices the ladder ON coach reviews, so the meter has to
be real: delivery now consumes a slot, and tokens are left to meter machine
work."""


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
    return int(prices().get((action or "").strip(), 0))


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
    rather than hardcoding them — that is what makes a repricing a config
    change instead of a deploy.

    THE SALES SHEET, NOT THE TIER UNIVERSE. Only SOLD_TIERS ship here, so a
    retired tier renders no card and cannot be bought. A legacy subscriber's
    own tier still comes back on /v2/tokens/balance, which means `balance.tier`
    can legitimately name a key that appears in no card — the FE treats
    "matches nothing" as correct rather than as a bug."""
    return {
        "price_version": price_version(),
        # Every number here is already in tokens as shown; the unit is for
        # anyone reconciling with the ledger, which keeps stored units.
        "display_unit": display_unit(),
        "actions": {action: shown(price) for action, price in prices().items()
                    if action != "coach_time"},
        "bands": [{"max_seconds": s, "action": a, "price": shown(price_of(a))}
                  for s, a in BANDS],
        # The coach's time, a minute (v4 only; null before).
        "coach_minute": shown(COACH_MINUTE_V4) if v4_enabled() else None,
        "tiers": {
            name: {"tokens_per_month": shown(tier_row(name)["tokens"]),
                   "coach_reviews_per_month": tier_row(name)["coach_reviews"],
                   "usd_per_month": tier_row(name)["usd"]}
            for name in SOLD_TIERS
            if name in TIERS
        },
    }
