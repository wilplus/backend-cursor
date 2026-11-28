"""Founder-only calibration inside the AI Training chat."""
import logging
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
logger = logging.getLogger(__name__)

#: What the founder reads when ElevenLabs refuses (their own Training only):
#: the reason, so a key, credit or format problem can be fixed.
_VOICE_REASONS = {
    "missing_key": "ElevenLabs has no key set on the server.",
    "invalid_key": "ElevenLabs refused the key. Check that the key allows Speech to Speech.",
    "quota_exceeded": "ElevenLabs has no credits left on this key.",
    "rate_limited": "ElevenLabs is busy. Try again in a minute.",
    "not_found": "ElevenLabs can’t find your voice copy.",
    "outage": "ElevenLabs is unavailable right now.",
}


def _voice_refused(error):
    """The founder's own Training: say why ElevenLabs refused, never the key."""
    logger.warning("speaking calibration: ElevenLabs refused kind=%s status=%s code=%s",
                   error.kind, error.status, error.code)
    line = _VOICE_REASONS.get(error.kind) or "ElevenLabs refused the recording ({}).".format(
        error.code or error.status or "no reason given")
    return _json({"code": "VOICE_UNAVAILABLE", "reason": error.kind, "provider_code": error.code,
                  "error": line}, 503)


def _moment(take, snippet):
    user = str(request.user_id)
    valid = all(map(_is_valid_uuid, (take, snippet)))
    owned = owned_chat_moment(db, user, take, snippet) if valid else None
    if not owned and valid:
        # The founder's own acted recording (N708): AI Audio shapes it too.
        from services.acted_examples import acted_clip
        clip = acted_clip(db, user, take, snippet)
        owned = (None, clip) if clip else None
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
        if (upload := request.files.get("audio")) and request.form.get("action") == "revoice":
            response = send_file(BytesIO(speaking_calibration.revoice(db, user, take, moment, upload)),
                                 mimetype="audio/mpeg")
            response.headers["Cache-Control"] = "private, no-store"
            return response
        if upload:
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
    except VoiceProviderError as error:
        return _voice_refused(error)
