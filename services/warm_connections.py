"""Keep a web worker's outbound connections warm (founder 2026-10-14).

The stopwatch showed every request at the moment the app opened waiting
about 1.5 s together, with one database question each: after a quiet spell
the worker had to reopen its pooled database connection (Supabase closes
idle ones). A tiny read every PING_EVERY_S keeps that connection open, so
opening the app costs nothing extra. Started once per gunicorn worker
(gunicorn_conf.post_worker_init), never in the job worker or in tests.
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

PING_EVERY_S = 45.0
_started = False


def _ping_once() -> None:
    from services.db import db
    db.client.table("runtime_config").select("key").limit(1).execute()


def _warm_signing_keys() -> None:
    from auth import get_jwks_client
    get_jwks_client().get_signing_keys()


def _loop(stop: threading.Event) -> None:
    try:
        _warm_signing_keys()
    except Exception:  # noqa: BLE001 -- a cold key fetch is only slower
        logger.warning("warm_connections: signing keys not warmed", exc_info=True)
    while not stop.wait(PING_EVERY_S):
        try:
            _ping_once()
        except Exception:  # noqa: BLE001 -- the next request reconnects anyway
            logger.warning("warm_connections: ping failed", exc_info=True)


def start() -> None:
    """Start the keep-warm thread once in this process (idempotent)."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, args=(threading.Event(),),
                     name="warm-connections", daemon=True).start()
