"""Bold voices, the once-per-Take after-practice steps and the heard
receipt: RETIRED (founder 2026-10-07, Q-B11 A, decisions log N62: "The
Album share switch and Bold voices are retired").

The three routes stay registered as 404 tombstones so the URL map keeps
its shape; each answers NOT_FOUND whatever ``PRAISE_AFTER_PRACTICE_ENABLED``
says, before any read or write (``services/bold_voices.py``). The
``bold_voices_plays`` and ``after_practice_steps`` tables are not dropped.
"""
from __future__ import annotations

from flask import jsonify

from auth import require_auth
from routes.v2.blueprint import v2_bp


def _retired():
    """Every call: 404, nothing read, nothing written."""
    return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404


@v2_bp.route("/user/takes/<take_session_id>/bold-voices", methods=["GET"])
@require_auth
def v2_bold_voices(take_session_id):
    """Retired (Q-B11 A): 404."""
    return _retired()


@v2_bp.route("/user/takes/<take_session_id>/after-practice-step", methods=["POST"])
@require_auth
def v2_after_practice_step(take_session_id):
    """Retired (Q-B11 A): 404."""
    return _retired()


@v2_bp.route("/user/takes/<take_session_id>/bold-voices/heard", methods=["POST"])
@require_auth
def v2_bold_voices_heard(take_session_id):
    """Retired (Q-B11 A): 404."""
    return _retired()
