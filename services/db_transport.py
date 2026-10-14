"""Retry database reads that hit a dropped connection (founder 2026-10-14).

The Supabase client talks to PostgREST over one pooled HTTP/2 connection.
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
import time

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


def install() -> None:
    """Idempotent; called when services.db is imported."""
    try:
        from postgrest.utils import SyncClient
    except Exception:
        logger.warning("db_transport: postgrest SyncClient not found; no retry", exc_info=True)
        return
    if getattr(SyncClient, "_willab_read_retry", False):
        return
    original = SyncClient.request

    def request(self, method, url, *args, **kwargs):
        attempt = 0
        while True:
            try:
                return original(self, method, url, *args, **kwargs)
            except Exception as err:
                if attempt >= len(_PAUSES_S) or not _resendable(str(method), err):
                    raise
                logger.warning(
                    "db_transport: %s %s dropped (%s), resending (try %d)",
                    method, url, type(err).__name__, attempt + 2, exc_info=True,
                )
                time.sleep(_PAUSES_S[attempt])
                attempt += 1

    setattr(SyncClient, "request", request)
    setattr(SyncClient, "_willab_read_retry", True)
