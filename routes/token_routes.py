"""Token balance API (token pricing Phase 1).

docs/PRICING-TOKENS-PLAN.md · docs/PROMPT-FE-token-pricing.md.

A self-contained blueprint with full paths baked in (same shape as
routes/journal.py and routes/dev_bugs.py) rather than more routes in the
15k-line v2_routes.py — this is a new, separable surface and it does not need to
share that module's blast radius.

  GET /v2/tokens/balance          balance, tier, renewal date, coach allowance
  GET /v2/tokens/prices           THE price list — the FE must not hardcode it
  GET /v2/tokens/recording-band   longest recording the balance covers
  GET /v2/tokens/history          paged ledger, newest first

All authed, all read-only. Nothing here charges: charging happens at the action
that is being paid for, so a balance read can never cost the user anything.

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
from services.token_prices import band_for_balance, public_price_list

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


@tokens_bp.route("/v2/tokens/checkout", methods=["POST"])
@require_auth
def tokens_checkout():
    """Open a Stripe Checkout Session for a recurring tier.

    Body: {"tier": "starter"|"pro"|"max", "success_url"?, "cancel_url"?}
    200 {checkout_url, checkout_session_id, tier} · 400 · 500 · 502 · 503

    This exists because a Payment Link cannot sell these tiers — see the module
    docstring in services/tier_checkout.py. In short: ``client_reference_id``
    never reaches the Subscription, so renewals would arrive unattributable and
    grant nothing from month two.

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
