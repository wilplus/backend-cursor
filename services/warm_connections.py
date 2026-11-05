"""Keep a web worker's outbound connections warm (founder 2026-10-14).

The stopwatch showed every request at the moment the app opened waiting
about 1.5 s together, with one database question each: after a quiet spell
the worker had to reopen its pooled database connection (Supabase closes
idle ones). A tiny read every PING_EVERY_S keeps that connection open, so
opening the app costs nothing extra. Started once per gunicorn worker
(gunicorn_conf.post_worker_init); the job worker holds connections warm for
the length of each Take's job instead (``held_warm``); never in tests.

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

Loading times, 2026-11-05, two widenings:

  * One lane per thread was too few. A single request at app open can read
    eight things at once (the chats list, ``services/chats._LIST_READERS``;
    the Ideal Text's enrichment readers, ``services/ideal_text_enrichment``),
    so one wide request beside the other lanes needs about ``threads - 1 +
    8`` connections, and every one past the warm ones cost a new TLS
    connection. The ping now keeps that many, capped so that a ping round
    always leaves each thread a connection free in the pool
    (``db_transport.POOL_SIZE``): a ping never makes a request wait.
  * The job worker forks a fresh process for every job, so each Take's
    processing began with an empty pool and opened its connections one cold
    second at a time as its stages fanned out. ``held_warm`` opens them at
    the job's first moment, side by side with the job's own first reads, and
    keeps them open until the job ends (``worker.py``). Nothing waits for it.
"""
from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
from typing import Iterator

from services.db_transport import KEEPALIVE_S, POOL_SIZE

logger = logging.getLogger(__name__)

# Before the pool drops an idle connection (db_transport.KEEPALIVE_S), with
# room for a slow ping; never longer than 20 s.
PING_EVERY_S = min(20.0, KEEPALIVE_S * 2 / 3)
# A ping slower than this reopened a connection (a warm call takes ~60 ms).
SLOW_PING_MS = 250.0
# The most database reads one request makes at once (see the docstring).
WIDEST_FAN_OUT = 8
_started = False


def _lanes() -> int:
    """How many requests a worker serves at once: gunicorn's threads
    (gunicorn_conf.py reads the same variable, the same way)."""
    try:
        return max(1, int((os.getenv("GUNICORN_THREADS") or "4").strip()))
    except ValueError:
        return 4


def _web_connections() -> int:
    """How many connections a web worker keeps warm: one wide request beside
    the other lanes, never so many that a ping round fills the pool. With the
    defaults (4 threads, a pool of 16): 11."""
    lanes = _lanes()
    return max(lanes, min(lanes - 1 + WIDEST_FAN_OUT, POOL_SIZE - lanes))


def _ping_once() -> None:
    from services.db import db
    started = time.perf_counter()
    db.client.table("runtime_config").select("key").limit(1).execute()
    ms = (time.perf_counter() - started) * 1000.0
    if ms >= SLOW_PING_MS:
        logger.info("warm_connections: ping took %.0f ms (a connection was reopened)", ms)


def _ping_every_lane(count: int | None = None) -> None:
    """One tiny read per connection to keep, sent together, so the pool keeps
    that many idle connections (a web worker's, unless ``count`` says). A
    ping that fails leaves one connection cold, nothing more."""
    def one() -> None:
        try:
            _ping_once()
        except Exception:  # noqa: BLE001 -- the next request reconnects anyway
            logger.warning("warm_connections: ping failed", exc_info=True)

    pings = [threading.Thread(target=one, name="warm-connections-ping", daemon=True)
             for _ in range(count or _web_connections())]
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


@contextlib.contextmanager
def held_warm(count: int) -> Iterator[None]:
    """Keep ``count`` connections open while the block runs: pinged at once,
    on a thread of their own, then before the pool would drop them. The
    block never waits for a ping; leaving it stops the pings (a ping still
    in flight is a read and finishes on its own)."""
    stop = threading.Event()

    def loop() -> None:
        _ping_every_lane(count)
        while not stop.wait(PING_EVERY_S):
            _ping_every_lane(count)

    threading.Thread(target=loop, name="warm-connections-job", daemon=True).start()
    try:
        yield
    finally:
        stop.set()


def start() -> None:
    """Start the keep-warm thread once in this process (idempotent)."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, args=(threading.Event(),),
                     name="warm-connections", daemon=True).start()
