"""Supabase's Send SMS hook: the sign-up and sign-in code goes out on
WhatsApp (founder 2026-10-27, N214). Logic in services/login_code.py.

  POST /v2/internal/auth/send-sms   Supabase only, signed with
                                    SEND_SMS_HOOK_SECRET (Standard Webhooks)

No user JWT: the person has no session yet. 503 while the secret is not
set, so the door is shut by default; 401 for a request without Supabase's
signature. An empty 200 tells Supabase the code went.
"""
import logging

from flask import jsonify, request

from routes.v2.blueprint import v2_bp

logger = logging.getLogger(__name__)


@v2_bp.route("/internal/auth/send-sms", methods=["POST"])
def v2_internal_send_login_code():
    from config import Config
    from services.login_code import HookRefusal, send, verify
    secret = (Config.SEND_SMS_HOOK_SECRET or "").strip()
    if not secret:
        return jsonify(HookRefusal(503, "SEND_SMS_HOOK_SECRET not configured").body), 503
    try:
        payload = verify(secret, request.headers, request.get_data(cache=True))
        send(payload)
    except HookRefusal as refusal:
        return jsonify(refusal.body), refusal.status
    except Exception as e:
        logger.error("send-sms hook failed: %s", type(e).__name__, exc_info=True)
        return jsonify(HookRefusal(500, "The code could not be sent").body), 500
    return jsonify({}), 200
