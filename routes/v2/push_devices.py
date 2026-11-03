"""Push to the iPhone app (N385): the app's address for Apple's push service.
Service: services/push_devices.py.

  POST   /v2/user/push-device  {token}  kept for the caller   {ok: true}
  DELETE /v2/user/push-device  {token}  forgotten (sign-out)  {ok: true}

A token that is not Apple's hex device token is 400 NOT_ALLOWED. No speaker
content and no provider call: only where to reach a phone.
"""
import logging

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from services.db import db

logger = logging.getLogger(__name__)


def _run(label: str, work):
    from services.push_devices import PushDeviceError
    try:
        return jsonify(work()), 200
    except PushDeviceError as e:
        return jsonify({"code": e.code, "error": str(e)}), e.status
    except Exception as e:
        logger.error("push device %s failed: %s", label, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to keep the device"}), 500


@v2_bp.route("/user/push-device", methods=["POST"])
@require_auth
def v2_push_device_save():
    from services.push_devices import save
    body = request.get_json(silent=True)
    return _run("save", lambda: save(db, str(request.user_id), body))


@v2_bp.route("/user/push-device", methods=["DELETE"])
@require_auth
def v2_push_device_remove():
    from services.push_devices import remove
    body = request.get_json(silent=True)
    return _run("remove", lambda: remove(db, str(request.user_id), body))
