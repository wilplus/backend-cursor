"""One id per request, on every log line, Sentry event and queued job.

WHY (audit 2026-09-26, bug-trace drills). A user's report could not be joined
to a single log line: nothing tied the browser's request, the BFF hop, the
Flask handler and the worker job that finished the work together. The id
starts at the BFF (``X-Request-Id``), is bound here for the length of the
Flask request, rides a queued job in ``job.meta``, and is bound again in the
worker for the length of that job.

The id is stamped on EVERY log record through the record factory, not a
handler filter: ``configure_logging`` deliberately leaves handlers someone
else installed alone, and a handler whose format names ``request_id`` must
never meet a record without it.
"""
from __future__ import annotations

import contextvars
import logging
import re
import uuid
from typing import Any, Optional

NO_REQUEST = "-"
HEADER = "X-Request-Id"
_VALID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=NO_REQUEST)
_factory_installed = False


def current_request_id() -> str:
    """The id bound to this request or job, or ``"-"`` outside both."""
    return _REQUEST_ID.get()


def bind_request_id(value: Optional[str]) -> str:
    """Bind ``value`` when it is a well-formed id, otherwise a fresh one.

    The header comes from outside, so anything that is not a short token is
    replaced rather than logged verbatim.
    """
    rid = value if isinstance(value, str) and _VALID.match(value) else (
        uuid.uuid4().hex[:12])
    _REQUEST_ID.set(rid)
    try:
        import sentry_sdk
        sentry_sdk.set_tag("request_id", rid)
    except Exception:  # Sentry is optional; the log line is what matters.
        pass
    return rid


def job_meta() -> dict[str, Any]:
    """What a queued job carries so the worker can bind the same id."""
    rid = current_request_id()
    return {} if rid == NO_REQUEST else {"request_id": rid}


def bind_from_job_meta(meta: Any) -> str:
    """Bind the id a job was queued with (a fresh one when it has none)."""
    value = meta.get("request_id") if isinstance(meta, dict) else None
    return bind_request_id(value)


def install_log_record_factory() -> None:
    """Give every log record a ``request_id`` attribute. Idempotent."""
    global _factory_installed
    if _factory_installed:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        record.request_id = _REQUEST_ID.get()
        return record

    logging.setLogRecordFactory(factory)
    _factory_installed = True


def install_request_id(app: Any) -> None:
    """Bind the incoming id for each Flask request and echo it back."""
    from flask import g, request

    @app.before_request
    def _bind_request_id() -> None:
        g.request_id = bind_request_id(request.headers.get(HEADER))

    @app.after_request
    def _echo_request_id(response: Any) -> Any:
        response.headers[HEADER] = current_request_id()
        return response

    @app.teardown_request
    def _clear_request_id(_exc: Any) -> None:
        _REQUEST_ID.set(NO_REQUEST)
