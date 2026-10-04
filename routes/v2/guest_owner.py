"""A guest reads and works on their own Ideal Text page (F1 Repair Plan
Phase 0.6, founder 2026-10-04).

The founder, after recording as a brand-new guest: "it makes no sense. You
need to show the full feedback ... and then when they want to practice, then
show you need to sign up. That should be the order."

Until now every route behind the Ideal Text page was ``require_auth`` and
matched ownership on ``v2_sessions.user_id``. A guest's Take carries no
``user_id`` -- only ``owner_principal_id`` -- so a guest who had just recorded
could see nothing but plain text, and a guest is who meets the product first.

ONE DECORATOR, ONE IDENTITY RULE.

* ``require_owner_or_guest`` behaves exactly like ``require_auth`` whenever an
  ``Authorization`` header is present: a signed-in caller is never treated as
  a guest, and a bad token is still a 401, never a fallback.
* Without one, it accepts the signed guest owner token
  (``X-Willab-Guest-Owner``) and only when ``verify_guest_owner`` proves it:
  the principal exists, has no account yet, and the secret matches. A guest
  identity that has been claimed by an account stops working here at once.
* A verified guest's ``request.user_id`` is its principal id. That is the
  actor the publisher already uses for a guest Take (``_publishing_actor``
  falls back to ``owner_principal_id``), so the document a guest reads and
  the document the pipeline wrote are the same rows. ``claim_guest_owner``
  moves those rows to the account at sign-up (migration 0413).

``session_actor_id`` is the matching rule on the session side: the Take's
account when it has one, else its owner principal. A signed-in caller's id
is an auth user id and can never equal a principal id, and a guest's id is a
principal it has just proved, so a caller only ever matches their own Takes.

Practise, coach and Lounge routes stay account-only on purpose: sign-up is
the step in front of practise.
"""
from __future__ import annotations

import logging
from functools import wraps

from flask import jsonify, request

from auth import require_auth
from services.db import db
from services.project_ownership import (
    GUEST_OWNER_HEADER,
    parse_guest_owner_token,
    session_actor_id,
    verify_guest_owner,
)

__all__ = [
    "caller_is_guest",
    "require_owner_or_guest",
    "session_actor_id",
    "verified_guest_principal",
]

logger = logging.getLogger(__name__)


def verified_guest_principal(token: str | None) -> str | None:
    """The guest principal this token proves, or None."""
    parsed = parse_guest_owner_token(token)
    if not parsed:
        return None
    try:
        stored = db.get_owner_principal(parsed[0])
    except Exception as error:  # a read failure is a refusal, never a pass
        logger.warning("guest owner lookup failed: %s", error,
                       exc_info=True)
        return None
    return verify_guest_owner(token, stored)


def require_owner_or_guest(f):
    """``require_auth``, or a verified guest owner when no account is sent."""
    authed = require_auth(f)

    @wraps(f)
    def decorated(*args, **kwargs):
        request.guest_owner_principal_id = None
        if request.headers.get("Authorization"):
            return authed(*args, **kwargs)
        principal_id = verified_guest_principal(
            request.headers.get(GUEST_OWNER_HEADER))
        if not principal_id:
            return jsonify({"code": "UNAUTHORIZED",
                            "error": "Missing Authorization header"}), 401
        request.user_id = principal_id
        request.token_payload = None
        request.guest_owner_principal_id = principal_id
        return f(*args, **kwargs)

    return decorated


def caller_is_guest() -> bool:
    """True when this request was let in by a guest owner token."""
    return bool(getattr(request, "guest_owner_principal_id", None))
