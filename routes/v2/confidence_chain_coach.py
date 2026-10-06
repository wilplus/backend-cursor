"""The confidence chain's blind packet and render receipt, for the coach (Q2).

Two routes, in the order the coach's screen uses them:

  POST /coach/snippets/<snippet_id>/mlc2-packet
      THE WALK'S ADAPTER (founder 2026-10-05, N48.5 Q27 A: "the coach walk's
      blind labels as its judgements"). The walk's Judge screen asks, when
      it paints a moment, whether the chain holds a selected candidate for
      that moment; if so the blind packet is prepared for THIS coach (0393's
      wrapper) and the four identifiers come back, else null. Nothing about
      the moment is in the answer (BLIND COACH), and the coach sees nothing
      new. A coach who already rated the moment, or who has seen its
      non-blind side (35g-11), gets null: a second listen is never a blind
      judgement.
  POST /coach/mlc2/assignments/<assignment_id>/render
      The browser's post-paint receipt for that packet; the exposure id it
      returns is what the coach's answer echoes on the label PUT, which then
      writes the chain's immutable blind_coach judgement and its reveal, in
      that order, after the legacy save (routes/v2/coach.py).

The receipt is closed (404) unless the writer state is ``founder_canary``, so
the surface is not discoverable while dark; the packet route answers null.
"""
from __future__ import annotations

from typing import Any

from flask import jsonify, request

from routes.admin import require_admin_or_coach
from routes.v2.blueprint import v2_bp
from services.confidence_chain_consumer import (
    HANDLE_KEY,
    ConfidenceChainConsumerError,
    ConfidenceChainConsumerStore,
    consumer_enabled,
)
from services.confidence_chain_walk import walk_packet
from services.db import db
from utils.ids import parse_uuid


def _body() -> dict[str, Any]:
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def _idempotency_key() -> str:
    value = str(request.headers.get("Idempotency-Key") or "").strip()
    if not 1 <= len(value) <= 200:
        raise ValueError("Idempotency-Key is required")
    return value


def _reviewer_principal_id() -> str:
    user_id = parse_uuid(getattr(request, "user_id", None), "reviewer_user_id")
    principal = db.get_owner_principal_for_user(user_id) or {}
    return parse_uuid(principal.get("id"), "reviewer_principal_id")


@v2_bp.post("/coach/mlc2/assignments/<assignment_id>/render")
@require_admin_or_coach
def v2_coach_confidence_chain_render(assignment_id: str):
    if not consumer_enabled():
        return jsonify({"code": "NOT_FOUND"}), 404
    try:
        # The request is validated in full before anything is looked up.
        idempotency_key = _idempotency_key()
        body = _body()
        fields = {
            "review_assignment_id": parse_uuid(
                assignment_id, "review_assignment_id"),
            "presentation_id": parse_uuid(
                body.get("presentation_id"), "presentation_id"),
            "acknowledgement_token": parse_uuid(
                body.get("acknowledgement_token"), "acknowledgement_token"),
            "render_instance_id": parse_uuid(
                body.get("render_instance_id"), "render_instance_id"),
            "client_rendered_at": str(body.get("client_rendered_at") or ""),
            "visible_payload_sha256": str(
                body.get("visible_payload_sha256") or ""),
        }
        if not fields["client_rendered_at"] or not fields["visible_payload_sha256"]:
            raise ValueError("client_rendered_at and visible_payload_sha256 are required")
    except (TypeError, ValueError):
        return jsonify({"code": "INVALID_INPUT"}), 400
    try:
        store = ConfidenceChainConsumerStore(db.client)
        row = store.ack_render(
            reviewer_principal_id=_reviewer_principal_id(),
            idempotency_key=idempotency_key,
            **fields,
        )
    except (TypeError, ValueError, ConfidenceChainConsumerError):
        return jsonify({"code": "INVALID_INPUT"}), 400
    except Exception as error:  # noqa: BLE001 - the receipt is refused, not faked
        return jsonify({
            "code": "CONFIDENCE_CHAIN_RENDER_NOT_RECORDED",
            "error": str(error)[:200],
        }), 409
    if not row or not row.get("id"):
        return jsonify({"code": "CONFIDENCE_CHAIN_RENDER_NOT_RECORDED"}), 409
    return jsonify({"exposure_id": str(row["id"])}), 201


@v2_bp.post("/coach/snippets/<snippet_id>/mlc2-packet")
@require_admin_or_coach
def v2_coach_confidence_chain_packet(snippet_id: str):
    """The walk's blind packet for this coach on this moment, or null
    (services/confidence_chain_walk.py decides who gets one)."""
    try:
        snippet = parse_uuid(snippet_id, "snippet_id")
    except (TypeError, ValueError):
        return jsonify({"code": "INVALID_INPUT"}), 400
    coach_id = str(getattr(request, "user_id", "") or "")
    return jsonify({HANDLE_KEY: walk_packet(db, coach_id=coach_id, snippet_id=snippet)}), 200
