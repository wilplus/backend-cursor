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

    Until 2026-09-16 this returned 410 unconditionally — it named a registry
    purpose but never read it, so the switch and the fact it claimed to
    reflect were kept in step by hand. It now ASKS, which is what the
    paragraph above always said it did. An unreadable registry, a missing row,
    a phase-2 purpose or `operational = false` are all a closed door; only an
    explicit phase-1 operational row opens it. Flipping the row to false is
    therefore a working emergency stop that needs no deploy.
    """
    def decorate(function):
        @wraps(function)
        def gated(*args, **kwargs):
            from services.processing_purposes import purpose_is_operational

            if purpose_is_operational(purpose_id):
                return function(*args, **kwargs)
            return jsonify({
                "code": "PURPOSE_NOT_OPERATIONAL",
                "error": "This feature is not available yet.",
                "purpose": purpose_id,
            }), 410

        return gated

    return decorate


def consent_choice_required(choice: str):
    """Refuse the caller's request when their own choice says no.

    FOUNDER 2026-09-25 (E1): the "Personalised practice" tick was recorded
    and then read by nothing, so a person who left it empty still had
    exercises chosen from their recordings. This asks the one boundary that
    knows (ProcessingAuthorizationService.choice_permitted) about THIS caller,
    and nothing here decides the rule itself.

    It sits beside operational_purpose_disabled and does not replace it: that
    one asks whether the feature exists for anyone, this one whether this
    person said yes. Authentication must wrap it. A caller whose acquirer
    cannot be resolved is refused while the gate enforces, and passes the
    established path while it is off, the same rule the service applies.
    """
    def decorate(function):
        @wraps(function)
        def gated(*args, **kwargs):
            from flask import request

            from services.db import db
            from services.processing_authorization import (
                ProcessingAuthorizationService,
            )

            service = ProcessingAuthorizationService(db)
            user_id = getattr(request, "user_id", None)
            try:
                principal = (service.user_acquisition_principal(str(user_id))
                             if user_id else "")
            except Exception:
                principal = ""
            allowed = (service.choice_permitted(principal, choice)
                       if principal else not service.enforced)
            if allowed:
                return function(*args, **kwargs)
            return jsonify({
                "code": "CONSENT_CHOICE_OFF",
                "error": "This is turned off in your data choices.",
                "choice": choice,
            }), 403

        return gated

    return decorate


def ring_required(feature: str):
    """Expose a route to the people its ring row reaches (rings, 0392).

    Generalised from ``mlc3_service_required`` (founder 2026-09-29). Order:

    1. the building switch (``MLC3_SERVICE_ENABLED``) must be on, or the
       code does not even reach the check; a Railway variable stays the
       deeper kill for the day the database itself is distrusted;
    2. the caller must have an owner principal;
    3. ``feature_is_on_v1(feature, principal)`` must say yes: not killed,
       ring >= the row's ring, attribute rule matched, consent current
       when the row names a purpose (services/rings.py);
    4. then, unchanged, the MLC-3 enrollment wristband is issued and its
       coordinates are attached to the request, because the service loop's
       RPCs read them.

    Authentication must wrap this decorator. Every refusal is 404 so the
    surface is not discoverable. The old cohort and allow-list tables are
    kept and no longer read here; 0392 copied them into principal_rings.
    """
    def decorate(function):
        @wraps(function)
        def gated(*args, **kwargs):
            from flask import request

            from services import rings
            from services.coach_guidance_delivery import runtime_is_enabled
            from services.db import db, first_client_repository

            user_id = str(getattr(request, "user_id", "") or "")
            principal = db.get_owner_principal_for_user(user_id) if user_id else None
            principal_id = str((principal or {}).get("id") or "")
            if not runtime_is_enabled() or not principal_id:
                return jsonify({"code": "NOT_FOUND"}), 404
            if not rings.feature_is_on(feature, principal_id):
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
            request.ring_feature = feature
            return function(*args, **kwargs)

        return gated

    return decorate


# The MLC-3 service loop's row. Kept as a name so a dormant import still
# resolves; every runtime route now says which row it is behind.
mlc3_service_required = ring_required("exercise_service")

# Compatibility only for dormant imports. New runtime routes use the
# rollout-aware name above; both names execute the exact same guard.
mlc3_pilot_required = mlc3_service_required
