"""The backend's JSON error contract, in one place (F1-SURFACE).

Every error response this app produces is ``{"code": ..., "error": ...}``
with an HTTP status — that is what the Next.js app parses. Before this
module only 413 and 405 were handled, so anything else (an unhandled
exception, a 404, an ``abort(400)``) fell through to Werkzeug's HTML error
page. The FE would then try to ``JSON.parse`` a ``<!doctype html>`` and
crash on the very responses it most needs to handle gracefully.

``register(app, config)`` installs the whole contract:

  413  PAYLOAD_TOO_LARGE   body over MAX_CONTENT_LENGTH
  405  METHOD_NOT_ALLOWED
  429  RATE_LIMITED        + retry_after_seconds and Retry-After
  4xx  <werkzeug name>     e.g. NOT_FOUND, BAD_REQUEST, UNAUTHORIZED
  500  INTERNAL_ERROR      anything unhandled

Run: python3 -m unittest test_error_contract
"""
from __future__ import annotations

import logging

from flask import jsonify, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

logger = logging.getLogger(__name__)


def http_error_code(exc) -> str:
    """Werkzeug's error name as a stable machine code: "Not Found" ->
    NOT_FOUND. Gives the contract's ``code`` field something meaningful for
    the HTTP errors nobody wrote a bespoke handler for."""
    name = (getattr(exc, "name", None) or "HTTP Error").strip()
    code = "".join(ch if ch.isalnum() else "_" for ch in name).upper()
    while "__" in code:
        code = code.replace("__", "_")
    return code.strip("_") or "HTTP_ERROR"


def http_error_message(exc) -> str:
    """The ``error`` text for an HTTP error.

    ``abort(400, "take_session_id is required")`` must survive verbatim —
    that message is the whole point of the abort. But Werkzeug's own
    DEFAULTS are browser copy ("If you entered the URL manually please
    check your spelling..."), which has no business in an API contract, so
    an untouched description collapses to the short status name and matches
    what the hand-written handlers already return ("Not found").
    """
    description = getattr(exc, "description", None)
    class_default = getattr(type(exc), "description", None)
    if description and description != class_default:
        return description
    return getattr(exc, "name", None) or "HTTP error"


def register(app, config) -> None:
    """Install the JSON error contract on ``app``."""

    @app.errorhandler(RequestEntityTooLarge)
    @app.errorhandler(413)
    def handle_413(e):
        """Return JSON when request body exceeds MAX_CONTENT_LENGTH."""
        path = (request.path or "").strip()
        if "/v2/admin/copilot/reference-videos/upload" in path:
            return jsonify({
                "code": "PAYLOAD_TOO_LARGE",
                "error": (
                    f"Reference video is too large. Max allowed is "
                    f"{int(getattr(config, 'MAX_REFERENCE_VIDEO_SIZE_MB', 500))}MB."
                ),
            }), 413
        return jsonify({
            "code": "PAYLOAD_TOO_LARGE",
            "error": (
                f"Request body exceeds {config.MAX_AUDIO_SIZE_MB}MB limit. "
                f"Keep recording under {config.MAX_AUDIO_SIZE_MB}MB."
            ),
        }), 413

    @app.errorhandler(405)
    def handle_405(e):
        return jsonify({
            "code": "METHOD_NOT_ALLOWED",
            "error": "Method not allowed",
        }), 405

    @app.errorhandler(429)
    def handle_429(e):
        """Rate limited — the shape the guest funnel already returned.

        ``retry_after_seconds`` mirrors the Retry-After header so the FE can
        back off without reading headers (the same field the icebreaker
        regenerate endpoint has always sent).
        """
        from services import rate_limits
        retry_after = rate_limits.retry_after_seconds()
        logger.info("rate limited: %s %s scope=%s retry_after=%ss",
                    request.method, (request.path or "").strip(),
                    rate_limits.breach_scope(e), retry_after)
        response = jsonify({
            "code": "RATE_LIMITED",
            "error": rate_limits.breach_message(e),
            "retry_after_seconds": retry_after,
        })
        response.headers["Retry-After"] = str(retry_after)
        return response, 429

    @app.errorhandler(Exception)
    def handle_unexpected_error(e):
        """The catch-all, so the backend ALWAYS answers JSON.

        Three things this has to get right:

        1. HTTPExceptions (404, ``abort(400)``, ...) reach this handler too,
           because Flask's lookup walks the exception MRO and lands on
           ``Exception`` when nothing more specific matches. They keep their
           own status — only genuine crashes become 500. The handlers above
           still win: Flask checks code-keyed handlers before class-keyed
           ones.
        2. Registering this handler SUPPRESSES Flask's got_request_exception
           signal, which is how sentry-sdk's Flask integration normally sees
           an unhandled error. So we capture explicitly — otherwise adding a
           nicer error page would have silently blinded Sentry.
        3. It re-raises where exceptions are meant to propagate (the local
           debug server, or an explicit PROPAGATE_EXCEPTIONS), so the
           Werkzeug debugger and test tracebacks still work.
        """
        if isinstance(e, HTTPException):
            return jsonify({
                "code": http_error_code(e),
                "error": http_error_message(e),
            }), e.code

        if app.config.get("PROPAGATE_EXCEPTIONS") or app.debug:
            raise e

        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except Exception:  # pragma: no cover - reporting must never mask
            logger.warning("sentry capture failed for unhandled exception")

        logger.error("Unhandled exception on %s %s: %s", request.method,
                     (request.path or "").strip(), e, exc_info=True)
        payload = {"code": "INTERNAL_ERROR", "error": "Internal server error"}
        if not getattr(config, "is_production", False):
            # Local/staging only — never leak internals to production clients.
            payload["detail"] = f"{type(e).__name__}: {e}"
        return jsonify(payload), 500
