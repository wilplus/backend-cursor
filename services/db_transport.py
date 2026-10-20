"""The PostgREST transport: a connection pool, and retried reads (founder
2026-10-14 and 2026-10-16).

Out of the box the Supabase client talks to PostgREST over one HTTP/2 connection.
When that connection sits idle the far side closes it, and the next request
on it fails with ``RemoteProtocolError: Server disconnected``; Sentry showed
it on the booking page, the booking slots and ``/v2/user/asks/next`` in the
same few seconds. Most call sites run ``.execute()`` directly, not through
``DatabaseService._execute_with_retry``, so one stale socket became a 500.

This patches the PostgREST session's ``request`` once, for every call site:
a read (GET/HEAD) that fails this way is sent again on a fresh connection
(httpx drops the dead one from the pool). A write is never resent here, since
the server may already have applied it; a refused connection (nothing sent)
is retried for any method.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_READS = {"GET", "HEAD"}
_PAUSES_S = (0.0, 0.25)  # two more tries: at once, then after a short wait


def _resendable(method: str, err: Exception) -> bool:
    if isinstance(err, httpx.ConnectError):
        return True
    if method.upper() not in _READS:
        return False
    if isinstance(err, (httpx.RemoteProtocolError, httpx.ReadError)):
        return True
    msg = str(err).lower()
    return "server disconnected" in msg or "connection reset by peer" in msg


def _short_path(url: Any) -> str:
    """``/rest/v1/user_settings`` -> ``user_settings``; never raises."""
    path = getattr(url, "path", None) or str(url).split("?", 1)[0]
    return str(path).rsplit("/", 1)[-1] or str(path)


# ── One connection per request, not one socket per process ──────────────
#
# postgrest builds its httpx session with ``http2=True``: one TCP socket per
# process that every gunicorn thread multiplexes over, read under a single
# lock. The founder's boot stopwatch (2026-10-16) showed the cost: fourteen
# requests arriving together all took 3.5–4.7 s, including ones with three
# database calls, while the same calls a second later took 0.5 s. A thread
# whose answer had already arrived stayed parked until the next frame came
# down the shared socket, and after the fast answers were drained the next
# frame belonged to the slowest request. An HTTP/1.1 pool gives each
# in-flight call its own connection, so nobody waits for a stranger's reply.
# ``DB_HTTP2=1`` restores the old transport without a deploy.

POOL_SIZE = max(1, int((os.getenv("DB_HTTP_POOL_SIZE") or "16").strip() or 16))
KEEPALIVE_S = 30.0  # drop idle sockets before Supabase does (then nothing stale is reused)
USE_HTTP2 = (os.getenv("DB_HTTP2") or "").strip().lower() in {"1", "true", "yes"}


def _pooled_session(SyncClient: type, base_url, headers, timeout, verify: bool = True):
    return SyncClient(
        base_url=base_url,
        headers=headers,
        timeout=timeout,
        verify=verify,
        follow_redirects=True,
        http2=False,
        limits=httpx.Limits(
            max_connections=POOL_SIZE,
            max_keepalive_connections=POOL_SIZE,
            keepalive_expiry=KEEPALIVE_S,
        ),
    )


def _install_pool() -> None:
    if USE_HTTP2:
        logger.info("db_transport: DB_HTTP2 set; keeping postgrest's HTTP/2 session")
        return
    try:
        from postgrest._sync.client import SyncPostgrestClient
        from postgrest.utils import SyncClient
    except Exception:
        logger.warning("db_transport: postgrest client not found; default transport", exc_info=True)
        return
    if getattr(SyncPostgrestClient, "_willab_pooled", False):
        return

    def create_session(self, base_url, headers, timeout, verify: bool = True):
        return _pooled_session(SyncClient, base_url, headers, timeout, verify)

    setattr(SyncPostgrestClient, "create_session", create_session)
    setattr(SyncPostgrestClient, "_willab_pooled", True)


def install() -> None:
    """Idempotent; called when services.db is imported."""
    _install_pool()
    try:
        from postgrest.utils import SyncClient
    except Exception:
        logger.warning("db_transport: postgrest SyncClient not found; no retry", exc_info=True)
        return
    if getattr(SyncClient, "_willab_read_retry", False):
        return
    original = SyncClient.request

    from services.request_context import add_db_time, count_db_call, lap

    def request(self, method, url, *args, **kwargs):
        count_db_call()
        started = time.perf_counter()
        try:
            return _send(self, method, url, *args, **kwargs)
        finally:
            add_db_time((time.perf_counter() - started) * 1000)

    def _send(self, method, url, *args, **kwargs):
        attempt = 0
        while True:
            try:
                # One lap per call, so a slow request's log line says which
                # call waited (``parts=db:GET user_settings:3100,...``).
                with lap(f"db:{method} {_short_path(url)}"):
                    return original(self, method, url, *args, **kwargs)
            except Exception as err:
                if attempt >= len(_PAUSES_S) or not _resendable(str(method), err):
                    raise
                # One line, no traceback (founder 2026-10-20): a dropped
                # connection fails every request in flight at once, and their
                # tracebacks hit Railway's 500 lines/s cap and dropped the
                # rest of the log. A read that still fails after the last try
                # raises, so the caller and Sentry keep its full trace.
                logger.warning(
                    "db_transport: %s %s dropped (%s: %s), resending (try %d)",
                    method, url, type(err).__name__, " ".join(str(err).split())[:200],
                    attempt + 2,
                )
                time.sleep(_PAUSES_S[attempt])
                attempt += 1

    setattr(SyncClient, "request", request)
    setattr(SyncClient, "_willab_read_retry", True)
