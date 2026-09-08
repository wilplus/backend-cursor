"""Hard-disabled HTTP surface for Coach Guidance Delivery D3."""
from flask import jsonify

from routes.admin import require_admin_or_coach
from routes.v2.blueprint import v2_bp
from services.coach_guidance_delivery import runtime_is_enabled


def _disabled_response():
    return jsonify({"code": "COACH_GUIDANCE_D3_DISABLED"}), 404


@v2_bp.get("/coach/guidance/batches/<arc_id>")
@require_admin_or_coach
def v2_coach_guidance_batch(arc_id: str):
    del arc_id
    if not runtime_is_enabled():
        return _disabled_response()
    return _disabled_response()


@v2_bp.post("/coach/guidance/attachments")
@require_admin_or_coach
def v2_coach_guidance_attachment():
    if not runtime_is_enabled():
        return _disabled_response()
    return _disabled_response()


@v2_bp.post("/coach/guidance/events")
@require_admin_or_coach
def v2_coach_guidance_event():
    if not runtime_is_enabled():
        return _disabled_response()
    return _disabled_response()


@v2_bp.post("/coach/guidance/publications")
@require_admin_or_coach
def v2_coach_guidance_publication():
    if not runtime_is_enabled():
        return _disabled_response()
    return _disabled_response()
