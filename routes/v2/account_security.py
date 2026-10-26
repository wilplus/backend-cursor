"""Email and password on Data & consent (WIL-95; founder 2026-10-26, N187).
Service: services/account_security.py.

  GET  /v2/account/sign-in                 {email, has_password, provider}
  POST /v2/account/email                   {new_email, current_password?}; {sent_to}
  POST /v2/account/email/confirm           {token}; {email}   (no sign-in: the link)
  POST /v2/account/password                {current_password, new_password}; {changed}
  POST /v2/account/password/link           {}; {sent_to, kind: reset | set}
  POST /v2/account/password/link-used      {}; {event}

Every request, change and wrong password is a row in account_security_events.
The confirm route needs no sign-in, because the link may be opened on
another device: the one-time token is the proof, and it is rate-limited by
IP address.
"""
import logging

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from routes.v2.common import _client_ip_from_request
from services.rate_limits import client_ip, identity_key, limiter

logger = logging.getLogger(__name__)

# A person changes these rarely; a burst is someone guessing a password.
_CHANGES = "10 per hour"
_LINKS = "30 per hour"


def _caller():
    from services.account_security import Caller
    header = request.headers.get("Authorization") or ""
    return Caller(user_id=str(request.user_id),
                  jwt=header.replace("Bearer ", "", 1).strip(),
                  ip=_client_ip_from_request(),
                  user_agent=request.headers.get("User-Agent"))


def _body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _run(label: str, work):
    """The service's refusal as it is; anything else a 500 that is logged."""
    from services.account_security import AccountError, Ports
    try:
        return jsonify(work(Ports())), 200
    except AccountError as e:
        return jsonify({"code": e.code, "error": str(e)}), e.status
    except Exception as e:
        logger.error("account security %s failed: %s", label, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Couldn’t save that."}), 500


@v2_bp.route("/account/sign-in", methods=["GET"])
@require_auth
def v2_account_sign_in():
    from services.account_security import state
    caller = _caller()
    return _run("state", lambda ports: state(ports, caller))


@v2_bp.route("/account/email", methods=["POST"])
@limiter.limit(_CHANGES, key_func=identity_key, scope="account_security")
@require_auth
def v2_account_change_email():
    from services.account_security import change_email
    caller, body = _caller(), _body()
    return _run("email", lambda ports: change_email(
        ports, caller, body.get("new_email"), body.get("current_password")))


@v2_bp.route("/account/email/confirm", methods=["POST"])
@limiter.limit(_LINKS, key_func=client_ip, scope="account_email_confirm")
def v2_account_confirm_email():
    from services.account_security import confirm_email
    token = _body().get("token")
    ip, agent = _client_ip_from_request(), request.headers.get("User-Agent")
    return _run("confirm", lambda ports: confirm_email(ports, token, ip, agent))


@v2_bp.route("/account/password", methods=["POST"])
@limiter.limit(_CHANGES, key_func=identity_key, scope="account_security")
@require_auth
def v2_account_change_password():
    from services.account_security import change_password
    caller, body = _caller(), _body()
    return _run("password", lambda ports: change_password(
        ports, caller, body.get("current_password"), body.get("new_password")))


@v2_bp.route("/account/password/link", methods=["POST"])
@limiter.limit(_CHANGES, key_func=identity_key, scope="account_security")
@require_auth
def v2_account_password_link():
    from services.account_security import send_password_link
    caller = _caller()
    return _run("link", lambda ports: send_password_link(ports, caller))


@v2_bp.route("/account/password/link-used", methods=["POST"])
@limiter.limit(_CHANGES, key_func=identity_key, scope="account_security")
@require_auth
def v2_account_password_link_used():
    from services.account_security import password_link_used
    caller = _caller()
    return _run("link used", lambda ports: password_link_used(ports, caller))
