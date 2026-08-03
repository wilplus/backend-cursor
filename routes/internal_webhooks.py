"""
Server-to-server hooks (no student JWT).

- POST /v2/internal/student-credits/increment — X-Internal-Secret: INTERNAL_CREDITS_WEBHOOK_SECRET
- POST /v2/internal/stripe/webhook — Stripe-Signature (STRIPE_WEBHOOK_SECRET); credits from STRIPE_CHECKOUT_PRICE_CREDITS_JSON
- POST /v2/internal/annotation-export — X-Internal-Secret: ANNOTATION_EXPORT_CRON_SECRET
- POST /v2/internal/stress-model/train — X-Internal-Secret: STRESS_MODEL_TRAIN_SECRET
- POST /v2/internal/copilot-video/retrain — X-Internal-Secret: COPILOT_VIDEO_RETRAIN_SECRET
"""
import logging
import os
import subprocess
from datetime import datetime, timezone

import httpx
from flask import Blueprint, jsonify, request

from config import Config
from services.annotation_export import result_to_dict, run_annotation_export
from services.db import db
from services.stripe_checkout_credits import apply_paid_checkout_session_credits
from utils.errors import safe_error, scrub, scrub_process_output

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


# ── Testing-phase credits admin (founder 2026-07-13) ──────────────────────
# A password-protected pair for the internal credits page. Unlike the
# server-to-server increment above (X-Internal-Secret HEADER), these take the
# password in the BODY so a browser page can send it from a form field. Gated
# on config.CREDIT_ADMIN_PASSWORD — blank ⇒ 503 (disabled).

def _credit_admin_ok():
    """(authorized, error_response). error_response is None when authorized."""
    pw = (getattr(config, "CREDIT_ADMIN_PASSWORD", None) or "").strip()
    if not pw:
        return False, (jsonify({
            "code": "DISABLED",
            "error": "CREDIT_ADMIN_PASSWORD not configured",
        }), 503)
    body = request.get_json(silent=True) or {}
    if (body.get("password") or "").strip() != pw:
        return False, (jsonify({
            "code": "UNAUTHORIZED", "error": "Wrong password",
        }), 401)
    return True, None


def _credit_admin_resolve_user(body):
    """(user_id, error_response). Resolves by user_id or email."""
    uid = (body.get("user_id") or "").strip()
    if uid:
        return uid, None
    email = (body.get("email") or "").strip()
    if email:
        resolved = db.v2_find_user_id_by_email(email)
        if not resolved:
            return None, (jsonify({
                "code": "USER_NOT_FOUND",
                "error": f"No user for email {email}",
            }), 404)
        return resolved, None
    return None, (jsonify({
        "code": "INVALID_INPUT", "error": "user_id or email is required",
    }), 400)


@internal_webhooks_bp.route("/v2/internal/student-credits/lookup", methods=["POST"])
def internal_lookup_student_credits():
    """Testing credits page — current balance. Body: { password, user_id|email }.
    200 { user_id, credits } · 400 · 401 · 404 · 503"""
    ok, err = _credit_admin_ok()
    if not ok:
        return err
    body = request.get_json(silent=True) or {}
    user_id, err = _credit_admin_resolve_user(body)
    if err:
        return err
    details = db.v2_get_student_details(user_id) or {}
    cur = details.get("credits")
    return jsonify({"user_id": user_id, "credits": int(cur) if cur is not None else 0}), 200


@internal_webhooks_bp.route("/v2/internal/student-credits/set", methods=["POST"])
def internal_set_student_credits():
    """Testing credits page — SET an absolute balance. Body:
    { password, user_id|email, credits }.
    200 { user_id, credits } · 400 · 401 · 404 · 500 · 503"""
    ok, err = _credit_admin_ok()
    if not ok:
        return err
    body = request.get_json(silent=True) or {}
    user_id, err = _credit_admin_resolve_user(body)
    if err:
        return err
    try:
        credits = int(body.get("credits"))
    except (TypeError, ValueError):
        return jsonify({"code": "INVALID_INPUT", "error": "credits must be an integer"}), 400
    if credits < 0:
        return jsonify({"code": "INVALID_INPUT", "error": "credits must be >= 0"}), 400
    new_bal = db.v2_set_student_credits(user_id, credits)
    if new_bal is None:
        return jsonify({"code": "V2_ERROR", "error": "Could not set credits"}), 500
    logger.info("internal_set_student_credits user_id=%s credits=%s", user_id, new_bal)
    return jsonify({"user_id": user_id, "credits": new_bal}), 200


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


@internal_webhooks_bp.route("/v2/internal/stress-model/train", methods=["POST"])
def internal_stress_model_train():
    """
    One-click pipeline:
      1) export stress snippet dataset JSONL
      2) train baseline stress classifier
      3) optionally promote model path into runtime_config

    Header:
      X-Internal-Secret: STRESS_MODEL_TRAIN_SECRET

    Optional JSON body:
      {
        "source_type": "all" | "student" | "internet",
        "limit": 20000,
        "max_train_rows": 5000,
        "min_samples": 80,
        "epochs": 350,
        "learning_rate": 0.08,
        "l2": 0.002,
        "train_ratio": 0.8,
        "split_group": "user_id",
        "seed": 42,
        "target_recall_stress": 0.85,
        "target_precision_stress": 0.75,
        "target_fpr_no_stress": 0.30,
        "auto_promote": true,
        "force_promote": false,
        "export_with_audio_url": false
      }

    Promotion is GATE-GUARDED (PHASE-A0-FINDINGS.md A3.4: "Promote stays
    human-gated"): auto_promote=true only promotes when the trainer's
    quality_gate passed. A failing/missing gate → promoted:false with
    promotion_skipped_reason. force_promote:true is the explicit human
    override for the gate (logged loudly, recorded in runtime_config
    metadata) — it does NOT override a failed storage upload: a local
    ephemeral path is never promoted (other dynos can't read it).
    """
    secret = (getattr(config, "STRESS_MODEL_TRAIN_SECRET", None) or "").strip()
    if not secret:
        return jsonify({"code": "DISABLED", "error": "STRESS_MODEL_TRAIN_SECRET not configured"}), 503
    if (request.headers.get("X-Internal-Secret") or "").strip() != secret:
        return jsonify({"code": "UNAUTHORIZED", "error": "Invalid or missing X-Internal-Secret"}), 401

    data = request.get_json(silent=True) or {}
    source_type = (data.get("source_type") or "all").strip().lower()
    if source_type not in ("all", "student", "internet"):
        return jsonify({"code": "INVALID_INPUT", "error": "source_type must be one of: all, student, internet"}), 400

    try:
        limit = int(data.get("limit", 20000))
        max_train_rows = int(data.get("max_train_rows", 5000))
        min_samples = int(data.get("min_samples", 80))
        epochs = int(data.get("epochs", 350))
        seed = int(data.get("seed", 42))
        lr = float(data.get("learning_rate", data.get("lr", 0.08)))
        l2 = float(data.get("l2", 0.002))
        train_ratio = float(data.get("train_ratio", 0.8))
        target_recall_stress = float(data.get("target_recall_stress", 0.85))
        target_precision_stress = float(data.get("target_precision_stress", 0.75))
        target_fpr_no_stress = float(data.get("target_fpr_no_stress", 0.30))
    except (TypeError, ValueError):
        return jsonify({"code": "INVALID_INPUT", "error": "Invalid numeric training parameters"}), 400

    auto_promote = _parse_bool(data.get("auto_promote"), True)
    force_promote = _parse_bool(data.get("force_promote"), False)
    export_with_audio_url = _parse_bool(data.get("export_with_audio_url"), False)
    split_group = (data.get("split_group") or "user_id").strip().lower()
    if split_group not in ("user_id", "session_id", "recording_id"):
        return jsonify({"code": "INVALID_INPUT", "error": "split_group must be one of: user_id, session_id, recording_id"}), 400

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    exports_dir = os.path.join(repo_root, "exports")
    os.makedirs(exports_dir, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dataset_path = os.path.join(exports_dir, f"stress-dataset-{source_type}-{run_id}.jsonl")
    model_path = os.path.join(exports_dir, f"stress-model-{source_type}-{run_id}.json")
    metrics_path = os.path.join(exports_dir, f"stress-model-{source_type}-{run_id}-metrics.json")

    export_cmd = [
        "python3",
        "scripts/export_stress_snippets_dataset.py",
        "-o",
        dataset_path,
        "--source-type",
        source_type,
    ]
    if export_with_audio_url:
        export_cmd.append("--with-audio-url")

    train_cmd = [
        "python3",
        "scripts/train_stress_classifier_baseline.py",
        "--model-out",
        model_path,
        "--metrics-out",
        metrics_path,
        "--source-type",
        source_type,
        "--limit",
        str(max(1, limit)),
        "--max-train-rows",
        str(max(1, max_train_rows)),
        "--min-samples",
        str(max(20, min_samples)),
        "--epochs",
        str(max(10, epochs)),
        "--lr",
        str(max(0.0001, lr)),
        "--l2",
        str(max(0.0, l2)),
        "--train-ratio",
        str(max(0.5, min(0.95, train_ratio))),
        "--seed",
        str(seed),
        "--split-group",
        split_group,
        "--target-recall-stress",
        str(max(0.0, min(1.0, target_recall_stress))),
        "--target-precision-stress",
        str(max(0.0, min(1.0, target_precision_stress))),
        "--target-fpr-no-stress",
        str(max(0.0, min(1.0, target_fpr_no_stress))),
    ]

    try:
        export_proc = subprocess.run(
            export_cmd,
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=900,
        )
        if export_proc.returncode != 0:
            # The subprocess echoes its full argv — absolute repo paths,
            # the dataset location, and whatever the exporter printed. It
            # goes to the log, never over the wire (P0 audit 2026-08-03).
            logger.error(
                "stress export rc=%s stdout=%s stderr=%s",
                export_proc.returncode,
                scrub_process_output(export_proc.stdout[-4000:]),
                scrub_process_output(export_proc.stderr[-4000:]),
            )
            return safe_error("EXPORT_FAILED", 500,
                              message="Stress dataset export failed.")

        train_proc = subprocess.run(
            train_cmd,
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if train_proc.returncode != 0:
            # Same rule as the export branch — plus dataset_path, which
            # named a real on-disk location to the caller.
            logger.error(
                "stress train rc=%s dataset=%s stdout=%s stderr=%s",
                train_proc.returncode, dataset_path,
                scrub_process_output(train_proc.stdout[-6000:]),
                scrub_process_output(train_proc.stderr[-6000:]),
            )
            return safe_error("TRAIN_FAILED", 500,
                              message="Stress model training failed.")

        import json as _json

        metrics_payload = None
        try:
            with open(metrics_path, "r", encoding="utf-8") as fh:
                metrics_payload = _json.load(fh)
        except Exception:
            metrics_payload = None

        # The trainer's quality gate (scripts/train_stress_classifier_baseline.py
        # serializes it into both the metrics file and the model artifact).
        # Prefer the metrics file; fall back to the artifact.
        quality_gate = None
        if isinstance(metrics_payload, dict):
            qg = metrics_payload.get("quality_gate")
            if isinstance(qg, dict):
                quality_gate = qg
        if quality_gate is None:
            try:
                with open(model_path, "r", encoding="utf-8") as fh:
                    artifact_payload = _json.load(fh)
                qg = ((artifact_payload or {}).get("metrics") or {}).get("quality_gate")
                if isinstance(qg, dict):
                    quality_gate = qg
            except Exception:
                quality_gate = None

        # ── Gate-guarded promotion (A3.4 "Promote stays human-gated") ──
        # auto_promote (default True) only promotes a model whose quality
        # gate PASSED. Failing/missing gate → no promote, unless the caller
        # explicitly sends force_promote:true (human override, logged +
        # recorded in the runtime_config metadata). A model whose artifact
        # could not be uploaded to storage is NEVER promoted — the local
        # exports/ path is dyno-ephemeral and unreadable elsewhere — and
        # force_promote does NOT override that.
        promoted = None
        promoted_flag = False
        promotion_skipped_reason = None
        gate_ok = bool(quality_gate.get("ok")) if isinstance(quality_gate, dict) else None

        if auto_promote or force_promote:
            bucket = (getattr(config, "STRESS_MODEL_BUCKET", None) or "stress_models").strip() or "stress_models"
            storage_key = f"baseline/{source_type}/{run_id}.json"
            promote_value = None
            try:
                with open(model_path, "rb") as mf:
                    model_bytes = mf.read()
                db.upload_audio(bucket, storage_key, model_bytes, "application/json")
                promote_value = f"storage://{bucket}/{storage_key}"
                logger.info(
                    "internal_stress_model_train uploaded model bucket=%s key=%s",
                    bucket,
                    storage_key,
                )
            except Exception as upload_exc:
                logger.warning(
                    "internal_stress_model_train: storage upload failed — model NOT promoted "
                    "(promotion requires the storage:// ref; set up bucket %s): %s",
                    bucket,
                    upload_exc,
                )

            if promote_value is None:
                promotion_skipped_reason = "artifact_not_in_storage"
            elif quality_gate is None and not force_promote:
                promotion_skipped_reason = "quality_gate_missing"
            elif quality_gate is not None and not gate_ok and not force_promote:
                promotion_skipped_reason = "quality_gate_failed"
            else:
                if force_promote and not gate_ok:
                    logger.warning(
                        "internal_stress_model_train: FORCE-PROMOTING run_id=%s despite "
                        "quality_gate ok=%s (explicit force_promote:true override)",
                        run_id,
                        gate_ok,
                    )
                promoted = db.upsert_runtime_config(
                    key="stress_baseline_model_path",
                    value=promote_value,
                    updated_by="internal:stress-model-train",
                    metadata={
                        "source_type": source_type,
                        "run_id": run_id,
                        "dataset_path": dataset_path,
                        "metrics_path": metrics_path,
                        "local_model_path": model_path,
                        "storage_bucket": bucket,
                        "storage_key": storage_key,
                        # Gate outcome + override provenance — the learning
                        # trace page reads these back.
                        "quality_gate": quality_gate,
                        "quality_gate_ok": gate_ok,
                        "force_promote": force_promote,
                        "promoted_via": "force_promote" if (force_promote and not gate_ok) else "quality_gate_pass",
                    },
                )
                promoted_flag = promoted is not None

        return jsonify(
            {
                "status": "ok",
                "run_id": run_id,
                "source_type": source_type,
                "dataset_path": dataset_path,
                "model_path": model_path,
                "metrics_path": metrics_path,
                "auto_promote": auto_promote,
                "force_promote": force_promote,
                "promoted": promoted_flag,
                "promotion_skipped_reason": promotion_skipped_reason,
                "quality_gate": quality_gate,
                "runtime_config": promoted,
                "metrics": metrics_payload,
            }
        ), 200
    except subprocess.TimeoutExpired as te:
        # TimeoutExpired.__str__ renders the whole command list.
        return safe_error("TIMEOUT", 504, exc=te,
                          message="The training pipeline timed out.",
                          log="internal_stress_model_train timed out")
    except Exception as exc:
        return safe_error("PIPELINE_FAILED", 500, exc=exc,
                          log="internal_stress_model_train failed")


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
