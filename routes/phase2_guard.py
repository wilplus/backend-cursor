"""Fail-closed HTTP boundary for every Phase-2 learning operation.

Phase 1 may keep historical handlers and data readable for audit, but no
request is allowed to create a corpus, export a dataset, or start training.
Keeping the response in one decorator prevents route-specific feature flags
from accidentally reopening a retired path.
"""
from __future__ import annotations

from functools import wraps

from flask import jsonify


def phase2_learning_disabled(function):
    """Return a stable terminal response without entering the handler."""
    @wraps(function)
    def disabled(*args, **kwargs):
        return jsonify({
            "code": "PHASE2_DISABLED",
            "error": "Pooled datasets, training, and promotion are not active.",
        }), 410

    raw = function
    while getattr(raw, "__wrapped__", None) is not None:
        raw = raw.__wrapped__
    disabled.__wrapped__ = raw
    return disabled


def operational_purpose_disabled(purpose_id: str):
    """Fail closed while a registry-only product purpose is not operational.

    This is intentionally separate from the pooled-learning guard: a product
    feature can be unavailable even though it is not itself a training job.
    Keeping the decision at the route boundary prevents dormant handlers from
    downloading audio or reaching a provider before the purpose has its own
    reviewed authorization, retention, deletion and rights controls.
    """
    def decorate(function):
        @wraps(function)
        def disabled(*args, **kwargs):
            return jsonify({
                "code": "PURPOSE_NOT_OPERATIONAL",
                "error": "This feature is not available yet.",
                "purpose": purpose_id,
            }), 410

        return disabled

    return decorate


def mlc3_service_required(function):
    """Expose the service loop only after rollout-aware DB enrollment.

    Authentication must wrap this decorator. A disabled or ineligible caller
    receives 404 so the surface is not discoverable. Legacy founder-pilot
    variables do not authorize this path.
    """
    @wraps(function)
    def gated(*args, **kwargs):
        from flask import request

        from services.coach_guidance_delivery import runtime_is_enabled
        from services.db import db, first_client_repository

        user_id = str(getattr(request, "user_id", "") or "")
        principal = db.get_owner_principal_for_user(user_id) if user_id else None
        principal_id = str((principal or {}).get("id") or "")
        if not runtime_is_enabled() or not principal_id:
            return jsonify({"code": "NOT_FOUND"}), 404
        enrollment = first_client_repository.ensure_service_enrollment(
            acquisition_principal_id=principal_id,
            owner_user_id=user_id,
            idempotency_key=(
                f"http-enrollment:{principal_id}:"
                f"{getattr(request, 'request_id', '') or 'request'}"
            ),
        )
        if not enrollment:
            return jsonify({"code": "NOT_FOUND"}), 404
        request.mlc3_principal_id = principal_id
        request.mlc3_rollout_revision_id = enrollment.get(
            "rollout_revision_id"
        )
        request.mlc3_enrollment_revision_id = enrollment.get("id")
        request.mlc3_operation_mode = enrollment.get("operation_mode")
        return function(*args, **kwargs)

    return gated


# Compatibility only for dormant imports. New runtime routes use the
# rollout-aware name above; both names execute the exact same guard.
mlc3_pilot_required = mlc3_service_required
