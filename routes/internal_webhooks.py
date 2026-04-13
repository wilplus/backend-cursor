"""
Server-to-server hooks (no student JWT).

- POST /v2/internal/student-credits/increment — X-Internal-Secret: INTERNAL_CREDITS_WEBHOOK_SECRET
- POST /v2/internal/stripe/webhook — Stripe-Signature (STRIPE_WEBHOOK_SECRET); credits from STRIPE_CHECKOUT_PRICE_CREDITS_JSON
- POST /v2/internal/annotation-export — X-Internal-Secret: ANNOTATION_EXPORT_CRON_SECRET
- POST /v2/internal/stress-model/train — X-Internal-Secret: STRESS_MODEL_TRAIN_SECRET
"""
import logging
import os
import subprocess
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from config import Config
from services.annotation_export import result_to_dict, run_annotation_export
from services.db import db
from services.stripe_checkout_credits import apply_paid_checkout_session_credits

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
            cur = 15
        return jsonify({"status": "ok", "user_id": user_id.strip(), "credits": int(cur), "delta_applied": 0}), 200

    new_bal = db.v2_increment_student_credits(user_id.strip(), d)
    if new_bal is None:
        return jsonify({"code": "V2_ERROR", "error": "Could not update credits"}), 500
    logger.info("internal_increment_student_credits user_id=%s delta=%s new_credits=%s", user_id, d, new_bal)
    return jsonify({"status": "ok", "user_id": user_id.strip(), "credits": new_bal, "delta_applied": d}), 200


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

    if event.get("type") != "checkout.session.completed":
        return jsonify({"received": True}), 200

    obj = (event.get("data") or {}).get("object") or {}
    session_id = obj.get("id")
    if not session_id:
        return jsonify({"code": "INVALID_EVENT", "error": "missing session id"}), 400

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
        logger.warning("internal_annotation_export failed: %s", exc)
        return jsonify({"code": "EXPORT_FAILED", "error": str(exc)}), 500


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
        "export_with_audio_url": false
      }
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
            return jsonify(
                {
                    "code": "EXPORT_FAILED",
                    "error": "Stress dataset export failed",
                    "stdout": export_proc.stdout[-4000:],
                    "stderr": export_proc.stderr[-4000:],
                }
            ), 500

        train_proc = subprocess.run(
            train_cmd,
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if train_proc.returncode != 0:
            return jsonify(
                {
                    "code": "TRAIN_FAILED",
                    "error": "Stress model training failed",
                    "stdout": train_proc.stdout[-6000:],
                    "stderr": train_proc.stderr[-6000:],
                    "dataset_path": dataset_path,
                }
            ), 500

        metrics_payload = None
        try:
            with open(metrics_path, "r", encoding="utf-8") as fh:
                import json as _json

                metrics_payload = _json.load(fh)
        except Exception:
            metrics_payload = None

        promoted = None
        if auto_promote:
            promote_value = model_path
            bucket = (getattr(config, "STRESS_MODEL_BUCKET", None) or "stress_models").strip() or "stress_models"
            storage_key = f"baseline/{source_type}/{run_id}.json"
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
                    "internal_stress_model_train: storage upload failed, using local path (set up bucket %s): %s",
                    bucket,
                    upload_exc,
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
                    "storage_key": storage_key if promote_value.startswith("storage://") else None,
                },
            )

        return jsonify(
            {
                "status": "ok",
                "run_id": run_id,
                "source_type": source_type,
                "dataset_path": dataset_path,
                "model_path": model_path,
                "metrics_path": metrics_path,
                "auto_promote": auto_promote,
                "runtime_config": promoted,
                "metrics": metrics_payload,
                "export_stdout": export_proc.stdout[-2000:],
                "train_stdout": train_proc.stdout[-2000:],
            }
        ), 200
    except subprocess.TimeoutExpired as te:
        return jsonify({"code": "TIMEOUT", "error": f"Pipeline timed out: {te}"}), 504
    except Exception as exc:
        logger.warning("internal_stress_model_train failed: %s", exc, exc_info=True)
        return jsonify({"code": "PIPELINE_FAILED", "error": str(exc)}), 500
