"""Keep a web worker's outbound connections warm (founder 2026-10-14).

The stopwatch showed every request at the moment the app opened waiting
about 1.5 s together, with one database question each: after a quiet spell
the worker had to reopen its pooled database connection (Supabase closes
idle ones). A tiny read every PING_EVERY_S keeps that connection open, so
opening the app costs nothing extra. Started once per gunicorn worker
(gunicorn_conf.post_worker_init), never in the job worker or in tests.

Founder 2026-10-18: the status read at app open still took 610 ms for one
database call. The pool (services/db_transport, 2026-10-16) drops a
connection idle for KEEPALIVE_S, and this pinged every 45 s -- so the
connection it meant to keep warm was already gone each time, and the first
request after a quiet spell opened a new TLS connection anyway. The ping
now comes before the pool's own cut-off, and is tied to it so the two
cannot drift apart again.

The same day's Railway line showed what a new connection costs here:
``db:GET v2_student_details:1044, ...:65, ...:61`` -- about a second to
open one, about 60 ms for every call on it afterwards. One warm connection
serves one request at a time, and the app opens with several at once, so
every lane gets its own: the ping is one tiny read per gunicorn thread,
sent together, which leaves that many idle connections in the pool. A ping
that takes longer than a warm call is logged, so the log shows when a
connection had to be reopened anyway.
"""
from __future__ import annotations

import logging
import os
import threading
import time

from services.db_transport import KEEPALIVE_S

logger = logging.getLogger(__name__)

# Before the pool drops an idle connection (db_transport.KEEPALIVE_S), with
# room for a slow ping; never longer than 20 s.
PING_EVERY_S = min(20.0, KEEPALIVE_S * 2 / 3)
# A ping slower than this reopened a connection (a warm call takes ~60 ms).
SLOW_PING_MS = 250.0
_started = False


def _lanes() -> int:
    """How many requests a worker serves at once: gunicorn's threads
    (gunicorn_conf.py reads the same variable, the same way)."""
    try:
        return max(1, int((os.getenv("GUNICORN_THREADS") or "4").strip()))
    except ValueError:
        return 4


def _ping_once() -> None:
    from services.db import db
    started = time.perf_counter()
    db.client.table("runtime_config").select("key").limit(1).execute()
    ms = (time.perf_counter() - started) * 1000.0
    if ms >= SLOW_PING_MS:
        logger.info("warm_connections: ping took %.0f ms (a connection was reopened)", ms)


def _ping_every_lane() -> None:
    """One tiny read per lane, sent together, so the pool keeps one idle
    connection per lane. A lane whose ping fails is only cold."""
    def one() -> None:
        try:
            _ping_once()
        except Exception:  # noqa: BLE001 -- the next request reconnects anyway
            logger.warning("warm_connections: ping failed", exc_info=True)

    pings = [threading.Thread(target=one, name="warm-connections-ping", daemon=True)
             for _ in range(_lanes())]
    for ping in pings:
        ping.start()
    for ping in pings:
        ping.join(timeout=PING_EVERY_S)


def _warm_signing_keys() -> None:
    from auth import get_jwks_client
    get_jwks_client().get_signing_keys()


def _loop(stop: threading.Event) -> None:
    try:
        _warm_signing_keys()
    except Exception:  # noqa: BLE001 -- a cold key fetch is only slower
        logger.warning("warm_connections: signing keys not warmed", exc_info=True)
    while not stop.wait(PING_EVERY_S):
        _ping_every_lane()


def start() -> None:
    """Start the keep-warm thread once in this process (idempotent)."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, args=(threading.Event(),),
                     name="warm-connections", daemon=True).start()
