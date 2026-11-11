"""Starting a model: the setup's routes (N528 item 4, N566 items 2 to 6,
N570, N571, N582, N585; services/model_setup.py for the rules and words,
services/model_setup_store.py for the tables).

  POST /v2/models/setup                          "Start your own": a new draft
  GET  /v2/models/<id>/setup                     the draft where it stopped;
                                                 ?step=<step> for one step
  POST /v2/models/<id>/setup/<step>              one step's answer, then the next
  POST /v2/models/<id>/setup/start-now           "Start with this, finish the rest later"
  POST /v2/models/<id>/setup/study               a study (multipart ``file``)
  POST /v2/models/<id>/setup/data                existing data (multipart ``file``)
  GET  /v2/models/<id>/setup/first-ten           the next of the owner's first 10
  POST /v2/models/<id>/setup/first-ten/<eid>     {step, answer}
  GET  /v2/models/coming                         images, video, recordings: coming
  POST /v2/models/coming/<kind>/want             "I want this", one mail, once
                                                 (services/model_coming.py; ring
                                                 chat_builder or ai_models)

Every answer is {model_id, status, screen}; ``screen`` is one step as the
owner's screen shows it. "Copy an invite link" is the owner's own chat link
(N598): the invite step carries ``chat_link``, and GET /v2/chats/link makes
it when there is none yet; there is no separate teacher link. Ring row ``ai_models`` (ring 6): anyone else gets
404 from every route, and a draft is 404 to anyone but its owner. The two
provider calls (the draft and a study's rules) pass the caller's
processing authorization in the store.
"""
import logging

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from services.db import db
from services.rate_limits import limiter

logger = logging.getLogger(__name__)


def _run(label: str, work):
    from services.chats import ChatsError
    try:
        result = work()
    except ChatsError as e:
        return jsonify({"code": e.code, "error": str(e)}), e.status
    except Exception as e:
        logger.error("model setup %s failed: %s", label, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to reach the setup"}), 500
    resp = jsonify(result)
    resp.headers["Cache-Control"] = "no-store"
    return resp, 200


def _me() -> str:
    return str(getattr(request, "user_id", ""))


def _body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _file(most: int) -> tuple[str, bytes]:
    upload = request.files.get("file")
    if upload is None:
        return "", b""
    return str(upload.filename or ""), upload.stream.read(most + 1)


@v2_bp.route("/models/setup", methods=["POST"])
@limiter.limit("30 per hour", scope="model_setup_begin")
@require_auth
def v2_model_setup_begin():
    from services import model_setup_store as store
    return _run("begin", lambda: store.begin(db, _me()))


@v2_bp.route("/models/<model_id>/setup", methods=["GET"])
@require_auth
def v2_model_setup_state(model_id):
    from services import model_setup_store as store
    return _run("state", lambda: store.state(db, _me(), model_id, request.args.get("step") or None))


@v2_bp.route("/models/setup/blocks", methods=["POST"])
@limiter.limit("30 per hour", scope="model_setup_begin")
@require_auth
def v2_model_setup_blocks():
    """"Start your own" in blocks (N636 item 7): {question, answers, gives?,
    base?} makes the model at once, as a chat's own card does."""
    from services import model_setup_store as store
    body = _body()
    return _run("blocks", lambda: store.begin_from_blocks(db, _me(), body))


@v2_bp.route("/models/<model_id>/setup/start-now", methods=["POST"])
@require_auth
def v2_model_setup_start_now(model_id):
    from services import model_setup_store as store
    body = _body()
    return _run("start-now", lambda: store.start_now(db, _me(), model_id, body))


@v2_bp.route("/models/<model_id>/setup/study", methods=["POST"])
@limiter.limit("20 per hour", scope="model_setup_study")
@require_auth
def v2_model_setup_study(model_id):
    from services import model_setup as rules
    from services import model_setup_store as store
    name, data = _file(rules.MAX_STUDY_BYTES)
    return _run("study", lambda: store.read_study(db, _me(), model_id, name, data))


@v2_bp.route("/models/<model_id>/setup/data", methods=["POST"])
@limiter.limit("20 per hour", scope="model_setup_data")
@require_auth
def v2_model_setup_data(model_id):
    from services import model_setup as rules
    from services import model_setup_store as store
    if "file" not in request.files and request.is_json:
        # The step's own answer, "I don't have any" ({}) or "Use this data"
        # ({use: true}): this route shadows /setup/<step> for "data", so a
        # JSON body is that step, never an upload without a file.
        body = _body()
        return _run("save", lambda: store.save(db, _me(), model_id, "data", body))
    name, data = _file(rules.MAX_UPLOAD_BYTES)
    return _run("data", lambda: store.read_data(db, _me(), model_id, name, data))


@v2_bp.route("/models/<model_id>/setup/first-ten", methods=["GET"])
@require_auth
def v2_model_setup_first_ten(model_id):
    from services import model_setup_store as store
    return _run("first-ten", lambda: store.first_ten(db, _me(), model_id))


@v2_bp.route("/models/<model_id>/setup/first-ten/<example_id>", methods=["POST"])
@require_auth
def v2_model_setup_first_ten_answer(model_id, example_id):
    from services import model_setup_store as store
    body = _body()
    return _run("first-ten answer", lambda: store.first_ten_answer(db, _me(), model_id, example_id, body))


@v2_bp.route("/models/<model_id>/setup/<step>", methods=["POST"])
@require_auth
def v2_model_setup_save(model_id, step):
    from services import model_setup_store as store
    body = _body()
    return _run("save", lambda: store.save(db, _me(), model_id, step, body))


# ── Models that learn from images, video and recordings: coming (N642
#    item 6, N645; services/model_coming.py) ──────────────────────────────

@v2_bp.route("/models/coming", methods=["GET"])
@require_auth
def v2_models_coming():
    """{"coming": [{kind, title, wanted}]}: images, video, recordings."""
    from services import model_coming
    return _run("coming", lambda: model_coming.coming(db, _me()))


@v2_bp.route("/models/coming/<kind>/want", methods=["POST"])
@limiter.limit("30 per hour", scope="models_coming_want")
@require_auth
def v2_models_coming_want(kind):
    """"I want this": one mail to the founder, once per kind."""
    from services import model_coming
    payload = getattr(request, "token_payload", None)
    return _run("coming want", lambda: model_coming.want(db, _me(), kind, payload))
