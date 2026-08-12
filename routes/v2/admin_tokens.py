"""Admin-authenticated token top-up. Founder 2026-08-12.

  GET  /v2/admin/tokens/lookup?email=…   — one account's balance breakdown
  POST /v2/admin/tokens/grant            — add non-expiring tokens

THE TWIN OF /v2/internal/student-credits/*, AND ITS REPLACEMENT.

Those two routes take `CREDIT_ADMIN_PASSWORD` in the request BODY so a browser
form could send it, and they write the LEGACY `credits` column. Both halves of
that are now wrong:

  * the currency is tokens (founder 2026-08-12, the pricing pivot). Legacy
    credits were already honoured into `bonus_balance` by migration 0233 and
    are no longer the balance anything spends;
  * a shared password typed into a page is a second credential that exists
    only for this panel, and it grants money. The pipeline panel already
    settled this pattern: the backend grows @require_admin twins, the BFF
    forwards the caller's JWT, and there is no secret in the path at all — so
    there is nothing to leak rather than something well hidden.

GRANTS GO TO `bonus_balance`. See token_account.admin_grant: the monthly roll
SETS `token_balance`, so a top-up there has a silent 30-day expiry.

IDEMPOTENCY IS THE CALLER'S `ref_id`. The panel sends one per submitted form,
so a double-tap, a retried fetch or a refreshed tab cannot grant twice. A
request without one is refused rather than defaulted — a server-generated ref
would be unique per attempt, which is precisely the bug.

AC-9: a token balance is commerce, not a read on a speaker. Nothing here
touches quality signals, and none of it renders on a student surface.
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from routes.admin import require_admin
from services import token_account as ta
from services.db import db

logger = logging.getLogger(__name__)

admin_tokens_bp = Blueprint("admin_tokens", __name__)

# One operator, one panel, one order of magnitude of sanity. A fat-fingered
# extra zero on a grant is not recoverable from the UI (the correction is
# another grant), so the ceiling is here rather than in the browser where it
# would be advice rather than a rule.
MAX_GRANT = 10_000_000


def _no_store(payload, status: int = 200):
    """A cached balance is a wrong balance — and this panel exists to change
    the number the caller is looking at."""
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-store"
    return resp, status


def _resolve(email, user_id):
    """(user_id, error_payload, status). Email or id, id wins."""
    uid = (user_id or "").strip()
    if uid:
        return uid, None, 200
    mail = (email or "").strip()
    if not mail:
        return None, {"code": "INVALID_INPUT",
                      "error": "email or user_id is required"}, 400
    resolved = db.v2_find_user_id_by_email(mail)
    if not resolved:
        return None, {"code": "USER_NOT_FOUND",
                      "error": f"No user for email {mail}"}, 404
    return resolved, None, 200


def _account_payload(user_id: str) -> dict:
    """The breakdown, or a flag saying why there isn't one.

    THE SPLIT IS THE POINT of this panel: `balance` is what the user can spend,
    but only `monthly` expires at the period roll. An operator topping someone
    up needs to see which half they are adding to, or they will add to the
    wrong one — which is the entire failure mode this endpoint pair exists to
    prevent.
    """
    acct = ta.get_account(user_id)
    if not acct:
        return {"user_id": user_id, "available": False}
    return {
        "user_id": user_id,
        "available": True,
        "balance": acct.get("balance"),
        "monthly_balance": acct.get("monthly_balance"),
        "bonus_balance": acct.get("bonus_balance"),
        "tier": acct.get("tier"),
        "period_ends_at": acct.get("period_ends_at"),
        # Whether metering is live at all. Without it the panel cannot tell
        # "granted and spendable" from "granted into a system nothing reads
        # yet", and the operator would top up an account that is still on the
        # dark flag and conclude the grant failed.
        "pricing_enabled": ta.enabled(),
    }


@admin_tokens_bp.route("/v2/admin/tokens/lookup", methods=["GET"])
@require_admin
def admin_tokens_lookup():
    """One account's balance. 200 · 400 · 404 (403 from the decorator)."""
    user_id, err, status = _resolve(request.args.get("email"),
                                    request.args.get("user_id"))
    if err:
        return _no_store(err, status)
    return _no_store(_account_payload(user_id))


@admin_tokens_bp.route("/v2/admin/tokens/grant", methods=["POST"])
@require_admin
def admin_tokens_grant():
    """Add non-expiring tokens. Body: {email|user_id, tokens, ref_id}.

    `tokens` may be negative — a correction is a grant with a minus sign, and
    refusing them would leave a fat-fingered top-up permanent. The bucket
    floors at zero either way.
    """
    body = request.get_json(silent=True) or {}
    user_id, err, status = _resolve(body.get("email"), body.get("user_id"))
    if err:
        return _no_store(err, status)
    try:
        tokens = int(body.get("tokens"))
    except (TypeError, ValueError):
        return _no_store({"code": "INVALID_INPUT",
                          "error": "tokens must be an integer"}, 400)
    if tokens == 0:
        return _no_store({"code": "INVALID_INPUT",
                          "error": "tokens must not be zero"}, 400)
    if abs(tokens) > MAX_GRANT:
        return _no_store({"code": "INVALID_INPUT",
                          "error": f"tokens must be within ±{MAX_GRANT}"}, 400)
    ref_id = (body.get("ref_id") or "").strip()
    if not ref_id:
        # Refused, never defaulted: a server-side ref would be fresh on every
        # attempt, so the retry this guard exists for would sail through it.
        return _no_store({"code": "INVALID_INPUT",
                          "error": "ref_id is required (idempotency key)"},
                         400)
    acct = ta.admin_grant(user_id, tokens, ref_id=ref_id)
    if acct is None:
        return _no_store({"code": "GRANT_FAILED",
                          "error": "Could not apply the grant"}, 500)
    logger.info("admin_tokens: granted user=%s tokens=%s ref=%s balance=%s",
                user_id, tokens, ref_id, acct.get("balance"))
    return _no_store(_account_payload(user_id))
