"""The bundled MLC-2 consent route, retired as a door (N48.5 Q27 A).

Until 2026-10-05 this route recorded the bundled two-purpose grant
(``accept_mlc2_founder_consent_v1`` → ``record_mlc2_consent_grant_v1``) that
admitted a person into the confidence chain. The founder's answer of that
day ("the confidence-learning chain is connected: one consent authority (the
training yes)") and the earlier locks (N2 / C2: the v1 grant and withdrawal
functions do not stay; N10 item 6: bundled-era yeses count for nothing) make
the training yes the only authority: ``/v2/user/training-consent`` on its own
screen, read through ``get_mlc2_training_consent_status_v2`` (migration
0430). So this route records no new bundled grant.

It still answers, because two screens read it: the founder gate in front of
the Lounge and ``/account/model-improvement``. And it keeps one write: a
person who holds a bundled grant can still withdraw it. Withdrawing is never
harder than agreeing was, and only the v1 withdrawal can withdraw a bundled
grant (0373 built the v2 one for training grants alone, by design).

  GET     a holder of an active bundled grant: applicable and granted, so the
          page offers the withdrawal; anyone else: not applicable. Never an
          error: the founder gate reads this before the Lounge, and an error
          there would stop recording (LIVE LOOP).
  POST    410 ``BUNDLED_CONSENT_RETIRED``. Nothing is written. The training
          yes is its own act on its own screen (N10, N15).
  DELETE  a holder's withdrawal (``record_mlc2_consent_withdrawal_v1``);
          anyone else gets the not-applicable status. Neither the ring nor
          the writer state can stand in front of a withdrawal.

The browser never writes canonical tables; responses carry no internal id.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from services.db import db


logger = logging.getLogger(__name__)
_SOURCE_ROUTE = "/v2/user/mlc2-consent"
_CLIENT_VERSION_FALLBACK = "willab-web-unknown"
RETIRED_CODE = "BUNDLED_CONSENT_RETIRED"

_NOT_APPLICABLE = {
    "applicable": False,
    "configured": False,
    "granted": False,
    "retired": True,
}


def _client_version() -> str:
    value = str(
        request.headers.get("X-Willab-Client-Version")
        or _CLIENT_VERSION_FALLBACK
    ).strip()
    return value[:120] or _CLIENT_VERSION_FALLBACK


def _public_status(status: dict) -> dict:
    return {
        "applicable": True,
        "retired": True,
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


def _principal_id() -> str | None:
    """The caller's existing owner principal, read only: a retired door
    creates nothing, not even a principal."""
    user_id = str(getattr(request, "user_id", "") or "").strip()
    if not user_id:
        return None
    try:
        principal = db.get_owner_principal_for_user(user_id) or {}
    except Exception:  # noqa: BLE001 - unknown reads as not applicable
        logger.warning("bundled consent: principal read failed", exc_info=True)
        return None
    value = str(principal.get("id") or "").strip()
    return value or None


def _held_grant(principal_id: str | None) -> dict | None:
    """The bundled status when this person still holds an active bundled
    grant, else None. Any failure of the v1 reader (it raises when more than
    one bundled policy is active) reads as "holds none"."""
    if not principal_id:
        return None
    try:
        status = db.get_mlc2_principal_consent_status(principal_id) or {}
    except Exception:  # noqa: BLE001 - never an error on this route
        logger.warning("bundled consent: status read failed", exc_info=True)
        return None
    if status.get("configured") and status.get("granted") \
            and status.get("grant_event_id"):
        return status
    return None


@v2_bp.route("/user/mlc2-consent", methods=["GET", "POST", "DELETE"])
@require_auth
def v2_user_mlc2_consent():
    """Read or withdraw a bundled-era grant; never record one."""
    if request.method == "POST":
        # A code only, no words: the words are the frontend's (as on the
        # training switch), and no screen posts here once GET never answers
        # "applicable but not granted".
        return jsonify({"code": RETIRED_CODE}), 410

    principal_id = _principal_id()
    held = _held_grant(principal_id)
    if request.method == "GET" or held is None or principal_id is None:
        return jsonify(_public_status(held) if held else _NOT_APPLICABLE), 200

    body = request.get_json(silent=True)
    idempotency_key = str((body or {}).get("idempotency_key") or "").strip() \
        if isinstance(body, dict) else ""
    if not idempotency_key or len(idempotency_key) > 200:
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "A bounded idempotency_key is required.",
        }), 400
    try:
        withdrawal = db.record_mlc2_consent_withdrawal(
            acquisition_principal_id=principal_id,
            grant_event_id=str(held["grant_event_id"]),
            source_route=_SOURCE_ROUTE,
            client_version=_client_version(),
            affirmative_action={
                "withdrawn": True,
                "service_access_ends": True,
            },
            occurred_at=datetime.now(timezone.utc).isoformat(),
            idempotency_key=idempotency_key,
        )
        if not withdrawal:
            raise RuntimeError("consent withdrawal was not persisted")
    except Exception as error:
        logger.error("bundled consent withdrawal failed: %s", error, exc_info=True)
        sentry_sdk.capture_exception(error)
        return jsonify({
            "code": "MLC2_CONSENT_FAILED",
            "error": "We could not save this consent safely. Please try again.",
        }), 500
    still = _held_grant(principal_id)
    return jsonify(_public_status(still) if still else _NOT_APPLICABLE), 200
