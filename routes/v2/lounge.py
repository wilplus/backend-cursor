"""The Lounge thread persistence routes (BE contract 3.15).

  GET/POST/DELETE /v2/user/lounge/messages

Moved verbatim out of ``routes/v2_routes.py`` (god-file split, phase 3);
bodies are byte-identical. Routes register on the SAME ``v2_bp`` object, so
endpoint names and the URL map are unchanged.

Re-exported from ``routes.v2_routes`` for import compatibility.
"""
import logging

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from services.db import db

logger = logging.getLogger(__name__)


# ── willab beta — Lounge thread persistence (BE contract §3.15) ─────
#
# Per-user Lounge chat thread that survives reload + device switch.
# FE rehydrates on mount (GET, cursor-paged) and appends per turn
# (POST, idempotent batch — also the merge-on-signup path). Text only,
# never audio; never in the coach packet; never profiled (§2/AC-6).
#
# Validation + page shaping live in services/lounge_messages.py; the
# queries in services/db.py. These handlers are thin auth + wiring.


@v2_bp.route("/user/lounge/messages", methods=["GET"])
@require_auth
def v2_user_lounge_messages_get():
    """Rehydrate the Lounge thread (newest page) or page older.

    Query:
      limit  (default 50, max 200)  — page size
      before (ISO-8601, optional)   — cursor; rows strictly older than
                                      this. Absent → latest page.

    Response 200 (BE contract §3.15):
      {
        "messages": [ {id, client_id, role, kind, body, metadata,
                       client_created_at} ],   // ASC by client_created_at
        "has_more": bool,                       // older messages exist
        "oldest_cursor": "<iso>" | null         // pass as ?before= for
                                                // the next older page
      }

    No `before` → latest `limit` (bottom of thread). `before=<cursor>`
    → the page immediately older. Empty thread / missing table →
    empty page (the Lounge renders blank, never errors).
    """
    try:
        from services.lounge_messages import (
            LoungeValidationError,
            parse_limit,
            shape_lounge_page,
            validate_before_cursor,
        )

        limit = parse_limit(request.args.get("limit"))
        try:
            before = validate_before_cursor(request.args.get("before"))
        except LoungeValidationError as ve:
            return jsonify({"code": "INVALID_INPUT", "error": str(ve)}), 400

        rows_desc = db.get_lounge_messages_page(
            request.user_id, limit=limit, before=before,
        )
        return jsonify(shape_lounge_page(rows_desc, limit)), 200

    except Exception as e:
        logger.error(
            "user/lounge/messages GET failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        # Soft-fail to an empty page so the Lounge mounts rather than
        # showing an error on its home surface.
        return jsonify({
            "messages": [], "has_more": False, "oldest_cursor": None,
        }), 200


@v2_bp.route("/user/lounge/messages", methods=["POST"])
@require_auth
def v2_user_lounge_messages_post():
    """Idempotent batch append (also the merge-on-signup path).

    Body:
      { "messages": [ { client_id, role, kind, body, metadata?,
                        client_created_at } ] }

    The FE sends the user turn + bot reply together after each turn
    (FE-append, §7.6), and system lines as they happen. On signup it
    replays the localStorage thread as batches through THIS endpoint
    (§7.8 — no separate /merge alias); client_created_at preserves
    order, client_id prevents dupes.

    Idempotent on (user_id, client_id) — re-sending a stored client_id
    is a no-op upsert, not a duplicate.

    Responses:
      200 { "messages": [ ...persisted rows with server id ] }
      422 INVALID_INPUT — validator rejected (role/kind enum, non-UUID
                          client_id, bad client_created_at, batch over
                          200, body over cap)
      500 V2_ERROR — persist failed
    """
    try:
        from services.lounge_messages import (
            LoungeValidationError,
            validate_lounge_batch,
        )

        body = request.get_json(silent=True) or {}
        try:
            cleaned = validate_lounge_batch(body)
        except LoungeValidationError as ve:
            return jsonify({"code": "INVALID_INPUT", "error": str(ve)}), 422

        persisted = db.insert_lounge_messages(request.user_id, cleaned)
        if not persisted:
            return jsonify({
                "code": "V2_ERROR",
                "error": "Failed to persist lounge messages",
            }), 500

        logger.info(
            "user/lounge/messages.append user=%s count=%d",
            request.user_id, len(cleaned),
        )
        return jsonify({"messages": persisted}), 200

    except Exception as e:
        logger.error(
            "user/lounge/messages POST failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to append lounge messages",
        }), 500


@v2_bp.route("/user/lounge/messages", methods=["DELETE"])
@require_auth
def v2_user_lounge_messages_delete():
    """Clear the user's entire Lounge thread (BE contract §3.14 —
    user-deletable privacy commitment). Account deletion is handled
    separately by the ON DELETE CASCADE FK; this is the explicit
    'clear my Lounge' action.

    Responses:
      204 — thread cleared
      500 V2_ERROR — delete failed
    """
    try:
        ok = db.delete_lounge_messages_for_user(request.user_id)
        if not ok:
            return jsonify({
                "code": "V2_ERROR",
                "error": "Failed to clear lounge thread",
            }), 500
        logger.info("user/lounge/messages.cleared user=%s", request.user_id)
        return ("", 204)
    except Exception as e:
        logger.error(
            "user/lounge/messages DELETE failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to clear lounge thread",
        }), 500
