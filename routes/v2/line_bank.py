"""The signed line bank's rotation, for the Feedback walk (build plan D-FW-3;
founder lock 2026-10-06, the Feedback walk, "Line bank"; 0438).

"Within one bank the app never shows the same line twice in a row" for one
speaker, across reloads, Takes and devices. The walk reads which line each
bank says next as it opens, and records each line it shows
(services/line_rotation.py). Indexes into the signed banks only: no text, no
score, no read (AC-9).
"""
from __future__ import annotations

from flask import jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from services.db import db


@v2_bp.route("/user/line-bank", methods=["GET"])
@require_auth
def v2_user_line_bank():
    """200 {"next": {bank: index}}: the ordinary line each signed bank says
    next for the caller. {} when the memory cannot be read: the walk keeps
    its own turn and the loop never waits (LIVE LOOP)."""
    from services.line_rotation import upcoming

    return jsonify({"next": upcoming(db, user_id=request.user_id)}), 200


@v2_bp.route("/user/line-bank/shown", methods=["POST"])
@require_auth
def v2_user_line_bank_shown():
    """The walk showed a line of a bank (body {"bank"}): it is recorded as
    said. 200 {"bank", "index"}; 400 INVALID_INPUT; 503 V2_ERROR."""
    from services.line_rotation import shown

    status, body = shown(db, user_id=request.user_id,
                         body=request.get_json(silent=True))
    return jsonify(body), status
