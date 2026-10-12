"""
Server-to-server hooks (no student JWT).

- POST /v2/internal/student-credits/increment — X-Internal-Secret: INTERNAL_CREDITS_WEBHOOK_SECRET
- POST /v2/internal/stripe/webhook — Stripe-Signature (STRIPE_WEBHOOK_SECRET); one-time token packages only

REMOVED (founder 2026-10-12): POST /v2/internal/annotation-export and POST
/v2/internal/copilot-video/retrain. Both answered 410 (Phase 2 disabled) on
every request; they are now absent, so the paths answer 404.

RETIRED (founder 2026-08-03, stress-lane deletion): POST /v2/internal/stress-
model/train. It ran a `subprocess.run` train pipeline INSIDE the request
handler (30-minute timeout on a web dyno), defaulted `auto_promote` to true,
and promoted `runtime_config.stress_baseline_model_path`. The whole second
lane is gone and there is NO replacement trainer. The live owner answer at
POST /v2/user/snippets/<id>/confidence-review is Voice Album routing only and
must never train, calibrate, vote in quorum, evaluate or feed DPO. Do not
reintroduce a trainer in a request handler; nothing may promote a model
artifact without a quality gate AND a human decision.
"""
import logging

from flask import Blueprint, jsonify, request

from config import Config
from services.db import db

logger = logging.getLogger(__name__)
config = Config()

internal_webhooks_bp = Blueprint("internal_webhooks", __name__)


@internal_webhooks_bp.route("/v2/internal/student-credits/increment", methods=["POST"])
def internal_increment_student_credits():
    """
    Body JSON: { "user_id": "<uuid>", "delta": <int> }
    Header: X-Internal-Secret: <INTERNAL_CREDITS_WEBHOOK_SECRET>

    Example: $50 pack = 10 lessons at 5 credits each → delta: 10 (your product mapping lives in the caller).
    """
    secret = (getattr(config, "INTERNAL_CREDITS_WEBHOOK_SECRET", None) or "").strip()
    if not secret:
        return jsonify({"code": "DISABLED", "error": "INTERNAL_CREDITS_WEBHOOK_SECRET not configured"}), 503
    if (request.headers.get("X-Internal-Secret") or "").strip() != secret:
        return jsonify({"code": "UNAUTHORIZED", "error": "Invalid or missing X-Internal-Secret"}), 401

    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    delta = data.get("delta")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        return jsonify({"code": "INVALID_INPUT", "error": "user_id is required"}), 400
    try:
        d = int(delta)
    except (TypeError, ValueError):
        return jsonify({"code": "INVALID_INPUT", "error": "delta must be an integer"}), 400
    if d == 0:
        details = db.v2_get_student_details(user_id.strip()) or {}
        cur = details.get("credits")
        if cur is None:
            cur = int(getattr(config, "WILLAB_FREE_CREDIT_GRANT", 25) or 25)
        return jsonify({"status": "ok", "user_id": user_id.strip(), "credits": int(cur), "delta_applied": 0}), 200

    new_bal = db.v2_increment_student_credits(user_id.strip(), d)
    if new_bal is None:
        return jsonify({"code": "V2_ERROR", "error": "Could not update credits"}), 500
    logger.info("internal_increment_student_credits user_id=%s delta=%s new_credits=%s", user_id, d, new_bal)
    return jsonify({"status": "ok", "user_id": user_id.strip(), "credits": new_bal, "delta_applied": d}), 200


# ── Testing-phase credits admin — REMOVED (founder 2026-08-12) ────────────
# The /v2/internal/student-credits/{lookup,set} pair took CREDIT_ADMIN_PASSWORD
# in the request BODY so a browser form could send it, and it wrote the LEGACY
# `credits` column. Both halves are retired: the currency is tokens, and the
# replacement is /v2/admin/tokens/{lookup,grant} — @require_admin twins behind
# the BFF, with no shared credential anywhere in the path. The UI is
# /admin/tokens. CREDIT_ADMIN_PASSWORD can be deleted from Railway; nothing
# reads it any more.

@internal_webhooks_bp.route("/v2/internal/stripe/webhook", methods=["POST"])
def stripe_checkout_webhook():
    """
    Stripe webhook. On checkout.session.completed for a one-time token package
    (metadata.kind == token_package), grants the package (services/token_packages.py).

    Configure in Stripe: endpoint URL, event checkout.session.completed.
    Env: STRIPE_WEBHOOK_SECRET, STRIPE_SECRET_KEY.

    REMOVED (founder 2026-10-05, N48.3 Q13 A; contract 50 and 52): the
    subscription events (monthly tiers), the arc checkout (metadata.arc_id) and
    the legacy credit packs (STRIPE_CHECKOUT_PRICE_CREDITS_JSON). Nothing is
    sold through them any more, so any such event is acknowledged with 200 and
    a reason, logged, and grants nothing: a non-2xx would only make Stripe
    retry an event no code here will ever apply. If one arrives, a live
    subscription or Payment Link is still open in the Stripe dashboard.
    """
    import stripe

    wh_secret = (getattr(config, "STRIPE_WEBHOOK_SECRET", None) or "").strip()
    api_key = (getattr(config, "STRIPE_SECRET_KEY", None) or "").strip()
    if not wh_secret or not api_key:
        return jsonify({"code": "DISABLED", "error": "STRIPE_WEBHOOK_SECRET and STRIPE_SECRET_KEY required"}), 503

    payload = request.get_data(cache=False, as_text=False)
    sig_header = request.headers.get("Stripe-Signature") or ""
    stripe.api_key = api_key
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, wh_secret)
    except ValueError as e:
        logger.warning("stripe webhook invalid payload: %s", e)
        return jsonify({"code": "INVALID_PAYLOAD", "error": "Invalid payload"}), 400
    except stripe.error.SignatureVerificationError as e:
        logger.warning("stripe webhook bad signature: %s", e)
        return jsonify({"code": "INVALID_SIGNATURE", "error": "Invalid signature"}), 400

    etype = event.get("type") or ""
    if etype != "checkout.session.completed":
        if etype.startswith("customer.subscription."):
            logger.error("stripe webhook: %s received but subscriptions are "
                         "retired (N48.3 Q13 A) — nothing applied", etype)
        return jsonify({"received": True}), 200

    obj = (event.get("data") or {}).get("object") or {}
    session_id = obj.get("id")
    if not session_id:
        return jsonify({"code": "INVALID_EVENT", "error": "missing session id"}), 400

    # A one-time token package (contract §8; N44), granted from the re-read session.
    md = obj.get("metadata") or {}
    from services.token_packages import PACKAGE_KIND, webhook_reply
    if isinstance(md, dict) and md.get("kind") == PACKAGE_KIND:
        package_payload, package_status = webhook_reply(str(session_id), config)
        return jsonify(package_payload), package_status

    # Not a package: an arc checkout, a credit pack, or a sale of something
    # that is not willab's. None of them is applied any more.
    retired = isinstance(md, dict) and bool(md.get("arc_id"))
    log = logger.error if retired else logger.info
    log("stripe webhook: checkout %s is not a token package (arc=%s) — "
        "nothing applied", session_id, retired)
    return jsonify({"received": True, "granted": False,
                    "reason": "not_a_package"}), 200
