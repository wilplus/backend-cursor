"""Job-status polling for the durable recording pipeline (async-queue work).

Two endpoints, full paths baked in (registered without a prefix, like
internal_webhooks_bp):

  GET  /v2/jobs/<job_id>/status   — the lightweight FE poll. Mechanical
       plumbing state only (status/stage/percent/message): NEVER carries
       scores, verdicts, or the readout itself (AC-9 split-sink — results
       are served by the existing readout GETs once state is ready).
  POST /v2/internal/jobs/sweep    — internal recovery poke
       (X-Internal-Secret: PIPELINE_JOBS_SWEEP_SECRET), same contract as
       the other cron webhooks: unset secret ⇒ 503 disabled.

Ownership on the poll mirrors the readout GET twins: a job created by an
authed upload requires that same user (foreign/unknown → 404, no
existence leak); a guest job (user_id NULL) is readable unauthenticated —
the guest FE holds only the job_id it was handed back.
"""
from __future__ import annotations

import hmac
import logging
import os
import uuid

from flask import Blueprint, jsonify, request

from auth import optional_auth
from services.db import db

logger = logging.getLogger(__name__)

jobs_bp = Blueprint("jobs", __name__)

_TERMINAL = ("completed", "failed")


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


@jobs_bp.route("/v2/jobs/<job_id>/status", methods=["GET"])
@optional_auth
def v2_job_status(job_id: str):
    """Poll one processing job. 200 while pending/processing/terminal;
    404 for unknown ids and other users' jobs (identical on purpose)."""
    if not _is_uuid(job_id):
        return jsonify({"code": "NOT_FOUND", "error": "job not found"}), 404
    job = db.get_processing_job(job_id)
    if not job:
        return jsonify({"code": "NOT_FOUND", "error": "job not found"}), 404
    owner = job.get("user_id")
    caller = getattr(request, "user_id", None)
    if owner and str(owner) != str(caller or ""):
        # No existence leak: foreign and unknown look identical.
        return jsonify({"code": "NOT_FOUND", "error": "job not found"}), 404

    status = str(job.get("status") or "pending")
    body = {
        "job_id": str(job.get("id")),
        "status": status,
        # The readout GETs' vocabulary (processing|ready|failed) so the FE
        # can reuse one state machine for both polls.
        "state": {
            "pending": "processing",
            "processing": "processing",
            "completed": "ready",
            "failed": "failed",
        }.get(status, "processing"),
        "stage": job.get("stage"),
        "percent": int(job.get("percent") or 0),
        "message": job.get("message"),
        "session_id": job.get("session_id"),
        "created_at": job.get("created_at"),
        "finished_at": job.get("finished_at"),
    }
    if status == "failed":
        body["error"] = job.get("error")
    if status == "completed":
        body["result"] = job.get("result")
    resp = jsonify(body)
    # Poll freshness: never let a proxy cache 'processing'.
    resp.headers["Cache-Control"] = "no-store"
    return resp, 200


@jobs_bp.route("/v2/internal/jobs/health", methods=["GET"])
def v2_internal_jobs_health():
    """Queue saturation signal — is anyone WAITING for a worker?

    OPS ONLY (same X-Internal-Secret as the sweep poke). Read-only, two
    bounded queries. Answers the one question that decides worker sizing:
    more slots shrink the wait, never the run.
    """
    secret = (os.getenv("PIPELINE_JOBS_SWEEP_SECRET") or "").strip()
    if not secret:
        return jsonify({
            "code": "DISABLED",
            "error": "PIPELINE_JOBS_SWEEP_SECRET is not configured",
        }), 503
    sent = (request.headers.get("X-Internal-Secret") or "").strip()
    if not hmac.compare_digest(sent, secret):
        return jsonify({"code": "FORBIDDEN", "error": "bad secret"}), 403
    from services.pipeline_health import queue_health
    resp = jsonify({"ok": True, **queue_health()})
    resp.headers["Cache-Control"] = "no-store"
    return resp, 200


@jobs_bp.route("/v2/internal/jobs/sweep", methods=["POST"])
def v2_internal_jobs_sweep():
    """Recover lost jobs on demand (cron / manual poke). Safe to call any
    time — recovery is CAS-guarded, a quiet sweep is a cheap SELECT."""
    secret = (os.getenv("PIPELINE_JOBS_SWEEP_SECRET") or "").strip()
    if not secret:
        return jsonify({
            "code": "DISABLED",
            "error": "PIPELINE_JOBS_SWEEP_SECRET is not configured",
        }), 503
    sent = (request.headers.get("X-Internal-Secret") or "").strip()
    if not hmac.compare_digest(sent, secret):
        return jsonify({"code": "FORBIDDEN", "error": "bad secret"}), 403
    from services.pipeline_jobs import sweep_stale_jobs
    counts = sweep_stale_jobs()
    return jsonify({"ok": True, **counts}), 200
