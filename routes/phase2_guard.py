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
