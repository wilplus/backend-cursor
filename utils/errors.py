"""Client-safe error envelopes + the global JSON error handler.

Why this exists (P0 audit, founder 2026-08-03): routes were returning
``str(e)`` and raw ``subprocess`` stderr straight to the browser. Those
strings carry absolute server paths (``/app/services/...``), Postgres
DSNs, Supabase/OpenAI keys echoed back inside SDK error text, and full
tracebacks. Anything a caller can trigger, a caller can read.

The contract this module enforces:

    the CLIENT gets  → {"code": <stable code>, "error": <generic copy>,
                        "ref": <short correlation id>}
    the SERVER gets  → the full exception, logged with the SAME ref and
                       tagged onto the Sentry event.

So support can still answer "what actually happened" from a screenshot —
the ref is the join key — without the payload itself being the leak.

Three entry points:

``safe_error(code, ...)``
    Drop-in for the ``return jsonify({"code": ..., "error": str(e)}), 500``
    pattern. Logs + captures, returns the sanitized envelope.

``register_error_handlers(app)``
    App-wide net for what routes DIDN'T catch: any uncaught exception,
    any ``abort()``, any Werkzeug HTTPException (404/401/400/...). Without
    this a route that raises before its own try/except reaches Flask's
    default handler, which renders an HTML page — and with
    ``debug=True`` locally, the interactive traceback.

``scrub(text)``
    Redacts secret-shaped and path-shaped substrings. Applied to every
    detail string we keep, including the ones that only go to logs — a
    log line pasted into a ticket is the same leak one step removed.

AC-9 note: none of this is user-facing product copy. These are failure
envelopes for the machine (FE error boundaries + support), not the
qualitative read, so the fence doesn't apply — but the generic messages
are still written as plain human sentences, not stack-trace fragments.
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Generic copy, per HTTP status ────────────────────────────────────────
# What the client is allowed to know: the shape of the failure, never the
# mechanism. Anything not listed falls through to the 500 line.
_STATUS_COPY = {
    400: "The request was malformed.",
    401: "Authentication required.",
    403: "You don't have access to this.",
    404: "Not found.",
    405: "Method not allowed.",
    409: "That conflicts with the current state.",
    413: "The upload is too large.",
    415: "That file type isn't supported.",
    422: "The request couldn't be processed.",
    429: "Too many requests — slow down and try again.",
    500: "Something went wrong on our end.",
    502: "An upstream service failed.",
    503: "Temporarily unavailable — try again shortly.",
    504: "That took too long and was stopped.",
}

_GENERIC_500 = _STATUS_COPY[500]


# ── Secret / path redaction ──────────────────────────────────────────────
# Order matters: the broad JWT + key patterns run before the path pattern
# so a key embedded in a URL is masked before the URL is touched.
_REDACTIONS: list[tuple[re.Pattern, str]] = [
    # OpenAI-style keys (sk-..., sk-proj-...) and generic long bearer blobs
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}"), "sk-***"),
    # JWTs (Supabase anon/service-role keys, access tokens)
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]+"),
     "***jwt***"),
    # Postgres / Redis / AMQP DSNs with inline credentials
    (re.compile(r"\b(postgres(?:ql)?|redis|rediss|amqp)://[^\s\"']+", re.I),
     r"\1://***"),
    # Authorization headers echoed inside SDK error text. The optional
    # scheme word has to be consumed too — matching only up to the next
    # \S+ eats "Bearer" and leaves the token itself in the clear.
    (re.compile(r"(?i)\b(authorization|api[-_]?key|token)\b\s*[:=]\s*"
                r"(?:bearer\s+|basic\s+)?\S+"),
     r"\1: ***"),
    (re.compile(r"(?i)\bbearer\s+\S+"), "bearer ***"),
    # AWS/R2 access key ids
    (re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{12,}"), "***akid***"),
    # Absolute server paths — leaks the deploy layout and the repo root
    (re.compile(r"(?:/[A-Za-z0-9._\-]+){2,}\.py\b"), "<path>.py"),
    (re.compile(r"\b/(?:app|home|usr|root|opt|nix|var|tmp)/[^\s\"',)]*"),
     "<path>"),
    # Windows paths (local dev tracebacks pasted into tickets)
    (re.compile(r"\b[A-Za-z]:\\[^\s\"',)]*"), "<path>"),
]

_MAX_DETAIL_CHARS = 600


def scrub(text: Any, *, limit: int = _MAX_DETAIL_CHARS) -> str:
    """Redact secret- and path-shaped substrings, then truncate.

    Applied to EVERY detail string this module keeps — including the ones
    that only ever reach the log sink. A scrubbed log line is still fully
    useful for debugging (exception type, message shape, ids) while
    surviving being pasted into a ticket or a shared terminal.
    """
    s = "" if text is None else str(text)
    for pattern, replacement in _REDACTIONS:
        s = pattern.sub(replacement, s)
    s = " ".join(s.split())
    if len(s) > limit:
        s = s[:limit] + "…"
    return s


def scrub_process_output(raw: Any, *, limit: int = 2000) -> str:
    """Scrub subprocess stdout/stderr for the LOG sink.

    ffmpeg and the trainer scripts echo the full argv — which includes
    absolute paths, and for the trainer, the dataset location. Never
    return the result of this to a client; it exists so the operator can
    still read what the subprocess said from the logs.
    """
    return scrub(raw, limit=limit)


def new_ref() -> str:
    """Short correlation id shared by the client envelope, the log line
    and the Sentry event. 8 hex chars — long enough not to collide inside
    a debugging window, short enough to read off a screenshot."""
    return uuid.uuid4().hex[:8]


def expose_error_detail() -> bool:
    """True when the exception detail may ride along in the response.

    OFF in production, always — the whole point. Locally it defaults ON
    so a dev sees the real error without tailing logs. ``EXPOSE_ERROR_
    DETAILS`` forces it either way (set it to 0 in staging to rehearse
    the production envelope).
    """
    raw = (os.getenv("EXPOSE_ERROR_DETAILS") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return (os.getenv("ENV", "development") or "development").strip().lower() \
        not in ("production", "prod", "staging")


def _capture(exc: Optional[BaseException], ref: str,
             context: Optional[dict] = None) -> None:
    """Send to Sentry with the ref attached, best-effort.

    Never raises: an error path that can itself error is how a 500
    becomes a 502.
    """
    if exc is None:
        return
    try:
        import sentry_sdk

        # sentry-sdk 2.x renamed push_scope -> new_scope; keep both so the
        # SDK pin can move without this becoming a silent no-op.
        scope_cm = getattr(sentry_sdk, "new_scope", None) or sentry_sdk.push_scope
        with scope_cm() as scope:
            scope.set_tag("error_ref", ref)
            for k, v in (context or {}).items():
                scope.set_extra(k, v)
            sentry_sdk.capture_exception(exc)
    except Exception:  # pragma: no cover - telemetry must never break a request
        pass


def error_payload(code: str, status: int = 500, *,
                  message: Optional[str] = None,
                  exc: Optional[BaseException] = None,
                  ref: Optional[str] = None,
                  extra: Optional[dict] = None) -> dict:
    """Build the client-facing envelope (no logging, no capture).

    ``message`` overrides the generic status copy — pass one only when
    it is SAFE and USEFUL to the caller ("No speech detected", "Upload an
    audio file"). Never pass exception text.
    """
    body: dict[str, Any] = {
        "code": code,
        "error": message or _STATUS_COPY.get(status, _GENERIC_500),
        "ref": ref or new_ref(),
    }
    if extra:
        body.update(extra)
    if exc is not None and expose_error_detail():
        # Dev/local only. Still scrubbed — a dev machine's .env holds real
        # keys, and this string ends up in browser devtools and HAR files.
        body["detail"] = scrub(f"{type(exc).__name__}: {exc}")
    return body


def safe_error(code: str, status: int = 500, *,
               message: Optional[str] = None,
               exc: Optional[BaseException] = None,
               log: Optional[str] = None,
               context: Optional[dict] = None,
               extra: Optional[dict] = None) -> Tuple[Any, int]:
    """Log + capture the real error, return the sanitized envelope.

    The replacement for ``return jsonify({"code": X, "error": str(e)}), 500``.

        except Exception as e:
            return safe_error("RECORDING_ERROR", 500, exc=e,
                              log="recordings: fetch failed user=%s" % uid)

    Returns a ``(response, status)`` tuple, so it drops straight into a
    ``return`` next to the existing jsonify calls.
    """
    from flask import jsonify

    ref = new_ref()
    if exc is not None or log:
        logger.error(
            "%s [ref=%s] %s",
            log or code, ref,
            f"({type(exc).__name__}: {scrub(exc)})" if exc is not None else "",
            exc_info=exc if exc is not None else False,
        )
    _capture(exc, ref, context)
    return jsonify(error_payload(code, status, message=message, exc=exc,
                                 ref=ref, extra=extra)), status


def _should_propagate(app) -> bool:
    """Mirror Flask's own PROPAGATE_EXCEPTIONS resolution.

    Registering a catch-all ``Exception`` handler would otherwise swallow
    exceptions in tests and in ``flask run --debug``, where the raise IS
    the feature. We keep that behaviour and only sanitize where it
    matters: a real request on a real deploy.
    """
    propagate = app.config.get("PROPAGATE_EXCEPTIONS")
    if propagate is None:
        return bool(app.testing or app.debug)
    return bool(propagate)


def register_error_handlers(app) -> None:
    """Install the app-wide JSON error net.

    Covers what route-level try/except cannot: exceptions raised before a
    route's own handler, ``abort()`` calls, and Flask's built-in 404/405
    pages. Every response from here is JSON — this process serves an API;
    an HTML error page is a parse failure at the FE error boundary on top
    of whatever went wrong.

    Handlers already registered by the app (413's per-route copy) keep
    working: Flask resolves the most specific handler first.
    """
    from werkzeug.exceptions import HTTPException

    @app.errorhandler(HTTPException)
    def _handle_http_exception(e: HTTPException):
        status = int(e.code or 500)
        # Werkzeug's stock descriptions are safe and more specific than
        # ours for the 4xx family; our table wins for 5xx, where the
        # description can name internals.
        message = _STATUS_COPY.get(status)
        if status >= 500:
            ref = new_ref()
            logger.error("http %s [ref=%s] %s %s: %s", status, ref,
                         _req_method(), _req_path(), scrub(e))
            _capture(e, ref, {"path": _req_path()})
            return _json(error_payload("HTTP_ERROR", status, message=message,
                                       ref=ref)), status
        return _json(error_payload(f"HTTP_{status}", status,
                                   message=message or scrub(e.description,
                                                            limit=200))), status

    @app.errorhandler(Exception)
    def _handle_uncaught(e: Exception):
        if _should_propagate(app):
            raise e
        ref = new_ref()
        logger.error("unhandled [ref=%s] %s %s: %s", ref, _req_method(),
                     _req_path(), scrub(e), exc_info=True)
        _capture(e, ref, {"path": _req_path()})
        return _json(error_payload("INTERNAL_ERROR", 500, exc=e, ref=ref)), 500


def _json(body: dict):
    from flask import jsonify

    return jsonify(body)


def _req_path() -> str:
    try:
        from flask import request

        return (request.path or "")[:200]
    except Exception:
        return ""


def _req_method() -> str:
    try:
        from flask import request

        return request.method or ""
    except Exception:
        return ""
