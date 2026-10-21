"""The founder's roadmap (founder 2026-10-21).

GET  /v2/admin/roadmap   where each planned item stands, read from GitHub

Founder only, by email, on top of the admin role, like the pace panel.
It reads the plan in config/roadmap.json and the two public repositories;
nothing here writes anything or reaches a speaker.
"""
from __future__ import annotations

import logging

from flask import jsonify

from routes.admin import require_founder
from routes.v2.blueprint import v2_bp

logger = logging.getLogger(__name__)


@v2_bp.route("/admin/roadmap", methods=["GET"])
@require_founder
def v2_admin_roadmap():
    from services.roadmap import overview
    try:
        response = jsonify(overview())
        response.headers["Cache-Control"] = "no-store"
        return response, 200
    except Exception:
        logger.exception("roadmap: read failed")
        return jsonify({"code": "ROADMAP_ERROR", "error": "The roadmap could not be read"}), 500
