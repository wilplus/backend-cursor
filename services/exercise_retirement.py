"""Retire or bring back one library exercise.

Retiring is the active flag the serving read already honours; the row, its
versions and its history stay. Founder-only (coach panel lock CP3 A, the
founder's Library page).
"""
from __future__ import annotations

import logging
from typing import Any

from services.diagnostic_exercise_catalogue import EXERCISE_ID_SHAPE

logger = logging.getLogger(__name__)


def set_exercise_active(database: Any, exercise_id: Any, body: Any) -> tuple[int, dict]:
    """Retire or bring back one exercise.

    Retiring is the active flag the serving read already honours; the row,
    its versions and its history stay. Founder-only (coach panel lock CP3 A,
    the founder's Library page).
    """
    if not isinstance(body, dict) or not isinstance(body.get("active"), bool):
        return 400, {"code": "INVALID_INPUT", "error": "active must be true or false"}
    active = body["active"]
    eid = str(exercise_id or "")
    if EXERCISE_ID_SHAPE.match(eid) is None:
        return 400, {"code": "INVALID_INPUT", "error": "unknown exercise id"}
    row = database.get_diagnostic_exercise(eid)
    if not isinstance(row, dict):
        return 404, {"code": "NOT_FOUND", "error": "exercise not found"}
    if active:
        if not row.get("explanation_video_url"):
            return 409, {
                "code": "NEEDS_VIDEO",
                "error": "add the exercise's video before bringing it back",
            }
        post_id = row.get("journal_post_id")
        if post_id:
            post = database.get_journal_post_by_id(post_id)
            if not isinstance(post, dict) or post.get("status") != "published":
                return 409, {
                    "code": "POST_NOT_PUBLISHED",
                    "error": "publish the post before bringing the exercise back",
                }
    if bool(row.get("active")) == active:
        return 200, {"exercise_id": eid, "active": active, "changed": False}
    saved = database.set_diagnostic_exercise_active(eid, active)
    if not isinstance(saved, dict):
        return 500, {"code": "V2_ERROR", "error": "could not save"}
    logger.info("exercise %s active=%s", eid, active)
    return 200, {"exercise_id": eid, "active": active, "changed": True}
