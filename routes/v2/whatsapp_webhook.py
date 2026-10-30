"""Replies to our WhatsApp number: STOP turns the messages off (founder
2026-10-28, N237); any other reply is emailed to the founder while
WHATSAPP_FORWARD_REPLIES is on (2026-10-29, N265). Logic in
services/whatsapp_notify.py.

  GET  /v2/whatsapp/webhook   Meta's check when the webhook is set: answers
                              hub.challenge when hub.verify_token matches
                              WHATSAPP_WEBHOOK_VERIFY_TOKEN
  POST /v2/whatsapp/webhook   Meta only, signed with WHATSAPP_APP_SECRET
                              (X-Hub-Signature-256)

No user JWT: Meta calls it. 503 while either key is unset, so the door is
shut by default; 403 for a wrong verify token, 401 for a delivery Meta did
not sign. A 200 tells Meta the delivery arrived; a 500 makes Meta send it
again.
"""
import hmac
import logging

from flask import jsonify, request

from routes.v2.blueprint import v2_bp

logger = logging.getLogger(__name__)


@v2_bp.route("/whatsapp/webhook", methods=["GET", "POST"])
def v2_whatsapp_webhook():
    from config import Config
    from services.db import db
    from services.whatsapp_notify import handle_replies, signed_by_meta
    token = (Config.WHATSAPP_WEBHOOK_VERIFY_TOKEN or "").strip()
    secret = (Config.WHATSAPP_APP_SECRET or "").strip()
    if not (token and secret):
        return jsonify({"code": "NOT_CONFIGURED", "error": "The WhatsApp webhook is not set up"}), 503
    if request.method == "GET":
        if (request.args.get("hub.mode") == "subscribe"
                and hmac.compare_digest(request.args.get("hub.verify_token") or "", token)):
            return request.args.get("hub.challenge") or "", 200, {"Content-Type": "text/plain"}
        return jsonify({"code": "FORBIDDEN", "error": "Wrong verify token"}), 403
    body = request.get_data(cache=True)
    if not signed_by_meta(secret, body, request.headers.get("X-Hub-Signature-256") or ""):
        return jsonify({"code": "UNAUTHORIZED", "error": "Not signed by Meta"}), 401
    try:
        handle_replies(db, request.get_json(silent=True) or {})
    except Exception as e:
        logger.error("whatsapp webhook failed: %s", type(e).__name__, exc_info=True)
        return jsonify({"code": "V2_ERROR", "error": "Try again"}), 500
    return jsonify({}), 200
