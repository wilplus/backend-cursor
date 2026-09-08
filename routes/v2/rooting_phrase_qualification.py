"""Hard-disabled RPQ-V1 route placeholders.

No request can reach the pending SQL contract in this slice.  These endpoints
reserve the typed boundary so later activation cannot be smuggled into an
unrelated route.
"""
from flask import jsonify

from routes.v2.blueprint import v2_bp
from services.rooting_phrase_qualification_v1 import runtime_is_enabled


def _disabled_response():
    return jsonify({"code": "RPQ_V1_DISABLED"}), 404


@v2_bp.get("/explore/arcs/<arc_id>/rooting-phrase-qualification")
def v2_rooting_phrase_qualification(arc_id: str):
    del arc_id
    if not runtime_is_enabled():
        return _disabled_response()
    # Deliberately unreachable until a separate serving implementation review.
    return _disabled_response()


@v2_bp.post("/explore/arcs/<arc_id>/rooting-phrase-qualification/actions")
def v2_rooting_phrase_qualification_action(arc_id: str):
    del arc_id
    if not runtime_is_enabled():
        return _disabled_response()
    return _disabled_response()

