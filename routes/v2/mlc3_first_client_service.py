"""The MLC-3 exercise service loop's speaker routes — RETIRED.

Founder 2026-09-30 (L8; contract 66): the service loop (feedback render and
respond, exercise offers, practice sessions and attempts, user guidance
playback — nineteen routes under ``/v2/user/mlc3/...``) is retired. Every
path under that prefix is one 410 tombstone so any lingering client gets a
clear signal, the way ``routes/v2/arcs.py`` (``v2_arc_unlock``) and
``routes/phase2_guard.py`` retire a door. Its tables and migrations stay
(never dropped); the monitors' cron scripts and the readiness checkers are
gone. The module keeps its name and its place in ``DOMAIN_MODULES`` so the
blueprint registers exactly as before.

``GET /v2/user/mlc3/confident-moment-exercise/<bundle_id>/<attachment_id>``
in ``routes/v2/confident_moment_bundles.py`` is NOT retired: it sits behind
the bundle gate and its rule is more specific than this catch-all, so Flask
matches it first (pinned by tests/test_mlc3_loop_retired.py).
"""
from __future__ import annotations

from flask import jsonify

from routes.v2.blueprint import v2_bp

GONE_ERROR = (
    "The MLC-3 service loop was retired (founder 2026-09-30, L8; contract 66)."
)


@v2_bp.route(
    "/user/mlc3/<path:rest>", methods=["GET", "POST", "PUT", "DELETE"],
)
def v2_mlc3_user_service_retired(rest: str):
    """410 GONE for every retired ``/v2/user/mlc3/...`` path."""
    return jsonify({"code": "GONE", "error": GONE_ERROR}), 410
