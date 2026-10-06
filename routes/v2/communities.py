"""Communities (founder 2026-10-06, decisions log N52.4; migration 0432): set
up or join a community, share a Take with communities, the listener's queue
and their answers. Every route answers 404 while ``COMMUNITIES_ENABLED`` is
off, checked before any read; sharing also waits for
``COMMUNITY_SHARE_POLICY_VERSION`` (CM2). Error codes only, no copy. The
work is ``services.communities``'.
"""
from __future__ import annotations

import logging

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from routes.v2.common import _is_valid_uuid
from services.db import db
from services.rate_limits import heavy_limit

logger = logging.getLogger(__name__)


def _off():
    """The switch, read before anything else: off, every route is 404."""
    from services.communities import communities_enabled
    if communities_enabled():
        return None
    return jsonify({"code": "NOT_FOUND"}), 404


def _run(name: str, call):
    try:
        status, payload = call()
    except Exception as e:
        logger.error("%s failed: %s", name, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR"}), 500
    return jsonify(payload), status


@v2_bp.route("/user/communities", methods=["POST"])
@heavy_limit
@require_auth
def v2_community_create():
    """Body {name, pass_code}: set up a private community; its creator is
    its owner. 201 · 400 · 409 PASS_CODE_TAKEN · 503 PASS_CODES_UNAVAILABLE."""
    off = _off()
    if off:
        return off
    from services.communities import create_community
    return _run("community create", lambda: create_community(
        db, owner_user_id=str(request.user_id), body=request.get_json(silent=True)))


@v2_bp.route("/user/communities/join", methods=["POST"])
@heavy_limit
@require_auth
def v2_community_join():
    """Body {pass_code}: join a private community by its pass code alone.
    200 · 400 · 404 COMMUNITY_NOT_FOUND · 503 PASS_CODES_UNAVAILABLE."""
    off = _off()
    if off:
        return off
    from services.communities import join_community
    return _run("community join", lambda: join_community(
        db, user_id=str(request.user_id), body=request.get_json(silent=True)))


@v2_bp.route("/user/communities", methods=["GET"])
@require_auth
def v2_communities_list():
    """The general community and the private ones the speaker belongs to."""
    off = _off()
    if off:
        return off
    from services.communities import list_my_communities
    return _run("communities list", lambda: list_my_communities(
        db, user_id=str(request.user_id)))


@v2_bp.route("/user/takes/<take_id>/share", methods=["PUT"])
@require_auth
def v2_take_share(take_id):
    """Body {general, community_ids, none}: share this Take with the
    communities chosen and withdraw it from the rest; "none" stands alone
    and withdraws it from every community. 409 TERMS_REACCEPT_REQUIRED
    until the sharing policy version exists and the speaker is on it."""
    off = _off()
    if off:
        return off
    from services.communities import share_take
    if not _is_valid_uuid(take_id):
        return jsonify({"code": "INVALID_INPUT"}), 400
    return _run("take share", lambda: share_take(
        db, owner_user_id=str(request.user_id), take_session_id=take_id,
        body=request.get_json(silent=True)))


@v2_bp.route("/user/communities/queue", methods=["GET"])
@require_auth
def v2_community_queue():
    """The listener's clips: their communities' first, then training clips.
    Audio only."""
    off = _off()
    if off:
        return off
    from services.communities import queue_for
    return _run("community queue", lambda: queue_for(
        db, listener_id=str(request.user_id)))


@v2_bp.route("/user/communities/answers", methods=["POST"])
@require_auth
def v2_community_answer():
    """Body {clip_id, value}: one of the five answers on one clip of the
    queue, once per person per clip; never the listener's own."""
    off = _off()
    if off:
        return off
    from services.communities import answer
    return _run("community answer", lambda: answer(
        db, listener_id=str(request.user_id), body=request.get_json(silent=True)))
