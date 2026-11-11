"""Silent tries before a change: the founder's routes (N647 item 3).

"Catch more" or "Catch fewer" on one thing the walk notices runs silently
beside the live setting (``services.silent_tries``). The founder only, at
first; a host for their own chat later. A response carries the thing, the
direction, counts and words, never a threshold. "Use it" answers 404 while
the environment switch ``SILENT_TRY_USE_ENABLED`` is not "true" (off unless
set; counsel's C1 question first).

  GET  /v2/build/notice/<thing>/try                  the try and its counts
  POST /v2/build/notice/<thing>/try  {direction}     start: "more" | "fewer"
  POST /v2/build/notice/<thing>/try/<id>/drop        "Go back"
  POST /v2/build/notice/<thing>/try/<id>/use         "Use it" (behind the switch)
"""
from __future__ import annotations

import logging

from flask import jsonify, request

from routes.admin import require_founder
from routes.v2.blueprint import v2_bp
from services import silent_tries as st
from services.db import db

logger = logging.getLogger(__name__)

_REFUSED = {"thing_unknown": 404, "no_such_try": 404}


def _who() -> str:
    return str(getattr(request, "user_id", "") or "founder")


def _answer(call):
    try:
        return jsonify(call()), 200
    except st.TryRefused as refused:
        return jsonify({"code": refused.reason}), _REFUSED.get(refused.reason, 409)
    except Exception as e:
        logger.error("silent try failed: %s", e, exc_info=True)
        return jsonify({"code": "V2_ERROR", "error": "Could not do that."}), 500


@v2_bp.route("/build/notice/<thing>/try", methods=["GET"])
@require_founder
def v2_silent_try_status(thing):
    return _answer(lambda: st.status_for(db, thing))


@v2_bp.route("/build/notice/<thing>/try", methods=["POST"])
@require_founder
def v2_silent_try_start(thing):
    direction = str((request.get_json(silent=True) or {}).get("direction") or "")

    def go():
        st.start_for(db, thing, direction, by=_who())
        return st.status_for(db, thing)
    return _answer(go)


@v2_bp.route("/build/notice/<thing>/try/<try_id>/drop", methods=["POST"])
@require_founder
def v2_silent_try_drop(thing, try_id):
    def go():
        st.drop(db, thing, try_id=try_id, by=_who())
        return {"thing": thing, "try": None}
    return _answer(go)


@v2_bp.route("/build/notice/<thing>/try/<try_id>/use", methods=["POST"])
@require_founder
def v2_silent_try_use(thing, try_id):
    if not st.use_is_on():
        return jsonify({"code": "NOT_FOUND", "error": "Not available"}), 404

    def go():
        st.use_for(db, thing, try_id, by=_who())
        return {"thing": thing, "try": None, "used": True}
    return _answer(go)
