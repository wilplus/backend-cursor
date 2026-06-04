"""Snippet labeling endpoints. Admin-only.

GET  /admin/snippet-labels/next?limit=N  -> queue of unlabeled snippets for the current admin
POST /admin/snippet-labels                -> UPSERT a label
GET  /admin/snippet-labels/stats          -> throughput counters
"""
from __future__ import annotations

import logging
from typing import Any

import sentry_sdk
from flask import Blueprint, jsonify, request

from routes.admin import require_admin
from services import snippet_labels as snippet_labels_svc

logger = logging.getLogger(__name__)
snippet_labels_bp = Blueprint("snippet_labels", __name__)


def _current_admin_id() -> str | None:
    """Resolve the current admin's UUID from the JWT email on request.token_payload."""
    payload = getattr(request, "token_payload", None) or {}
    email = payload.get("email") if isinstance(payload, dict) else None
    if not email:
        return None
    return snippet_labels_svc.admin_id_for_email(email)


@snippet_labels_bp.route("/next", methods=["GET"])
@require_admin
def next_unlabeled():
    try:
        admin_id = _current_admin_id()
        if not admin_id:
            return jsonify({"code": "ADMIN_NOT_FOUND", "error": "Admin user not resolved"}), 403
        try:
            limit = int(request.args.get("limit", 1))
        except (TypeError, ValueError):
            limit = 1
        limit = max(1, min(limit, 50))
        snippets = snippet_labels_svc.list_unlabeled_for_admin(admin_id, limit=limit)
        return jsonify({"snippets": snippets, "limit": limit, "count": len(snippets)}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.exception("snippet_labels.next failed")
        return jsonify({"code": "SNIPPET_LABELS_ERROR", "error": str(e)}), 500


@snippet_labels_bp.route("/submit", methods=["POST"])
@require_admin
def submit_label():
    try:
        admin_id = _current_admin_id()
        if not admin_id:
            return jsonify({"code": "ADMIN_NOT_FOUND", "error": "Admin user not resolved"}), 403

        body: dict[str, Any] = request.get_json(silent=True) or {}
        snippet_id = body.get("snippet_id")
        charisma = body.get("charisma")
        stress = body.get("stress")
        notes = body.get("notes")
        confidence = body.get("confidence")

        if not snippet_id:
            return jsonify({"code": "BAD_REQUEST", "error": "snippet_id is required"}), 400

        try:
            row = snippet_labels_svc.upsert_label(
                snippet_id=snippet_id,
                admin_id=admin_id,
                charisma=charisma,
                stress=stress,
                notes=notes,
                confidence=confidence,
            )
        except ValueError as ve:
            return jsonify({"code": "BAD_REQUEST", "error": str(ve)}), 400

        return jsonify({"label": row}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.exception("snippet_labels.submit failed")
        return jsonify({"code": "SNIPPET_LABELS_ERROR", "error": str(e)}), 500


@snippet_labels_bp.route("/stats", methods=["GET"])
@require_admin
def stats():
    try:
        admin_id = _current_admin_id()
        if not admin_id:
            return jsonify({"code": "ADMIN_NOT_FOUND", "error": "Admin user not resolved"}), 403
        return jsonify(snippet_labels_svc.label_stats(admin_id)), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.exception("snippet_labels.stats failed")
        return jsonify({"code": "SNIPPET_LABELS_ERROR", "error": str(e)}), 500
