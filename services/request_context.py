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

from datetime import datetime, timezone

import contextvars
import logging
import re
import time
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


# The stopwatch (founder 2026-10-14): how long each request took and how
# many database calls it made, so slow screens are measured, not guessed.
# Sent back as a Server-Timing header and logged when a request is slow.
SLOW_REQUEST_MS = 500
_DB_CALLS: contextvars.ContextVar[Optional[list[int]]] = contextvars.ContextVar(
    "db_calls", default=None)


_LAPS: contextvars.ContextVar[Optional[list[str]]] = contextvars.ContextVar(
    "laps", default=None)
# How long each database call waited, in ms (founder 2026-10-18: a 4 s read
# made three calls; the count alone could not say whether they were slow).
_DB_MS: contextvars.ContextVar[Optional[list[float]]] = contextvars.ContextVar(
    "db_ms", default=None)


class lap:
    """Time one named step of the current request; a slow request's log line
    then lists its steps (``parts=read:120,clips:4100``). No-op outside one."""

    def __init__(self, name: str):
        self.name = name

    def __enter__(self) -> "lap":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *_exc: Any) -> None:
        laps = _LAPS.get()
        if laps is not None:
            laps.append(f"{self.name}:{(time.perf_counter() - self._t0) * 1000:.0f}")


def count_db_call() -> None:
    """One database call inside the current request (no-op outside one)."""
    box = _DB_CALLS.get()
    if box is not None:
        box[0] += 1


def add_db_time(ms: float) -> None:
    """How long one database call took, retries included (no-op outside a
    request)."""
    box = _DB_MS.get()
    if box is not None:
        box.append(ms)


def install_request_id(app: Any) -> None:
    """Bind the incoming id for each Flask request and echo it back."""
    from flask import g, request

    @app.before_request
    def _bind_request_id() -> None:
        g.request_id = bind_request_id(request.headers.get(HEADER))
        # When the request arrived, for timings measured from arrival (V4
        # B1.4: the practise read's server-side wait).
        g.received_at = datetime.now(timezone.utc)
        g.started_perf = time.perf_counter()
        _DB_CALLS.set([0])
        _DB_MS.set([])
        _LAPS.set([])

    @app.after_request
    def _echo_request_id(response: Any) -> Any:
        response.headers[HEADER] = current_request_id()
        try:
            started = g.get("started_perf")
            box = _DB_CALLS.get()
            if started is not None:
                ms = (time.perf_counter() - started) * 1000.0
                calls = box[0] if box else 0
                timing = f"app;dur={ms:.0f}, db;desc=\"calls\";dur={calls}"
                # The calls' own time: summed (parallel calls overlap, so it
                # can pass `app`) and the slowest one.
                waits = _DB_MS.get() or []
                if waits:
                    timing += (f", db_wait;desc=\"db time, summed\";dur={sum(waits):.0f}"
                               f", db_slowest;desc=\"slowest db call\";dur={max(waits):.0f}")
                existing = response.headers.get("Server-Timing")
                response.headers["Server-Timing"] = f"{existing}, {timing}" if existing else timing
                if ms >= SLOW_REQUEST_MS:
                    laps = _LAPS.get() or []
                    logging.getLogger("request_timing").info(
                        "slow request %s %s status=%s ms=%.0f db_calls=%d%s",
                        request.method, request.path, response.status_code, ms, calls,
                        f" parts={','.join(laps)}" if laps else "")
        except Exception:  # noqa: BLE001 -- the stopwatch never breaks a response
            logging.getLogger("request_timing").warning("timing failed", exc_info=True)
        return response

    @app.teardown_request
    def _clear_request_id(_exc: Any) -> None:
        _REQUEST_ID.set(NO_REQUEST)
        _DB_CALLS.set(None)
        _DB_MS.set(None)
        _LAPS.set(None)
