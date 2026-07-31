"""Token balance API (token pricing Phase 1).

docs/PRICING-TOKENS-PLAN.md · docs/PROMPT-FE-token-pricing.md.

A self-contained blueprint with full paths baked in (same shape as
routes/journal.py and routes/dev_bugs.py) rather than more routes in the
15k-line v2_routes.py — this is a new, separable surface and it does not need to
share that module's blast radius.

  GET  /v2/tokens/balance         balance, tier, renewal date, coach allowance,
                                  and `plan` — is this a managed subscription?
  GET  /v2/tokens/prices          THE price list — the FE must not hardcode it
  GET  /v2/tokens/recording-band  longest recording the balance covers
  GET  /v2/tokens/arc/<arc_id>    which per-arc actions this arc already paid for
  POST /v2/tokens/checkout        start a subscription for a tier
  POST /v2/tokens/portal          cancel / switch / change card, via Stripe
  GET  /v2/tokens/history         paged ledger, newest first

The reads charge nothing: charging happens at the action that is being paid for,
so a balance read can never cost the user anything. The two POSTs move no tokens
either — they open a door at Stripe and return a URL; entitlements are granted
only by the subscription webhook.

THE PAIR THAT MAKES A PLAN CHANGEABLE. `plan.managed` says whether the tier is a
live Stripe subscription or just the default everyone starts on, and those need
different controls: `false` → upgrade (checkout), `true` → manage (portal).
Without it the FE can render a balance but cannot tell those two states apart,
which is what left the published tiers unsellable (FE handoff 2026-07-31).

FLAG-OFF BEHAVIOUR. With TOKEN_PRICING_ENABLED unset, every endpoint answers 200
with ``enabled: false`` and no numbers. It is deliberately not a 404: the FE
needs one probe that distinguishes "pricing is off, render no wallet UI at all"
from "the backend is broken", and a 404 cannot carry that difference.
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from auth import require_auth
from services import token_account as ta
from services.token_prices import (
    PER_ARC_ACTIONS, band_for_balance, price_of, public_price_list,
)

logger = logging.getLogger(__name__)

tokens_bp = Blueprint("tokens", __name__)


def _disabled_payload() -> dict:
    return {"enabled": False}


@tokens_bp.route("/v2/tokens/balance", methods=["GET"])
@require_auth
def tokens_balance():
    """Balance + tier + when it renews + the coach allowance.

    ``period_ends_at`` is not decoration. Every tier now renews monthly, so a
    balance shown without its renewal date reads as a countdown to being locked
    out rather than "wait or top up" (FE handoff §2)."""
    if not ta.enabled():
        return jsonify(_disabled_payload()), 200
    acct = ta.get_account(str(request.user_id))
    if not acct:
        # Unreadable account must not look like "you have nothing" — that would
        # push the FE into an empty-balance state and hide the record button.
        return jsonify({"enabled": True, "available": False}), 200
    return jsonify({"enabled": True, "available": True, **acct}), 200


@tokens_bp.route("/v2/tokens/prices", methods=["GET"])
@require_auth
def tokens_prices():
    """The price list, with its version.

    These numbers move once Phase 0's cost measurements land — that is the point
    of Phase 0 — so a hardcoded price in the FE becomes a lie silently."""
    if not ta.enabled():
        return jsonify(_disabled_payload()), 200
    return jsonify({"enabled": True, **public_price_list()}), 200


@tokens_bp.route("/v2/tokens/recording-band", methods=["GET"])
@require_auth
def tokens_recording_band():
    """The longest recording this balance covers.

    ADVISORY ONLY. It shapes the recorder UI; the upload endpoint accepts any
    duration and charges the band the audio actually lands in. Never reject a
    recording for length or balance — losing someone's take is worse than any
    billing inaccuracy (fence §6.1)."""
    if not ta.enabled():
        return jsonify({**_disabled_payload(), "can_record": True}), 200
    acct = ta.get_account(str(request.user_id))
    if not acct:
        # Fail OPEN: an unreadable balance lets them record.
        return jsonify({"enabled": True, "can_record": True,
                        "available": False}), 200
    band = band_for_balance(acct.get("balance"))
    if not band:
        return jsonify({"enabled": True, "can_record": False,
                        "balance": acct.get("balance"),
                        "period_ends_at": acct.get("period_ends_at")}), 200
    return jsonify({"enabled": True, "can_record": True,
                    "balance": acct.get("balance"),
                    "period_ends_at": acct.get("period_ends_at"),
                    **band}), 200


@tokens_bp.route("/v2/tokens/arc/<arc_id>", methods=["GET"])
@require_auth
def tokens_arc_state(arc_id):
    """What this arc's once-per-arc actions cost, and which are already paid.

    200 {enabled, arc_id, charged:{action: bool}, prices:{action: int}}

    THE POINT. Per-arc actions (`insights`, `game`, `moment_explanation`,
    `coach_review`) are charged with `ref_id=arc_id`, so the first open costs
    the price and every re-open is free. A control labelled with a static price
    would therefore be right exactly once and wrong forever after — and a stale
    price on a button is worse than no price at all, because people act on it
    and it discourages re-reading something they have already paid for.

    So the FE needs the answer BEFORE it renders the control, and it cannot get
    it from the action's own endpoint: `/explore/arc/<id>/feedback` IS the
    charge, so by the time that response exists the money is spent and the
    answer is always "yes".

    This read charges nothing, which is what makes it usable as a pre-render
    check. Scoped to the caller, so an arc they do not own returns all-false
    rather than revealing anything.
    """
    if not ta.enabled():
        return jsonify(_disabled_payload()), 200
    charged = ta.charged_actions_for_ref(str(request.user_id), str(arc_id))
    return jsonify({
        "enabled": True,
        "arc_id": str(arc_id),
        "charged": {a: (a in charged) for a in PER_ARC_ACTIONS},
        "prices": {a: price_of(a) for a in PER_ARC_ACTIONS},
    }), 200


@tokens_bp.route("/v2/tokens/checkout", methods=["POST"])
@require_auth
def tokens_checkout():
    """Open a Stripe Checkout Session for a recurring tier.

    Body: {"tier": "starter"|"pro"|"max", "success_url"?, "cancel_url"?}
    200 {checkout_url, checkout_session_id, tier} · 400 · 409 · 500 · 502 · 503

    This exists because a Payment Link cannot sell these tiers — see the module
    docstring in services/tier_checkout.py. In short: ``client_reference_id``
    never reaches the Subscription, so renewals would arrive unattributable and
    grant nothing from month two.

    409 comes in two flavours and they need different copy:
      ``ALREADY_ON_TIER``  — they are already on it; say so calmly, do nothing.
      ``MANAGE_EXISTING``  — they have a DIFFERENT live subscription. Send them
                             to POST /v2/tokens/portal, which SWITCHES the
                             existing one. Buying through here instead would
                             leave them paying for two plans at once.

    Deliberately NOT gated on TOKEN_PRICING_ENABLED. The flag controls whether
    we CHARGE for actions; it must not stop someone paying us. A subscription
    bought while the flag is off still sets the tier and grants tokens — they
    simply are not spent on anything yet, which is the correct behaviour for a
    soft launch where billing goes live before metering does.
    """
    body = request.get_json(silent=True) or {}
    from config import Config as _config
    from services.tier_checkout import create_tier_checkout_session
    result = create_tier_checkout_session(
        user_id=str(request.user_id),
        tier=(body.get("tier") or ""),
        app_config=_config,
        success_url=(body.get("success_url") or None),
        cancel_url=(body.get("cancel_url") or None),
    )
    return jsonify(result.payload), result.http_status


@tokens_bp.route("/v2/tokens/portal", methods=["POST"])
@require_auth
def tokens_portal():
    """Open the Stripe billing portal: cancel, switch tier, change card.

    Body: {"return_url"?}
    200 {portal_url} · 400 · 404 · 502 · 503

    Render the button from ``plan.manage_available`` on /v2/tokens/balance and
    call this on the click — the URL is minted per click because portal sessions
    expire, and because putting a Stripe round-trip inside the balance read
    would make a Stripe outage look like a missing balance.

    A 404 ``NO_SUBSCRIPTION`` is not an error state to show: it means there is
    nothing to manage, so render upgrade instead.

    Whatever they do in there returns as a subscription webhook and is applied
    by services/stripe_subscription_tiers.py. Nothing is decided here.

    Not gated on TOKEN_PRICING_ENABLED, for the same reason as checkout: the
    flag governs whether we CHARGE for actions, and it must never be the reason
    someone cannot cancel.
    """
    body = request.get_json(silent=True) or {}
    from config import Config as _config
    from services.tier_checkout import create_billing_portal_session
    result = create_billing_portal_session(
        user_id=str(request.user_id),
        app_config=_config,
        return_url=(body.get("return_url") or None),
    )
    return jsonify(result.payload), result.http_status


@tokens_bp.route("/v2/tokens/history", methods=["GET"])
@require_auth
def tokens_history():
    """Ledger rows, newest first. ``before_id`` pages backwards."""
    if not ta.enabled():
        return jsonify({**_disabled_payload(), "entries": []}), 200
    try:
        limit = int(request.args.get("limit") or 50)
    except (TypeError, ValueError):
        limit = 50
    before_id = request.args.get("before_id")
    try:
        before_id = int(before_id) if before_id else None
    except (TypeError, ValueError):
        before_id = None
    rows = ta.history(str(request.user_id), limit=limit, before_id=before_id)
    return jsonify({"enabled": True, "entries": rows,
                    "next_before_id": rows[-1]["id"] if rows else None}), 200
