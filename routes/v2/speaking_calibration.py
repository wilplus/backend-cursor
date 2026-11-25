"""Founder-only calibration inside the AI Training chat."""
from io import BytesIO

from flask import jsonify, request, send_file

from routes.admin import require_founder
from routes.v2.blueprint import v2_bp
from routes.v2.common import _is_valid_uuid
from routes.v2.processing_authorization import phase1_provider_route
from services import speaking_calibration
from services.db import db
from services.elevenlabs_client import VoiceProviderError
from services.lounge_clips import owned_chat_moment
from services.processing_authorization import ProcessingAuthorizationError
from services.rate_limits import llm_limit
from services.refusal import Refusal
from services.will_question import QuestionError

_PATH = "/user/speaking-calibration/<take>/<snippet>"


def _moment(take, snippet):
    user = str(request.user_id)
    owned = owned_chat_moment(db, user, take, snippet) if all(map(_is_valid_uuid, (take, snippet))) else None
    if not owned or type(owned[1].get("duration_ms")) is not int or owned[1]["duration_ms"] <= 0:
        raise Refusal("NOT_FOUND", "This moment is unavailable.", 404)
    return user, owned[1]


def _json(payload, status=200):
    response = jsonify(payload)
    response.headers["Cache-Control"] = "private, no-store"
    return response, status


@v2_bp.route(_PATH, methods=["GET", "PUT"])
@require_founder
def v2_speaking_calibration(take, snippet):
    try:
        user, moment = _moment(take, snippet)
        if request.method == "GET":
            return _json(speaking_calibration.get(db, user, take, moment))
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _json({"code": "INVALID_INPUT"}, 400)
        return _json(*speaking_calibration.save(db, user, take, moment, body))
    except Refusal as error:
        return _json(error.body, error.status)


@v2_bp.route(_PATH + "/coach", methods=["POST"])
@require_founder
@phase1_provider_route
@llm_limit
def v2_speaking_calibration_coach(take, snippet):
    from routes.v2.voice_notebook import _adapter

    try:
        user, moment = _moment(take, snippet)
        if upload := request.files.get("audio"):
            return _json(speaking_calibration.listen(
                _adapter(user), user, take, moment, upload, check_pace=request.form.get("sniper") == "1",
            ))
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _json({"code": "INVALID_INPUT"}, 400)
        if body.get("action") == "example":
            data = speaking_calibration.example(db, user, take, moment, body)
            response = send_file(BytesIO(data), mimetype="audio/mpeg")
            response.headers["Cache-Control"] = "private, no-store"
            return response
        return _json(speaking_calibration.reply(db, user, take, moment, body))
    except Refusal as error:
        return _json(error.body, error.status)
    except (ProcessingAuthorizationError, QuestionError) as error:
        return _json({"code": error.code, "error": str(error)}, error.status)
    except VoiceProviderError:
        return _json({"code": "VOICE_UNAVAILABLE", "error": "ElevenLabs is unavailable right now."}, 503)
