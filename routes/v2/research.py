"""The research screen (founder 2026-09-30, L4 to L9; build plan ML-6, ML-7).

GET  /v2/research/overview                     the read-only view
GET  /v2/research/golden                       the golden sets' counts
GET  /v2/research/golden/<surface>/next        the next moment to judge (founder)
POST /v2/research/golden/<surface>/judgements  one judgement (founder)
POST /v2/research/golden/<surface>/seal        seal the set (founder)

The research role (research_users) and the founder may read; only the
founder judges and seals (L6: the evaluation set is the founder's).
Every panel names in words what is missing while its door is closed.
"""
from __future__ import annotations

import logging

import sentry_sdk
from flask import jsonify, request

from routes.admin import require_founder, require_research_read
from routes.v2.blueprint import v2_bp
from services.db import db

logger = logging.getLogger(__name__)


def _judge() -> str:
    payload = getattr(request, "token_payload", None) or {}
    return str(payload.get("email") or "").strip().lower()


@v2_bp.route("/research/overview", methods=["GET"])
@require_research_read
def v2_research_overview():
    from services.research_view import overview
    try:
        response = jsonify(overview(db))
        response.headers["Cache-Control"] = "no-store"
        return response, 200
    except Exception as e:
        logger.error("research overview failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to read the research view"}), 500


@v2_bp.route("/research/golden", methods=["GET"])
@require_research_read
def v2_research_golden():
    from services.golden_set import SURFACES, counts
    return jsonify({"sets": {s: counts(db, surface=s) for s in SURFACES}}), 200


@v2_bp.route("/research/golden/<surface>/next", methods=["GET"])
@require_founder
def v2_research_golden_next(surface):
    from services.golden_set import GoldenRefusal, next_moment
    try:
        moment = next_moment(db, surface=surface, judge=_judge())
    except GoldenRefusal as refusal:
        return jsonify({"code": refusal.code, "error": refusal.message}), refusal.status
    return jsonify({"moment": moment}), 200


@v2_bp.route("/research/golden/<surface>/judgements", methods=["POST"])
@require_founder
def v2_research_golden_judge(surface):
    from services.golden_set import GoldenRefusal, record
    try:
        return jsonify(record(db, surface=surface, judge=_judge(),
                              body=request.get_json(silent=True))), 200
    except GoldenRefusal as refusal:
        return jsonify({"code": refusal.code, "error": refusal.message}), refusal.status


@v2_bp.route("/research/golden/<surface>/seal", methods=["POST"])
@require_founder
def v2_research_golden_seal(surface):
    from services.golden_set import GoldenRefusal, seal
    try:
        return jsonify(seal(db, surface=surface, judge=_judge())), 200
    except GoldenRefusal as refusal:
        return jsonify({"code": refusal.code, "error": refusal.message}), refusal.status
