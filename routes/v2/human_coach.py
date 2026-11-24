"""The live calendar and consented private review handoffs (N688)."""
import logging

from flask import jsonify, request

from auth import require_auth
from routes.v2.blueprint import v2_bp
from services import human_coach_booking as calendar, human_coach_reviews as reviews
from services.booking import BookingError
from services.db import db
from services.processing_authorization import ProcessingAuthorizationError
from services.rate_limits import limiter

logger = logging.getLogger(__name__)


def _private(payload, status=200):
    response = jsonify(payload)
    response.headers["Cache-Control"] = "private, no-store"
    return response, status


def _run(work):
    try:
        return _private(work())
    except (BookingError, reviews.HandoffError, ProcessingAuthorizationError) as error:
        return _private({"code": error.code, "error": str(error)}, error.status)
    except Exception as error:  # noqa: BLE001 — redact private notes and review links from failures.
        # Review and provider failures can contain the note or a link. Log
        # the exception type without the provider response or private body.
        logger.warning("human coach handoff failed: %s", type(error).__name__)
        return _private({"code": "HANDOFF_UNAVAILABLE", "error": "Please try again."}, 503)


def _body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise reviews.HandoffError("INVALID_INPUT", "This request could not be read.", 400)
    return body


@v2_bp.route("/human-coach/calendar", methods=["GET", "POST"])
@require_auth
@limiter.limit("20/minute")
def v2_human_coach_calendar():
    from routes.v2.plan import _account

    user = str(request.user_id)
    name, email = _account()
    if request.method == "GET":
        return _run(lambda: calendar.availability(user, name, email))
    return _run(lambda: calendar.confirm(db, user, _body(), name, email))


@v2_bp.route("/human-coach/projects/<project>/reviews", methods=["GET"])
@require_auth
def v2_human_coach_review_history(project):
    return _run(lambda: reviews.list_reviews(db, str(request.user_id), project))


@v2_bp.route("/human-coach/projects/<project>/reviews/<take>", methods=["GET", "POST"])
@require_auth
@limiter.limit("20/minute")
def v2_human_coach_review_take(project, take):
    user = str(request.user_id)
    if request.method == "GET":
        return _run(lambda: reviews.preview(db, user, project, take))
    return _run(lambda: reviews.send(db, user, project, take, _body().get("note", "")))


@v2_bp.route("/human-coach/inbox/<review>", methods=["GET", "POST"])
@require_auth
def v2_human_coach_inbox(review):
    user = str(request.user_id)
    if request.method == "GET":
        return _run(lambda: reviews.inbox(db, user, review))
    return _run(lambda: reviews.publish(db, user, review, _body().get("feedback")))
