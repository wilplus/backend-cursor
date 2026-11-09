"""Will's voice in the walk (founder 2026-11-09, N560).
Service: services/walk_voice.py.

  POST /v2/walk-voice   {take_id, step, snippet_id?, conversation?}:
                        Will's message for that step of the walk,
                        {text: "..." | null}. null: the walk says its
                        signed line (the writer is off for this speaker,
                        late, failed, or its words failed the check).
"""
import logging

from flask import jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from services.db import db

logger = logging.getLogger(__name__)


@v2_bp.route("/walk-voice", methods=["POST"])
@require_auth
def v2_walk_voice():
    from services.walk_voice import write
    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else {}
    text = write(db, str(request.user_id), body.get("take_id"), body.get("step"),
                 body.get("snippet_id"), body.get("conversation"))
    return jsonify({"text": text}), 200
