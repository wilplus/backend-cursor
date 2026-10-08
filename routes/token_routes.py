"""Token balance API (token pricing Phase 1).

docs/PRICING-TOKENS-PLAN.md · docs/PROMPT-FE-token-pricing.md.

A self-contained blueprint with full paths baked in (same shape as
routes/journal.py and routes/dev_bugs.py) rather than more routes in the
15k-line v2_routes.py — this is a new, separable surface and it does not need to
share that module's blast radius.

  GET  /v2/tokens/balance         balance, tier and coach allowance
  GET  /v2/tokens/prices          THE price list — the FE must not hardcode it
  GET  /v2/tokens/recording-band  longest recording the balance covers
  GET  /v2/tokens/arc/<arc_id>    which per-arc actions this arc already paid for
  POST /v2/tokens/checkout        buy a one-time token package
  POST /v2/tokens/portal          410 GONE: subscriptions are retired
  GET  /v2/tokens/history         paged ledger, newest first

The reads charge nothing: charging happens at the action that is being paid for,
so a balance read can never cost the user anything. The checkout moves no tokens
either — it opens a door at Stripe and returns a URL; the package is granted
only by the webhook (services/token_packages.py).

No subscriptions (contract 50; founder 2026-10-05, N48.3 Q13 A): the balance
no longer carries `plan`, and the billing portal answers 410.

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
    """Open a Stripe Checkout Session for a one-time token package.

    Body: {"tier": "practice"|"coaching"|"intensive", "success_url"?,
    "cancel_url"?}  ("package" is accepted for "tier".)
    200 {checkout_url, checkout_session_id, tier} · 400 · 502 · 503

    Contract §8 (founder 2026-10-05, "Packages"; N44): every purchase is a
    one-time package, never a subscription. Until that day this opened a
    monthly subscription while the purchase screen said "one-time purchase".
    The tokens are granted by the webhook, never here
    (services/token_packages.py).

    Deliberately NOT gated on TOKEN_PRICING_ENABLED. The flag controls whether
    we CHARGE for actions; it must not stop someone paying us.
    """
    body = request.get_json(silent=True) or {}
    from config import Config as _config
    from services.token_packages import create_package_checkout_session
    result = create_package_checkout_session(
        user_id=str(request.user_id),
        package=(body.get("package") or body.get("tier") or ""),
        app_config=_config,
        success_url=(body.get("success_url") or None),
        cancel_url=(body.get("cancel_url") or None),
    )
    return jsonify(result.payload), result.http_status


@tokens_bp.route("/v2/tokens/portal", methods=["POST"])
@require_auth
def tokens_portal():
    """RETIRED (founder 2026-10-05, N48.3 Q13 A; contract 50): there are no
    subscriptions to manage. Answers the house 410 rather than 404 because a
    frontend deployed before this one, or a page left open, still calls it on
    the click; the FE treats any refusal as "nothing to manage"."""
    return jsonify({"code": "GONE", "error": "Plans are retired; purchases "
                    "are one-time packages."}), 410


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
