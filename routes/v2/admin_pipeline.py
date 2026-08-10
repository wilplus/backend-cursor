"""Admin-authenticated view of the processing queue. Task IV, Tier 1.

  GET  /v2/admin/pipeline/health  — queue depth, latency, saturation verdict
  GET  /v2/admin/pipeline/jobs    — recent jobs, newest first, paginated
  POST /v2/admin/pipeline/sweep   — recover jobs the queue lost track of

THESE ARE TWINS OF /v2/internal/jobs/*, NOT REPLACEMENTS. The internal
routes stay exactly as they are, gated by X-Internal-Secret, and cron keeps
using them. The difference is the CALLER: cron is a machine holding a shared
secret, an operator is a person holding a JWT. Giving them one credential
would mean either handing a machine secret to a browser session, or teaching
the backend to treat an anonymous secret-holder as an admin. Two callers, two
credentials, same two services underneath.

That is also the whole answer to "PIPELINE_JOBS_SWEEP_SECRET must never reach
the browser": under this design the secret is not merely kept away from the
BFF, it is never involved in the admin path at all. There is nothing to leak
because nothing is carried.

AC-9. Plumbing counters about JOBS — status, stage, attempts, timings — never
reads on a speaker. Admin-only, and never rendered on a student surface.
Queue state must not leak into user-facing copy either ("4 ahead of you" is
product copy needing founder sign-off, quite apart from the fence).
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from routes.admin import require_admin

logger = logging.getLogger(__name__)

admin_pipeline_bp = Blueprint("admin_pipeline", __name__)


def _no_store(payload, status: int = 200):
    """Ops reads are never cacheable — a cached queue depth is a wrong one."""
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-store"
    return resp, status


@admin_pipeline_bp.route("/v2/admin/pipeline/health", methods=["GET"])
@require_admin
def v2_admin_pipeline_health():
    """Saturation snapshot. Same service the cron probe calls.

    The verdict is the headline because it is the only part that implies an
    action: more workers shrink the WAIT, never the RUN. `queue_health()`
    never raises and reports `unknown` when it cannot read the queue, which
    is a real answer and must not be flattened into `healthy`.
    """
    from services.pipeline_health import failure_window_hours, queue_health
    return _no_store({
        "ok": True,
        "failure_window_hours": failure_window_hours(),
        **queue_health(),
    })


@admin_pipeline_bp.route("/v2/admin/pipeline/jobs", methods=["GET"])
@require_admin
def v2_admin_pipeline_jobs():
    """Recent jobs, newest first.

    Query: ?status=pending|processing|completed|failed &limit=1..100
           &before=<enqueued_at cursor from the previous page>

    A bad `status` is a 400 rather than an empty list: during an incident,
    "no jobs match" and "you typed the filter wrong" must not look identical.
    """
    from services.pipeline_admin import DEFAULT_LIMIT, list_jobs_for_admin
    status = (request.args.get("status") or "").strip() or None
    before = (request.args.get("before") or "").strip() or None
    raw_limit = (request.args.get("limit") or "").strip()
    try:
        limit = int(raw_limit) if raw_limit else DEFAULT_LIMIT
    except ValueError:
        return _no_store(
            {"code": "BAD_REQUEST", "error": "limit must be an integer"}, 400)
    try:
        return _no_store({"ok": True, **list_jobs_for_admin(
            status=status, limit=limit, before=before)})
    except ValueError as e:
        return _no_store({"code": "BAD_REQUEST", "error": str(e)}, 400)


@admin_pipeline_bp.route("/v2/admin/pipeline/sweep", methods=["POST"])
@require_admin
def v2_admin_pipeline_sweep():
    """Recover jobs the queue lost track of. The panel's only write.

    Safe to press repeatedly: recovery re-enters run_processing_job, whose
    claim CAS dedups racing runners, and a quiet sweep is a cheap SELECT. That
    is why this is the one Tier-1 action — it fixes the real incident (a
    worker died holding a job) without needing any new promise about jobs a
    worker still holds.

    Retry and cancel are deliberately NOT here (SPEC §3, founder decision
    2026-08-10): both write to the live record→transcribe path, retry has to
    respect max_attempts and the dedup_key partial unique index, and "cancel"
    has no achievable meaning for a job already claimed.
    """
    from services.pipeline_jobs import sweep_stale_jobs
    try:
        counts = sweep_stale_jobs()
    except Exception as e:
        # The internal twin lets this propagate to a 500 for cron's alerting.
        # A human pressing a button gets a readable failure instead — and the
        # panel stays usable to look at the queue that just failed to sweep.
        logger.warning("admin sweep failed: %s", e)
        return _no_store(
            {"code": "SWEEP_FAILED", "error": "sweep failed; see logs"}, 502)
    logger.info("admin sweep by user=%s: %s",
                getattr(request, "user_id", None), counts)
    return _no_store({"ok": True, **counts})
