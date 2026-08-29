"""Founder-only MLC-2 bundled-consent surface for Slice 6A.

The browser never writes canonical tables. A verified Supabase subject is
resolved to one acquisition principal, then service-role RPCs append speaker
and consent provenance. The Confidence producer remains dark.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from config import Config
from routes.phase2_guard import phase2_learning_disabled
from routes.v2.blueprint import v2_bp
from services.db import db
from services.project_repository import ProjectOwnershipError, ProjectRepository


logger = logging.getLogger(__name__)
config = Config()
_repository = ProjectRepository(db)
_SOURCE_ROUTE = "/v2/user/mlc2-consent"
_CLIENT_VERSION_FALLBACK = "willab-web-unknown"


def _founder_request() -> bool:
    payload = getattr(request, "token_payload", None) or {}
    email = str(payload.get("email") or "").strip().lower()
    return bool(
        email
        and email == str(config.ADMIN_EMAIL or "").strip().lower()
        and email == str(
            config.MLC2_CONFIDENCE_CANARY_FOUNDER_EMAIL or ""
        ).strip().lower()
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _identity_coordinates(user_id: str) -> tuple[str, str]:
    payload = getattr(request, "token_payload", None) or {}
    issuer = str(payload.get("iss") or "supabase").strip()
    subject = str(payload.get("sub") or user_id).strip()
    identity = _sha256(f"supabase-auth-sub-v1:{issuer}:{subject}")
    proof = _sha256(
        "verified-account-link-v1:"
        f"{issuer}:{subject}:{str(payload.get('email') or '').strip().lower()}"
    )
    return identity, proof


def _client_version() -> str:
    value = str(
        request.headers.get("X-Willab-Client-Version")
        or _CLIENT_VERSION_FALLBACK
    ).strip()
    return value[:120] or _CLIENT_VERSION_FALLBACK


def _public_status(status: dict, *, applicable: bool = True) -> dict:
    return {
        "applicable": applicable,
        "configured": bool(status.get("configured")),
        "granted": bool(status.get("granted")),
        "speaker_bound": bool(status.get("speaker_bound")),
        "consent_policy_version": status.get("consent_policy_version"),
        "required_for_service": bool(status.get("required_for_service")),
        "bundled_ui": bool(status.get("bundled_ui")),
        "approval_reference": status.get("approval_reference"),
        "approved_copy_sha256": status.get("approved_copy_sha256"),
        "onboarding_copy": status.get("onboarding_copy"),
        "terms_version": status.get("terms_version"),
        "privacy_policy_version": status.get("privacy_policy_version"),
        "article_6_basis": status.get("article_6_basis"),
        "article_9_treatment": status.get("article_9_treatment"),
    }


def _owner_and_status() -> tuple[str, dict]:
    user_id = str(getattr(request, "user_id", "")).strip()
    if not user_id:
        raise ProjectOwnershipError("verified auth subject is missing")
    owner = _repository.owner_for_user(user_id)
    status = db.get_mlc2_principal_consent_status(owner.id)
    if not status:
        raise RuntimeError("canonical consent status is unavailable")
    return owner.id, status


@v2_bp.route("/user/mlc2-consent", methods=["GET", "POST", "DELETE"])
@phase2_learning_disabled
@require_auth
def v2_user_mlc2_consent():
    """Read, explicitly grant, or explicitly withdraw founder consent.

    Ordinary accounts receive ``applicable=false`` and are not modified. The
    founder's principal may be established from verified auth on GET; consent
    is created only by POST with an affirmative checkbox action.
    """
    if not _founder_request():
        return jsonify({
            "applicable": False,
            "configured": False,
            "granted": False,
        }), 200

    try:
        owner_id, status = _owner_and_status()
        if not status.get("configured"):
            return jsonify({
                "code": "MLC2_CONSENT_NOT_CONFIGURED",
                "error": "Model-improvement consent is not configured yet.",
            }), 503

        if request.method == "GET":
            return jsonify(_public_status(status)), 200

        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "Request body must be a JSON object.",
            }), 400
        idempotency_key = str(body.get("idempotency_key") or "").strip()
        if not idempotency_key or len(idempotency_key) > 200:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "A bounded idempotency_key is required.",
            }), 400

        now = datetime.now(timezone.utc).isoformat()
        if request.method == "DELETE":
            grant_event_id = str(status.get("grant_event_id") or "").strip()
            if not grant_event_id:
                return jsonify(_public_status(status)), 200
            withdrawal = db.record_mlc2_consent_withdrawal(
                acquisition_principal_id=owner_id,
                grant_event_id=grant_event_id,
                source_route=_SOURCE_ROUTE,
                client_version=_client_version(),
                affirmative_action={
                    "withdrawn": True,
                    "service_access_ends": True,
                },
                occurred_at=now,
                idempotency_key=idempotency_key,
            )
            if not withdrawal:
                raise RuntimeError("consent withdrawal was not persisted")
            refreshed = db.get_mlc2_principal_consent_status(owner_id) or {}
            return jsonify(_public_status(refreshed)), 200

        if body.get("accepted") is not True:
            return jsonify({
                "code": "EXPLICIT_CONSENT_REQUIRED",
                "error": "The consent checkbox must be selected.",
            }), 400
        if body.get("consent_policy_version") != status.get(
            "consent_policy_version"
        ) or body.get("copy_sha256") != status.get("approved_copy_sha256"):
            return jsonify({
                "code": "CONSENT_VERSION_MISMATCH",
                "error": "The consent text changed. Please review it again.",
            }), 409

        identity_hash, proof_hash = _identity_coordinates(
            str(getattr(request, "user_id", ""))
        )
        consent = db.accept_mlc2_founder_consent(
            acquisition_principal_id=owner_id,
            identity_hash=identity_hash,
            identity_version="supabase-auth-sub-v1",
            binding_kind="verified_account_link",
            binding_proof_hash=proof_hash,
            bound_by="authenticated-founder-consent-v1",
            consent_policy_version=str(status["consent_policy_version"]),
            jurisdiction="PL/EU",
            terms_version=str(status["terms_version"]),
            privacy_policy_version=str(status["privacy_policy_version"]),
            source_route=_SOURCE_ROUTE,
            client_version=_client_version(),
            affirmative_action={
                "accepted": True,
                "copy_sha256": status["approved_copy_sha256"],
                "purposes": [
                    "personalized_coaching",
                    "pooled_model_improvement",
                ],
                "checkbox_preselected": False,
            },
            occurred_at=now,
            article_9_applies=(
                status.get("article_9_treatment")
                == "9(2)(a)_when_special_category"
            ),
            idempotency_key=idempotency_key,
        )
        if not consent:
            raise RuntimeError("consent grant was not persisted")
        refreshed = db.get_mlc2_principal_consent_status(owner_id) or {}
        return jsonify(_public_status(refreshed)), 200

    except ProjectOwnershipError as error:
        logger.error("founder principal resolution failed: %s", error)
        sentry_sdk.capture_exception(error)
        return jsonify({
            "code": "PRINCIPAL_UNAVAILABLE",
            "error": "Your verified owner identity could not be prepared.",
        }), 503
    except Exception as error:
        logger.error("MLC-2 founder consent failed: %s", error, exc_info=True)
        sentry_sdk.capture_exception(error)
        return jsonify({
            "code": "MLC2_CONSENT_FAILED",
            "error": "We could not save this consent safely. Please try again.",
        }), 500
