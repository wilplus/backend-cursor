"""A model's API and its money (N528 items 6, 7 and 12, N531, N566 items 8
to 10, N577, N583; services/model_api.py for the rules,
services/model_api_store.py for the tables).

In the app (signed in; the ring row ``ai_models``, else 404):
  GET    /v2/models/<id>/card                 the card of a model for sale (MOD-39)
  POST   /v2/models/<id>/try   {message}      "Try it", in text (MOD-40, MOD-45)
  GET    /v2/models/<id>/price ?uses=&units=  "Set your price", the owner's (MOD-46);
                                              units previews a price, saving nothing
  POST   /v2/models/<id>/price {units}        set it, never below the running cost
  GET    /v2/models/<id>/use                  "Use it in your business" (MOD-41, MOD-48)
  POST   /v2/models/<id>/keys  {kind, monthly_limit_units, allow_training}
                                              a key, shown once (MOD-42)
  GET    /v2/models/<id>/code                 the code (MOD-43)
  GET    /v2/models/<id>/usage                the buyer's month (MOD-44)
  DELETE /v2/models/keys/<key_id>             "Delete this key"
  POST   /v2/models/keys/<key_id>/switch      move to the newest version
  POST   /v2/models/keys/<key_id>/unsure {on} "Send the questions it wasn't sure about"
  GET    /v2/models/earnings                  a teacher's earnings (MOD-47)
  GET    /v2/models/<id>/download ?rows=1     downloading its data, the one route (MOD-51):
                                              numbered, never the sealed exam; ?format=jsonl
                                              or csv: the same rows as a file, a manifest
                                              line first (N648 item 6)
  POST   /v2/models/<id>/versions/<n>/release the model's founder releases a version
  GET    /v2/models/<id>/check                the owner's check: ten unseen examples, the
                                              head's guess first (LEARN-03)
  POST   /v2/models/<id>/check {example_id, keep, answer?}  Keep or Change on one
  GET    /v2/models/<id>/learning             its head and its two gates (LEARN-04)

The API (a key, not a sign-in):
  POST   /v2/models/<id>/answer  {message}    Authorization: Bearer wpl_sk_...
                                              Idempotency-Key: <1-255 visible ASCII>, optional
                                              -> {answer, sure, version}
                                              The same Idempotency-Key and question again
                                              get the first answer, charged nothing (PIPE-07);
                                              a key's monthly limit is checked and taken in
                                              one database step, so it cannot be raced (PIPE-08)

WillpowerLab's founder only:
  POST   /v2/admin/models/<id>/versions {card?} queue a new fit (202 {queued}); a status
                                              or an exam is refused, 409 EXAM_IS_COMPUTED:
                                              the app computes it (LEARN-05)
  POST   /v2/admin/models/payouts {month, pay}  a month's payouts, in tokens

Provider calls: "Try it" runs under the caller's own authority
(``phase1_provider_route``); an API answer under its buyer's
(``user_provider_scope``). Both pass the processing-authorization path, a
permit for every call. A key is never logged: the Authorization header is
read here, hashed in the store, and never passed to a logger.
"""
import logging

import sentry_sdk
from flask import Response, jsonify, request

from auth import require_auth
from routes.admin import require_founder
from routes.v2.blueprint import v2_bp
from routes.v2.processing_authorization import phase1_provider_route, user_provider_scope
from services.db import db
from services.processing_authorization import ProcessingAuthorizationError
from services.rate_limits import llm_limit

logger = logging.getLogger(__name__)


def _run(label: str, work, status: int = 200, answer=None):
    from services.chats import ChatsError
    try:
        result = work()
    except ChatsError as e:
        return jsonify({"code": e.code, "error": str(e)}), e.status
    except ProcessingAuthorizationError as e:
        return jsonify({"code": e.code, "error": e.message}), e.status
    except Exception as e:
        logger.error("model api %s failed: %s", label, type(e).__name__, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to reach the model"}), 500
    resp = answer(result) if answer is not None else None
    if resp is None:
        resp = jsonify(result)
    resp.headers["Cache-Control"] = "no-store"
    return resp, status


def _me() -> str:
    return str(getattr(request, "user_id", ""))


def _body() -> dict:
    return request.get_json(silent=True) or {}


@v2_bp.route("/models/<model_id>/card", methods=["GET"])
@require_auth
def v2_model_card(model_id):
    from services import model_api_store as store
    return _run("card", lambda: store.card_for(db, _me(), model_id))


@v2_bp.route("/models/<model_id>/try", methods=["POST"])
@require_auth
@llm_limit
@phase1_provider_route
def v2_model_try(model_id):
    from services import model_api_store as store
    return _run("try", lambda: store.try_it(db, _me(), model_id, _body().get("message")))


@v2_bp.route("/models/<model_id>/price", methods=["GET"])
@require_auth
def v2_model_price(model_id):
    from services import model_api_store as store
    try:
        uses = int(request.args.get("uses") or 10_000)
    except ValueError:
        uses = 10_000
    try:
        units = int(request.args["units"]) if request.args.get("units") else None
    except ValueError:
        units = None
    # ?units= previews a proposed price and its split; nothing is saved.
    return _run("price", lambda: store.price_for(db, _me(), model_id, uses=uses, units=units))


@v2_bp.route("/models/<model_id>/price", methods=["POST"])
@require_auth
def v2_model_set_price(model_id):
    from services import model_api_store as store
    return _run("set price", lambda: store.set_price(db, _me(), model_id, _body().get("units")))


@v2_bp.route("/models/<model_id>/use", methods=["GET"])
@require_auth
def v2_model_use(model_id):
    from services import model_api_store as store
    return _run("use", lambda: store.terms_for(db, _me(), model_id))


@v2_bp.route("/models/<model_id>/keys", methods=["POST"])
@require_auth
def v2_model_create_key(model_id):
    from services import model_api_store as store
    b = _body()
    return _run("key", lambda: store.create_key(
        db, _me(), model_id, kind=str(b.get("kind") or "test"),
        monthly_limit_units=b.get("monthly_limit_units"), allow_training=bool(b.get("allow_training"))))


@v2_bp.route("/models/<model_id>/code", methods=["GET"])
@require_auth
def v2_model_code(model_id):
    from services import model_api_store as store
    return _run("code", lambda: store.code_for(db, _me(), model_id, request.host_url))


@v2_bp.route("/models/<model_id>/usage", methods=["GET"])
@require_auth
def v2_model_usage(model_id):
    from services import model_api_store as store
    return _run("usage", lambda: store.usage_for(db, _me(), model_id))


@v2_bp.route("/models/keys/<key_id>", methods=["DELETE"])
@require_auth
def v2_model_delete_key(key_id):
    from services import model_api_store as store
    return _run("delete key", lambda: store.delete_key(db, _me(), key_id))


@v2_bp.route("/models/keys/<key_id>/switch", methods=["POST"])
@require_auth
def v2_model_switch_key(key_id):
    from services import model_api_store as store
    return _run("switch key", lambda: store.switch_key(db, _me(), key_id))


@v2_bp.route("/models/keys/<key_id>/unsure", methods=["POST"])
@require_auth
def v2_model_send_unsure(key_id):
    from services import model_api_store as store
    return _run("unsure", lambda: store.send_unsure(db, _me(), key_id, bool(_body().get("on"))))


@v2_bp.route("/models/earnings", methods=["GET"])
@require_auth
def v2_model_earnings():
    from services import model_api_store as store
    return _run("earnings", lambda: store.earnings_for(db, _me()))


@v2_bp.route("/models/<model_id>/download", methods=["GET"])
@require_auth
def v2_model_download(model_id):
    from services import model_api_store as store
    fmt = request.args.get("format") or None

    def as_file(result):
        if "file" not in result:
            return None          # the screen, the rows or a refusal: JSON as before
        resp = Response(result["file"], mimetype=result["media_type"])
        resp.headers["Content-Disposition"] = f'attachment; filename="{result["name"]}"'
        return resp
    return _run("download", lambda: store.download_for(
        db, _me(), model_id, rows=request.args.get("rows") in ("1", "true"), fmt=fmt), answer=as_file)


@v2_bp.route("/models/<model_id>/versions/<number>/release", methods=["POST"])
@require_auth
def v2_model_release(model_id, number):
    from services import model_api_store as store
    return _run("release", lambda: store.release(db, _me(), model_id, number))


@v2_bp.route("/models/<model_id>/answer", methods=["POST"])
@llm_limit
def v2_model_answer(model_id):
    """The API. The key is the only credential; a missing or unknown key
    and a key for another model all answer the same 401."""
    from services import model_api_store as store
    header = request.headers.get("Authorization") or ""
    plain = header[len("Bearer "):].strip() if header.startswith("Bearer ") else ""
    key = store.key_for(db, plain)
    plain = ""  # never kept past the lookup
    if key is None:
        return jsonify({"code": "INVALID_KEY", "error": "This key is not valid."}), 401
    message = _body().get("message")
    once = request.headers.get("Idempotency-Key")

    def work():
        with user_provider_scope(str(key["buyer_id"]), operation="ai_conversation", prefix="model-api"):
            return store.answer_with_key(db, key, model_id, message, idempotency_key=once)
    return _run("answer", work)


@v2_bp.route("/admin/models/<model_id>/versions", methods=["POST"])
@require_founder
def v2_admin_model_version(model_id):
    from services import model_api_store as store
    return _run("version", lambda: store.admin_version(db, model_id, _body()), status=202)


@v2_bp.route("/admin/models/payouts", methods=["POST"])
@require_founder
def v2_admin_model_payouts():
    from services import model_api_store as store
    b = _body()
    return _run("payouts", lambda: store.pay_month(db, str(b.get("month") or ""),
                                                   pay=bool(b.get("pay"))))


@v2_bp.route("/models/<model_id>/check", methods=["GET", "POST"])
@require_auth
@phase1_provider_route
def v2_model_check(model_id):
    """The owner's check (LEARN-03). The first GET reads its ten examples
    once, under the owner's own processing authority."""
    from services import model_head_store as heads
    if request.method == "POST":
        return _run("check", lambda: heads.check_answer(db, _me(), model_id, _body()))
    return _run("check", lambda: heads.check_for(db, _me(), model_id))


@v2_bp.route("/models/<model_id>/learning", methods=["GET"])
@require_auth
def v2_model_learning(model_id):
    from services import model_head_store as heads
    return _run("learning", lambda: heads.learning_for(db, _me(), model_id))
