"""
Server-to-server hooks (no student JWT).

- POST /v2/internal/student-credits/increment — X-Internal-Secret: INTERNAL_CREDITS_WEBHOOK_SECRET
- POST /v2/internal/stripe/webhook — Stripe-Signature (STRIPE_WEBHOOK_SECRET); credits from STRIPE_CHECKOUT_PRICE_CREDITS_JSON
- POST /v2/internal/annotation-export — X-Internal-Secret: ANNOTATION_EXPORT_CRON_SECRET
- POST /v2/internal/copilot-video/retrain — X-Internal-Secret: COPILOT_VIDEO_RETRAIN_SECRET

RETIRED (founder 2026-08-03, stress-lane deletion): POST /v2/internal/stress-
model/train. It ran a `subprocess.run` train pipeline INSIDE the request
handler (30-minute timeout on a web dyno), defaulted `auto_promote` to true,
and promoted `runtime_config.stress_baseline_model_path`. The whole second
lane is gone and there is NO replacement trainer — the peer-review validation
loop (POST /v2/user/snippets/<id>/confidence-review) replaces it. Do not
reintroduce a trainer in a request handler; nothing may promote a model
artifact without a quality gate AND a human decision.
"""
import logging
from datetime import datetime, timezone

import httpx
from flask import Blueprint, jsonify, request

from config import Config
from services.annotation_export import result_to_dict, run_annotation_export
from services.db import db
from services.stripe_checkout_credits import apply_paid_checkout_session_credits
from utils.errors import safe_error, scrub

logger = logging.getLogger(__name__)
config = Config()

internal_webhooks_bp = Blueprint("internal_webhooks", __name__)


def _parse_bool(value, default=False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


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
    Stripe webhook for Checkout (payment mode). On checkout.session.completed, adds credits to v2_student_details.

    Configure in Stripe: endpoint URL, events checkout.session.completed.
    Env: STRIPE_WEBHOOK_SECRET, STRIPE_SECRET_KEY, STRIPE_CHECKOUT_PRICE_CREDITS_JSON (Price id → credits).

    Checkout Session must include client_reference_id or metadata.user_id = Supabase auth user id (uuid).
    Credit amount is derived only from paid line item Price IDs present in STRIPE_CHECKOUT_PRICE_CREDITS_JSON.
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

    # Token pricing Phase 1: the three paid tiers are RECURRING prices, so they
    # arrive as subscription events rather than checkout completions. Handled
    # BEFORE the checkout branch and returning early, so the legacy credit-pack
    # path below is byte-for-byte unchanged.
    from services.stripe_subscription_tiers import (
        apply_subscription_event, is_subscription_event,
    )
    if is_subscription_event(event.get("type")):
        sub_result = apply_subscription_event(
            event, getattr(config, "STRIPE_PRICE_TIER_JSON", "") or "",
        )
        # Always 200: a mapping we cannot resolve is ours to fix from the logs,
        # and telling Stripe to retry forever fixes nothing.
        return jsonify({"received": True, **sub_result}), 200

    if event.get("type") != "checkout.session.completed":
        return jsonify({"received": True}), 200

    obj = (event.get("data") or {}).get("object") or {}
    session_id = obj.get("id")
    if not session_id:
        return jsonify({"code": "INVALID_EVENT", "error": "missing session id"}), 400

    # willab Paid Audits (A3): a session tagged with metadata.arc_id is an
    # AUDIT purchase, not a credits top-up. Route it to the arc path and return
    # BEFORE the credits branch (which stays exactly as it was). The metadata is
    # on the event object, so no extra retrieve to discriminate.
    md = obj.get("metadata") or {}
    if isinstance(md, dict) and md.get("arc_id"):
        from services.arc_checkout import apply_completed_arc_checkout
        arc_result = apply_completed_arc_checkout(str(session_id), config)
        arc_payload = dict(arc_result.payload)
        if arc_result.ok:
            arc_payload["received"] = True
        return jsonify(arc_payload), arc_result.http_status

    result = apply_paid_checkout_session_credits(str(session_id), auth_user_id=None, app_config=config)
    payload = dict(result.payload)
    if result.ok:
        payload["received"] = True
    return jsonify(payload), result.http_status


@internal_webhooks_bp.route("/v2/internal/annotation-export", methods=["POST"])
def internal_annotation_export():
    """Cron-friendly export of admin_annotation_events → JSONL (+ optional Supabase Storage).

    Header: X-Internal-Secret: <ANNOTATION_EXPORT_CRON_SECRET>
    Body JSON (optional): { "limit": 5000, "dry_run": false }

    Configure ANNOTATION_EXPORT_BUCKET (recommended on Railway) and/or ANNOTATION_EXPORT_OUTPUT_DIR.
    """
    secret = (getattr(config, "ANNOTATION_EXPORT_CRON_SECRET", None) or "").strip()
    if not secret:
        return jsonify({"code": "DISABLED", "error": "ANNOTATION_EXPORT_CRON_SECRET not configured"}), 503
    if (request.headers.get("X-Internal-Secret") or "").strip() != secret:
        return jsonify({"code": "UNAUTHORIZED", "error": "Invalid or missing X-Internal-Secret"}), 401

    data = request.get_json(silent=True) or {}
    try:
        limit = int(data.get("limit", 5000))
    except (TypeError, ValueError):
        return jsonify({"code": "INVALID_INPUT", "error": "limit must be an integer"}), 400
    dry_raw = data.get("dry_run", False)
    dry_run = str(dry_raw).lower() in ("1", "true", "yes")

    bucket = (data.get("upload_bucket") or getattr(config, "ANNOTATION_EXPORT_BUCKET", None) or "").strip() or None
    output_dir = (data.get("output_dir") or getattr(config, "ANNOTATION_EXPORT_OUTPUT_DIR", None) or "").strip() or None
    prefix = (data.get("upload_prefix") or getattr(config, "ANNOTATION_EXPORT_PREFIX", None) or "annotation-events").strip()

    if not dry_run and not bucket and not output_dir:
        return jsonify(
            {
                "code": "EXPORT_SINK_MISSING",
                "error": "Set ANNOTATION_EXPORT_BUCKET and/or ANNOTATION_EXPORT_OUTPUT_DIR, or pass them in the body.",
            }
        ), 400

    try:
        result = run_annotation_export(
            limit=limit,
            output_dir=None if dry_run else output_dir,
            dry_run=dry_run,
            created_by="cron:internal_annotation_export",
            upload_bucket=bucket,
            upload_prefix=prefix,
        )
        logger.info(
            "internal_annotation_export run_id=%s exported=%s checkpoint=%s",
            result.run_id,
            result.exported_count,
            result.checkpoint_created_at,
        )
        return jsonify({"status": "ok", **result_to_dict(result)}), 200
    except Exception as exc:
        return safe_error("EXPORT_FAILED", 500, exc=exc,
                          log="internal_annotation_export failed")


@internal_webhooks_bp.route("/v2/internal/copilot-video/retrain", methods=["POST"])
def internal_copilot_video_retrain():
    """
    Trigger scheduled speech/video retraining from uploaded override videos.

    Header:
      X-Internal-Secret: COPILOT_VIDEO_RETRAIN_SECRET

    Optional JSON body:
      {
        "limit": 500,
        "dry_run": false,
        "run_interval_days": 14
      }
    """
    secret = (getattr(config, "COPILOT_VIDEO_RETRAIN_SECRET", None) or "").strip()
    if not secret:
        return jsonify({"code": "DISABLED", "error": "COPILOT_VIDEO_RETRAIN_SECRET not configured"}), 503
    if (request.headers.get("X-Internal-Secret") or "").strip() != secret:
        return jsonify({"code": "UNAUTHORIZED", "error": "Invalid or missing X-Internal-Secret"}), 401

    data = request.get_json(silent=True) or {}
    try:
        limit = int(data.get("limit", 500))
        run_interval_days = int(data.get("run_interval_days", 14))
    except (TypeError, ValueError):
        return jsonify({"code": "INVALID_INPUT", "error": "limit and run_interval_days must be integers"}), 400
    dry_run = _parse_bool(data.get("dry_run"), False)
    limit = max(1, min(5000, limit))
    run_interval_days = max(1, min(60, run_interval_days))

    run_type = "speech_video_retrain"
    latest_run = db.get_latest_model_training_run(run_type)
    since_iso = None
    if latest_run and latest_run.get("finished_at"):
        since_iso = latest_run.get("finished_at")

    refs = db.list_admin_uploaded_reference_videos_for_training(since_iso=since_iso, limit=limit)
    now = datetime.now(timezone.utc)
    if latest_run and latest_run.get("finished_at"):
        try:
            finished_at = datetime.fromisoformat(str(latest_run.get("finished_at")).replace("Z", "+00:00"))
            if (now - finished_at).days < run_interval_days and not dry_run:
                skipped = db.create_model_training_run(
                    run_type=run_type,
                    status="skipped",
                    input_count=0,
                    metadata={
                        "reason": "interval_not_reached",
                        "last_finished_at": latest_run.get("finished_at"),
                        "run_interval_days": run_interval_days,
                    },
                    created_by="internal:copilot-video-retrain",
                )
                return jsonify(
                    {
                        "status": "ok",
                        "skipped": True,
                        "reason": "interval_not_reached",
                        "run": skipped,
                    }
                ), 200
        except Exception:
            pass

    if not refs:
        skipped = db.create_model_training_run(
            run_type=run_type,
            status="skipped",
            input_count=0,
            metadata={"reason": "no_new_reference_videos", "since": since_iso},
            created_by="internal:copilot-video-retrain",
        )
        return jsonify({"status": "ok", "skipped": True, "reason": "no_new_reference_videos", "run": skipped}), 200

    run = db.create_model_training_run(
        run_type=run_type,
        status="running",
        input_count=len(refs),
        metadata={
            "since": since_iso,
            "dry_run": dry_run,
            "reference_video_ids": [r.get("id") for r in refs],
            "reference_count": len(refs),
        },
        created_by="internal:copilot-video-retrain",
    )
    if not run:
        return jsonify({"code": "RUN_CREATE_FAILED", "error": "Could not create training run"}), 500

    try:
        retrain_url = (getattr(config, "COPILOT_VIDEO_RETRAIN_WEBHOOK_URL", None) or "").strip()
        output_ref = None
        provider_response = None
        if not dry_run and retrain_url:
            payload = {
                "run_id": run.get("id"),
                "run_type": run_type,
                "reference_videos": [
                    {
                        "id": r.get("id"),
                        "user_id": r.get("user_id"),
                        "session_id": r.get("session_id"),
                        "storage_path": r.get("storage_path"),
                        "tags": r.get("tags") or [],
                        "feature_metadata": r.get("feature_metadata") or {},
                        "created_at": r.get("created_at"),
                    }
                    for r in refs
                ],
            }
            webhook_resp = httpx.post(retrain_url, json=payload, timeout=180)
            webhook_resp.raise_for_status()
            provider_response = webhook_resp.json() if "application/json" in (webhook_resp.headers.get("content-type") or "").lower() else {"status_code": webhook_resp.status_code}
            output_ref = (
                str(provider_response.get("model_version") or "").strip()
                or str(provider_response.get("job_id") or "").strip()
                or str(provider_response.get("artifact_ref") or "").strip()
                or None
            )

        completed = db.update_model_training_run(
            run_id=str(run.get("id")),
            status="completed",
            input_count=len(refs),
            output_artifact_ref=output_ref,
            metadata={
                "since": since_iso,
                "dry_run": dry_run,
                "reference_count": len(refs),
                "provider_response": provider_response,
            },
            error=None,
        )
        return jsonify(
            {
                "status": "ok",
                "run": completed,
                "reference_count": len(refs),
                "dry_run": dry_run,
            }
        ), 200
    except Exception as exc:
        db.update_model_training_run(
            run_id=str(run.get("id")),
            status="failed",
            input_count=len(refs),
            metadata={"since": since_iso, "dry_run": dry_run, "reference_count": len(refs)},
            error=scrub(exc, limit=1000),
        )
        return safe_error("TRAIN_FAILED", 500, exc=exc,
                          log="internal_copilot_video_retrain failed",
                          extra={"run_id": run.get("id")})
