"""Private, volunteer-only experiments in the chat builder.

  POST   /v2/experiments/sessions
  POST   /v2/experiments/sessions/<session_id>/takes
  POST   /v2/experiments/analyze-take   202, then
  GET    /v2/experiments/takes/<id>/analysis
  GET    /v2/experiments/prompts
  POST   /v2/experiments/prompts
  POST   /v2/experiments/prompts/import
  PUT    /v2/experiments/prompts/<prompt_id>
  DELETE /v2/experiments/prompts/<prompt_id>
  GET    /v2/experiments/interventions
  POST   /v2/experiments/interventions
  PUT    /v2/experiments/interventions/<intervention_id>
  DELETE /v2/experiments/interventions/<intervention_id>
  GET    /v2/experiments/export?format=csv|json&audience=self|researcher
  DELETE /v2/experiments/me

A take is a recording and a Whisper call, so it uses the same processing
authorization as a chat voice note. The service-role key stays on the
storage client. Responses never include it, or the auth user id.

``analyze-take`` is the model slot. Its shape is fixed in
``services.experiments_config.analyze_example``. The numbers are not for a
speaker's screen.
"""
from __future__ import annotations

import json
import logging

import sentry_sdk
from flask import Response, jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from routes.v2.processing_authorization import phase1_provider_route
from services.db import db
from services.rate_limits import heavy_limit, limiter, whisper_limit

logger = logging.getLogger(__name__)


def _json(body, status: int = 200):
    response = jsonify(body)
    response.status_code = status
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _run(label: str, work):
    from services.experiments import ExperimentsError
    try:
        result = work()
    except ExperimentsError as exc:
        return _json({"code": exc.code, "error": str(exc)}, exc.status)
    except Exception as exc:
        logger.exception("experiments %s failed", label)
        sentry_sdk.capture_exception(exc)
        return _json({"code": "V2_ERROR", "error": "Failed to reach experiments"}, 500)
    if isinstance(result, tuple) and len(result) == 2 and result[0] == "csv":
        response = Response(result[1], mimetype="text/csv")
        response.headers["Content-Disposition"] = 'attachment; filename="experiments.csv"'
        response.headers["Cache-Control"] = "private, no-store"
        return response
    if isinstance(result, tuple) and len(result) == 2 and result[0] == "json":
        return _json(result[1])
    if isinstance(result, tuple) and len(result) == 2 and result[0] == "pending":
        return _json(result[1], 202)
    if isinstance(result, tuple) and len(result) == 2 and result[0] == "ready":
        return _json(result[1])
    return _json(result)


def _case_from_request():
    from services.experiments import _case_file
    upload = request.files.get("business_case")
    if upload is None:
        return None
    raw = upload.read(10 * 1024 * 1024 + 1)
    return _case_file(upload.filename or "", upload.content_type or "", raw)


def _consent_and_case():
    if request.files.get("business_case") is not None or (
            request.content_type and "multipart/form-data" in request.content_type):
        raw = request.form.get("consent")
        try:
            consent = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            consent = None
        return consent, _case_from_request()
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return None, None
    return body.get("consent"), None


@v2_bp.route("/experiments/sessions", methods=["POST"])
@limiter.limit("30 per hour", scope="experiments_session")
@require_auth
def v2_experiments_session():
    from services.experiments import create_session

    def work():
        consent, case = _consent_and_case()
        return create_session(db, str(request.user_id), consent, case)

    return _run("session", work)


@v2_bp.route("/experiments/sessions/<session_id>/takes", methods=["POST"])
@require_auth
@phase1_provider_route
@whisper_limit
def v2_experiments_take(session_id):
    """Recording, then Whisper, under the caller's own processing authority."""
    from routes.v2.chats import _recording_refused
    from services.chat_voice import AUDIO_MAX
    from services.experiments import add_take
    refused = _recording_refused()
    if refused is not None:
        return refused
    upload = request.files.get("audio")
    raw = upload.read(AUDIO_MAX + 1) if upload is not None else b""
    rating_raw = request.form.get("self_rating")
    try:
        rating = json.loads(rating_raw) if rating_raw else None
    except json.JSONDecodeError:
        rating = None
    return _run("take", lambda: add_take(
        db, str(request.user_id), session_id,
        audio=raw,
        filename=(upload.filename if upload is not None else "") or "talk.webm",
        content_type=(upload.content_type if upload is not None else "") or "",
        prompt_id=request.form.get("prompt_id") or "",
        tag=request.form.get("tag") or "",
        self_rating=rating,
    ))


@v2_bp.route("/experiments/analyze-take", methods=["POST"])
@limiter.limit("30 per hour", scope="experiments_analyze")
@require_auth
@heavy_limit
def v2_experiments_analyze():
    """Queue analyze-take/v0.1. 202, then GET the take's analysis."""
    from services.experiments import request_analysis
    body = request.get_json(silent=True) or {}
    take_id = body.get("take_id") if isinstance(body, dict) else None
    model_id = body.get("model_id") if isinstance(body, dict) else None

    def work():
        return request_analysis(db, str(request.user_id), str(take_id or ""), model_id)

    response = _run("analyze", work)
    if getattr(response, "status_code", None) == 200:
        response.status_code = 202
    return response


@v2_bp.route("/experiments/takes/<take_id>/analysis", methods=["GET"])
@require_auth
def v2_experiments_analysis(take_id):
    from services.experiments import get_analysis

    def work():
        return get_analysis(db, str(request.user_id), take_id)

    return _run("analysis", work)


@v2_bp.route("/experiments/models", methods=["GET"])
@require_auth
def v2_experiments_models():
    from services.experiment_models import list_models
    return _run("models", lambda: list_models(db, str(request.user_id)))


@v2_bp.route("/experiments/models", methods=["POST"])
@limiter.limit("30 per hour", scope="experiments_model")
@require_auth
def v2_experiments_model_create():
    from services.experiment_models import create_model
    return _run("model", lambda: create_model(
        db, str(request.user_id), request.get_json(silent=True)))


@v2_bp.route("/experiments/models/<model_id>", methods=["PUT"])
@limiter.limit("30 per hour", scope="experiments_model")
@require_auth
def v2_experiments_model_update(model_id):
    from services.experiment_models import update_model
    return _run("model", lambda: update_model(
        db, str(request.user_id), model_id, request.get_json(silent=True)))


@v2_bp.route("/experiments/models/<model_id>", methods=["DELETE"])
@limiter.limit("30 per hour", scope="experiments_model")
@require_auth
def v2_experiments_model_delete(model_id):
    from services.experiment_models import delete_model
    return _run("model", lambda: delete_model(db, str(request.user_id), model_id))


@v2_bp.route("/experiments/prompts", methods=["GET"])
@require_auth
def v2_experiments_prompts():
    from services.experiments import list_prompts
    return _run("prompts", lambda: list_prompts(db, str(request.user_id)))


@v2_bp.route("/experiments/prompts", methods=["POST"])
@limiter.limit("60 per hour", scope="experiments_prompt")
@require_auth
def v2_experiments_prompt_create():
    from services.experiments import create_prompt
    return _run("prompt", lambda: create_prompt(
        db, str(request.user_id), request.get_json(silent=True)))


@v2_bp.route("/experiments/prompts/import", methods=["POST"])
@limiter.limit("10 per hour", scope="experiments_import")
@require_auth
def v2_experiments_prompt_import():
    from services.experiments import import_prompts
    return _run("import", lambda: import_prompts(db, str(request.user_id)))


@v2_bp.route("/experiments/prompts/<prompt_id>", methods=["PUT"])
@limiter.limit("60 per hour", scope="experiments_prompt")
@require_auth
def v2_experiments_prompt_update(prompt_id):
    from services.experiments import update_prompt
    return _run("prompt", lambda: update_prompt(
        db, str(request.user_id), prompt_id, request.get_json(silent=True)))


@v2_bp.route("/experiments/prompts/<prompt_id>", methods=["DELETE"])
@limiter.limit("60 per hour", scope="experiments_prompt")
@require_auth
def v2_experiments_prompt_delete(prompt_id):
    from services.experiments import delete_prompt
    return _run("prompt", lambda: delete_prompt(db, str(request.user_id), prompt_id))


@v2_bp.route("/experiments/interventions", methods=["GET"])
@require_auth
def v2_experiments_interventions():
    from services.experiments import list_interventions
    return _run("interventions", lambda: list_interventions(db, str(request.user_id)))


@v2_bp.route("/experiments/interventions", methods=["POST"])
@limiter.limit("60 per hour", scope="experiments_intervention")
@require_auth
def v2_experiments_intervention_create():
    from services.experiments import create_intervention
    return _run("intervention", lambda: create_intervention(
        db, str(request.user_id), request.get_json(silent=True)))


@v2_bp.route("/experiments/interventions/<intervention_id>", methods=["PUT"])
@limiter.limit("60 per hour", scope="experiments_intervention")
@require_auth
def v2_experiments_intervention_update(intervention_id):
    from services.experiments import update_intervention
    return _run("intervention", lambda: update_intervention(
        db, str(request.user_id), intervention_id, request.get_json(silent=True)))


@v2_bp.route("/experiments/interventions/<intervention_id>", methods=["DELETE"])
@limiter.limit("60 per hour", scope="experiments_intervention")
@require_auth
def v2_experiments_intervention_delete(intervention_id):
    from services.experiments import delete_intervention
    return _run("intervention", lambda: delete_intervention(
        db, str(request.user_id), intervention_id))


@v2_bp.route("/experiments/export", methods=["GET"])
@limiter.limit("20 per hour", scope="experiments_export")
@require_auth
def v2_experiments_export():
    from services.experiments import export_data
    fmt = request.args.get("format") or ""
    audience = request.args.get("audience") or "self"
    return _run("export", lambda: export_data(db, str(request.user_id), fmt, audience))


@v2_bp.route("/experiments/me", methods=["DELETE"])
@limiter.limit("10 per hour", scope="experiments_erase")
@require_auth
def v2_experiments_me():
    from services.experiments import erase
    return _run("erase", lambda: erase(db, str(request.user_id)))
