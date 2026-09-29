"""Rings: the founder's rollout panel and the per-login read (0394).

/v2/admin/rings/*  — founder-gated exactly like the other admin routes
                     (@require_admin: the admin_users allow-list by token
                     email). Lists and writes; every write goes through one
                     SECURITY DEFINER RPC in services/rings.py.
/v2/user/rings     — what is on for the signed-in person and which
                     announcements are pending for them; their answer to one.

A route validates, authorises, calls one service function, serialises (the
route fence). Nothing here touches the F1 loop, surfaces a score, or creates
consent: an announcement decision is an answer to a sheet, and the feature
turns on only when the consent doors say yes (L3).
"""
from __future__ import annotations

import logging
from typing import Any

from flask import jsonify, request

from auth import require_auth
from routes.admin import require_admin
from routes.v2.blueprint import v2_bp
from services import rings
from utils.errors import safe_error

logger = logging.getLogger(__name__)


def _body() -> dict[str, Any]:
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise TypeError("JSON object required")
    return value


def _changed_by() -> str:
    return f"user:{getattr(request, 'user_id', '') or 'unknown'}"


def _refused(error: rings.RingsError):
    if error.code == "RINGS_UNAVAILABLE":
        return jsonify({"code": "RINGS_UNAVAILABLE",
                        "error": "Rings are temporarily unavailable."}), 503
    return jsonify({"code": error.code}), error.status


def _invalid(error: Exception):
    return jsonify({"code": "INVALID_INPUT", "error": str(error)}), 400


def _int_arg(name: str, default: int, *, low: int, high: int) -> int:
    try:
        value = int(request.args.get(name, str(default)))
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer") from None
    if not low <= value <= high:
        raise ValueError(f"{name} out of range")
    return value


# ── features ───────────────────────────────────────────────────────────────

@v2_bp.route("/admin/rings/features", methods=["GET"])
@require_admin
def v2_admin_rings_features():
    try:
        return jsonify(rings.list_features()), 200
    except Exception as exc:
        return safe_error("RINGS_ERROR", 500, exc=exc,
                          log="rings: list features failed")


@v2_bp.route("/admin/rings/features/<feature>", methods=["PUT"])
@require_admin
def v2_admin_rings_set_feature(feature: str):
    try:
        row = rings.set_feature_ring(feature, _body(), changed_by=_changed_by())
        return jsonify({"feature": row}), 200
    except rings.RingsError as error:
        return _refused(error)
    except (TypeError, ValueError) as error:
        return _invalid(error)


@v2_bp.route("/admin/rings/features/<feature>/kill", methods=["POST"])
@require_admin
def v2_admin_rings_kill_feature(feature: str):
    try:
        row = rings.kill_feature(feature, _body().get("killed"),
                                 changed_by=_changed_by())
        return jsonify({"feature": row}), 200
    except rings.RingsError as error:
        return _refused(error)
    except (TypeError, ValueError) as error:
        return _invalid(error)


# ── people ─────────────────────────────────────────────────────────────────

@v2_bp.route("/admin/rings/people", methods=["GET"])
@require_admin
def v2_admin_rings_people():
    try:
        limit = _int_arg("limit", 50, low=1, high=200)
        offset = _int_arg("offset", 0, low=0, high=100_000)
        ring_arg = request.args.get("ring", "").strip()
        ring = int(ring_arg) if ring_arg else None
        filters = {key: request.args.get(key, "").strip()
                   for key in rings.ATTRIBUTE_KEYS}
        return jsonify(rings.list_people(
            search=request.args.get("search", ""), filters=filters,
            ring=ring, limit=limit, offset=offset,
        )), 200
    except (TypeError, ValueError) as error:
        return _invalid(error)
    except Exception as exc:
        return safe_error("RINGS_ERROR", 500, exc=exc,
                          log="rings: list people failed")


@v2_bp.route("/admin/rings/people/<principal_id>", methods=["PUT"])
@require_admin
def v2_admin_rings_set_person(principal_id: str):
    try:
        row = rings.set_principal_ring(principal_id, _body(),
                                       changed_by=_changed_by())
        return jsonify({"person": row}), 200
    except rings.RingsError as error:
        return _refused(error)
    except (TypeError, ValueError) as error:
        return _invalid(error)


@v2_bp.route("/admin/rings/people/bulk", methods=["POST"])
@require_admin
def v2_admin_rings_set_people_bulk():
    try:
        body = _body()
        result = rings.set_principal_rings_bulk(
            body.get("principal_ids"), body.get("ring"),
            changed_by=_changed_by())
        return jsonify(result), 200
    except rings.RingsError as error:
        return _refused(error)
    except (TypeError, ValueError) as error:
        return _invalid(error)


# ── defaults ───────────────────────────────────────────────────────────────

@v2_bp.route("/admin/rings/default", methods=["GET"])
@require_admin
def v2_admin_rings_get_default():
    return jsonify({"default_ring": rings.get_default_ring(),
                    "attribute_keys": list(rings.ATTRIBUTE_KEYS)}), 200


@v2_bp.route("/admin/rings/default", methods=["PUT"])
@require_admin
def v2_admin_rings_set_default():
    try:
        row = rings.set_default_ring(_body().get("ring"), changed_by=_changed_by())
        return jsonify({"default_ring": row.get("value"), "setting": row}), 200
    except rings.RingsError as error:
        return _refused(error)
    except (TypeError, ValueError) as error:
        return _invalid(error)


@v2_bp.route("/admin/rings/me", methods=["GET"])
@require_admin
def v2_admin_rings_me():
    """The founder's own ring row, for the Defaults tab's "your own ring"."""
    user_id = str(getattr(request, "user_id", "") or "")
    state = rings.features_on_for_user(user_id)
    state["user_id"] = user_id
    return jsonify(state), 200


# ── announcements ──────────────────────────────────────────────────────────

@v2_bp.route("/admin/rings/announcements", methods=["GET"])
@require_admin
def v2_admin_rings_announcements():
    try:
        return jsonify({"announcements": rings.list_announcements()}), 200
    except Exception as exc:
        return safe_error("RINGS_ERROR", 500, exc=exc,
                          log="rings: list announcements failed")


@v2_bp.route("/admin/rings/announcements/<feature>", methods=["PUT"])
@require_admin
def v2_admin_rings_set_announcement(feature: str):
    try:
        row = rings.set_announcement(feature, _body(), changed_by=_changed_by())
        return jsonify({"announcement": row}), 200
    except rings.RingsError as error:
        return _refused(error)
    except (TypeError, ValueError) as error:
        return _invalid(error)


# ── audit ──────────────────────────────────────────────────────────────────

@v2_bp.route("/admin/rings/audit", methods=["GET"])
@require_admin
def v2_admin_rings_audit():
    try:
        limit = _int_arg("limit", 100, low=1, high=500)
        return jsonify({"changes": rings.list_changes(limit=limit)}), 200
    except (TypeError, ValueError) as error:
        return _invalid(error)


# ── the per-login read ─────────────────────────────────────────────────────

@v2_bp.route("/user/rings", methods=["GET"])
@require_auth
def v2_user_rings():
    """features_on and pending_announcements for the signed-in person.

    Carries the person's own ring and the features on for them, never a
    score or anyone else's row. Missing principal or unreachable ring
    tables answer an empty, marked payload: the app loads regardless.
    """
    state = rings.features_on_for_user(getattr(request, "user_id", None))
    response = jsonify(state)
    response.headers["Cache-Control"] = "no-store"
    return response, 200


@v2_bp.route("/user/rings/announcements/<feature>/decision", methods=["POST"])
@require_auth
def v2_user_rings_announcement_decision(feature: str):
    """The person's answer to an announcement: accepted or not_now.

    It records the answer and nothing else. It does NOT record consent: a
    feature with a consent purpose turns on only when the consent routes
    have recorded that consent and the check sees it (L3).
    """
    try:
        principal = rings.principal_for_user(getattr(request, "user_id", None))
        row = rings.record_announcement_decision(
            principal, feature, _body().get("decision"))
        return jsonify({"decision": row}), 200
    except rings.RingsError as error:
        return _refused(error)
    except (TypeError, ValueError) as error:
        return _invalid(error)
