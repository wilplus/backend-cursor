"""Owner-only baseline pilot endpoints for the isolated app."""
from __future__ import annotations

import logging
from io import BytesIO

from flask import request, send_file
from sentry_sdk.integrations.logging import ignore_logger

from auth import require_auth
from routes.v2.blueprint import v2_bp
from routes.v2.chats import _recording_refused
from routes.v2.experiments import _json
from services import experiment_baseline as pilot
from services.db import db
from services.experiments import ExperimentsError
from services.rate_limits import limiter

_ROOT = "/experiments/baseline-pilot"
_STEP = _ROOT + "/runs/<run_id>/steps/<step_id>"
logger = logging.getLogger(__name__)
# Preserve operational logs locally without attaching Flask's report body to
# a logging event. The response itself contains a fixed, retryable error.
ignore_logger(__name__)


def _failure(label, exc):
    # Database failure details and stack locals can contain audio and reports.
    logger.error("baseline pilot %s failed (%s)", label, type(exc).__name__)
    return _json({"code": "PILOT_STORE", "error": "The pilot could not finish that request."}, 500)


def _run(label, work):
    try:
        return _json(work())
    except ExperimentsError as exc:
        return _json({"code": exc.code, "error": str(exc)}, exc.status)
    except Exception as exc:  # noqa: BLE001 - Never capture pilot errors with request data.
        return _failure(label, exc)


def _owner() -> str:
    user_id = str(getattr(request, "user_id", ""))
    pilot.enabled(user_id)
    return user_id


@v2_bp.route(_ROOT, methods=["GET", "DELETE"])
@require_auth
def v2_baseline_pilot():
    if request.method == "DELETE":
        return _run("baseline pilot erase", lambda: pilot.erase(db, _owner()))
    return _run("baseline pilot status", lambda: pilot.status(db, _owner(), request.args.get("language", "en")))


@v2_bp.route(_ROOT + "/runs", methods=["GET", "POST"])
@require_auth
def v2_baseline_runs():
    def work():
        owner = _owner()
        if request.method == "POST":
            return pilot.start_run(db, owner, request.get_json(silent=True))
        raw = request.args.get("offset", "0")
        if not (raw.isascii() and raw.isdecimal() and len(raw) <= 10):
            raise pilot.error("PILOT_INPUT", 400)
        return pilot.history(db, owner, request.args.get("mode", ""), int(raw))

    return _run("baseline pilot runs", work)


@v2_bp.route(_STEP + "/audio", methods=["PUT"])
@require_auth
@limiter.limit("40 per hour", scope="baseline_pilot_audio")
def v2_baseline_step_audio(run_id: str, step_id: str):
    def work():
        owner = _owner()
        refused = _recording_refused()
        if refused is not None:
            response, status = refused
            payload = response.get_json()
            raise ExperimentsError(payload["code"], payload["error"], status)
        upload = request.files.get("audio")
        if upload is None:
            raise pilot.error("PILOT_AUDIO_REQUIRED", 422)
        return pilot.save_audio(
            db, owner, run_id, step_id, audio=upload.stream.read(pilot.MAX_AUDIO_BYTES + 1),
            content_type=upload.mimetype or "", filename=upload.filename or "",
        )

    return _run("baseline pilot audio", work)


@v2_bp.route(_STEP + "/audio", methods=["GET"])
@require_auth
def v2_baseline_step_audio_read(run_id: str, step_id: str):
    try:
        audio, content_type = pilot.read_audio(db, _owner(), run_id, step_id)
    except ExperimentsError as exc:
        return _json({"code": exc.code, "error": str(exc)}, exc.status)
    except Exception as exc:  # noqa: BLE001 - Replay failures can carry private data.
        return _failure("audio replay", exc)
    response = send_file(BytesIO(audio), mimetype=content_type, conditional=True)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@v2_bp.route(_STEP + "/report", methods=["PUT"])
@require_auth
def v2_baseline_step_report(run_id: str, step_id: str):
    return _run("baseline pilot report", lambda: pilot.save_report(
        db, _owner(), run_id, step_id, request.get_json(silent=True)))
