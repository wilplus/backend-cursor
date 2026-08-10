"""Redis/RQ glue for the durable recording pipeline (F1-SURFACE).

Design contract (see migrations/add_processing_jobs.sql):

  * Redis is a DELIVERY mechanism only. Job state of record lives in
    Postgres (processing_jobs) — a wiped Redis loses nothing but latency,
    because the sweeper re-enqueues from the table.
  * Everything here degrades gracefully: missing redis/rq packages, an
    unset REDIS_URL, or a dead broker make `queue_enabled()` false /
    `enqueue()` return False, and the upload route falls back to the
    daemon-thread or synchronous path. Enabling the queue can therefore
    never take down the live loop.

Env:
  PIPELINE_QUEUE_ENABLED   default 0 — master switch for the queue path.
  REDIS_URL                broker address (Railway Redis plugin exposes it).
  PIPELINE_QUEUE_NAME      default "pipeline".
  PIPELINE_JOB_TIMEOUT_SECONDS  default 3600 — RQ kills the work horse
                           after this; the Postgres sweeper then recovers
                           the job row (attempts cap applies).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Cached broker connections, per process, keyed by profile
# ("client" = fail-fast enqueue side, "worker" = blocking-dequeue side).
_redis_conns: dict = {}


def _flag(name: str, default: str = "0") -> bool:
    return (os.getenv(name) or default).strip().lower() in ("1", "true", "yes")


def queue_name() -> str:
    return (os.getenv("PIPELINE_QUEUE_NAME") or "pipeline").strip() or "pipeline"


def job_timeout_seconds() -> int:
    raw = (os.getenv("PIPELINE_JOB_TIMEOUT_SECONDS") or "").strip()
    try:
        return max(60, int(raw)) if raw else 3600
    except ValueError:
        return 3600


def queue_configured() -> bool:
    """Flag on + a broker URL present. Does NOT probe the broker."""
    return _flag("PIPELINE_QUEUE_ENABLED") and bool(
        (os.getenv("REDIS_URL") or "").strip()
    )


def get_redis(*, for_worker: bool = False):
    """Lazily build (and cache) a Redis connection. None on any failure.

    TWO PROFILES, because the two sides want opposite things:

    * ``for_worker=False`` (the web/enqueue side) — fail fast. A dead broker
      must cost the upload route milliseconds before it falls back to the
      sync path, never hang it. LPUSH is instant, so a 5s read timeout is
      generous.

    * ``for_worker=True`` (the RQ worker) — NO read timeout. The worker
      dequeues with a BLOCKING BLPOP that legitimately waits minutes for a
      job (rq's dequeue_timeout is DEFAULT_WORKER_TTL-5 ≈ 415s). A short
      ``socket_timeout`` aborts that blocking read and rq treats it as a
      dead broker: "Redis connection timeout, quitting..." exactly
      socket_timeout seconds after "Listening on ...", on a perfectly
      healthy Redis. ``health_check_interval`` keeps the long-lived
      connection honest instead.
    """
    key = "worker" if for_worker else "client"
    cached = _redis_conns.get(key)
    if cached is not None:
        return cached
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        return None
    try:
        import redis  # lazy: package absent → queue silently off
        if for_worker:
            conn = redis.from_url(
                url,
                socket_connect_timeout=5,
                # socket_timeout deliberately UNSET — see docstring.
                health_check_interval=30,
            )
        else:
            conn = redis.from_url(
                url,
                socket_connect_timeout=2,
                socket_timeout=5,
            )
        _redis_conns[key] = conn
        return conn
    except Exception as e:
        logger.warning("job_queue: redis unavailable: %s", e)
        return None


SWEEP_LEASE_KEY = "willab:pipeline:sweep-chain"
# The pre-ownership lease wrote this constant. It carried no identity, which
# is precisely why nine chains renewing one key were indistinguishable from
# one healthy chain (handoff 2026-08-10 §6.5) — the lease answered "does SOME
# chain exist?", never "am I the chain?".
_LEGACY_LEASE_VALUE = "1"


def _lease_value(conn) -> str:
    """The current lease holder's chain id, or "" when the key is absent."""
    raw = conn.get(SWEEP_LEASE_KEY)
    if raw is None:
        return ""
    return raw.decode() if isinstance(raw, bytes) else str(raw)


def acquire_sweep_lease(chain_id: str, *, ttl_seconds: int) -> bool:
    """True if THIS boot may start a sweep chain, as owner `chain_id`.

    WHY A LEASE. `run_sweep_loop` re-enqueues itself in a `finally`, so a
    chain never ends; and worker.py started a NEW one on every boot. A worker
    that restarts ten times therefore leaves ten immortal chains sweeping in
    parallel — which is what "eleven sweeps in four seconds" was. Not a hot
    loop: eleven accumulated chains all coming due at once.

    WHY THE VALUE IS AN IDENTITY (2026-08-10, §6.5). The first lease stored a
    constant, so it could only gate STARTING chains — the accumulated ones all
    renewed the shared key and were immortal by construction. The value is now
    the owning chain's id, and every iteration re-checks ownership before
    re-enqueueing (renew_sweep_lease below): a chain that is not the owner
    simply does not re-arm, so duplicates drain themselves within one
    interval instead of accumulating forever.

    A LEGACY-FORMAT KEY IS CLAIMED, NOT RESPECTED. If this boot finds the old
    constant in the key, honoring it would recreate the exact gap it was
    written to prevent: the legacy chains die on their next firing (no id →
    no re-enqueue), the key would sit unowned until it expired, and no boot
    happens between deploys to re-acquire — zero sweepers until someone
    ships. So the boot overwrites the legacy value with its own id and takes
    the chain over. Two replicas racing this both "win" for one interval;
    the per-iteration ownership check converges them to one.

    Fails CLOSED — no broker means no lease means no chain, and the web-boot
    sweep plus POST /v2/internal/jobs/sweep remain the backstops.
    """
    conn = get_redis()
    if conn is None:
        return False
    try:
        if bool(conn.set(SWEEP_LEASE_KEY, chain_id, nx=True,
                         ex=ttl_seconds)):
            return True
        if _lease_value(conn) == _LEGACY_LEASE_VALUE:
            return bool(conn.set(SWEEP_LEASE_KEY, chain_id, xx=True,
                                 ex=ttl_seconds))
        return False
    except Exception as e:
        logger.warning("job_queue: sweep lease acquire failed: %s", e)
        return False


def renew_sweep_lease(chain_id: str, *, ttl_seconds: int) -> bool:
    """Hold the chain open for another interval — IF this chain still owns it.

    Returns ownership, and the caller re-enqueues ONLY on True: this is the
    per-iteration check that makes duplicate chains mortal. Three answers:

      * key absent → take over (SET NX). The previous owner died mid-interval;
        the first chain to fire afterwards adopts the lease rather than dying
        with it, so the queue can never end up with zero sweepers.
      * key holds OUR id → refresh the TTL, keep going.
      * key holds ANOTHER id → False. This iteration was the chain's last.

    The GET-then-SET pair is not atomic and deliberately so: the race's worst
    case is two chains each believing ownership for ONE interval, after which
    exactly one id matches and the other exits. Sweeps are CAS-guarded and
    cheap, so a transient duplicate costs a few reads — a Lua script would
    buy nothing worth its opacity here.

    On a broker ERROR (not absence): True — fail OPEN. A transiently
    duplicated sweep is CAS-safe; a stopped chain is not, and the boot-time
    acquire only runs at deploys.
    """
    conn = get_redis()
    if conn is None:
        # No broker → the re-enqueue below it would fail anyway; report
        # ownership so the caller's enqueue attempt is what decides.
        return True
    try:
        if bool(conn.set(SWEEP_LEASE_KEY, chain_id, nx=True,
                         ex=ttl_seconds)):
            return True
        if _lease_value(conn) == chain_id:
            conn.set(SWEEP_LEASE_KEY, chain_id, ex=ttl_seconds)
            return True
        return False
    except Exception as e:
        logger.warning("job_queue: sweep lease renew failed: %s", e)
        return True


def reset_connections() -> None:
    """Drop cached connections so the next get_redis() builds fresh ones.

    MUST be called in a freshly forked child: redis-py connection pools are
    NOT fork-safe, and two processes sharing one socket interleave their
    replies. The multi-slot worker (worker.py) forks, so each child resets
    and dials its own.
    """
    _redis_conns.clear()


def get_queue():
    """RQ Queue on the shared connection, or None."""
    conn = get_redis()
    if conn is None:
        return None
    try:
        from rq import Queue
        return Queue(queue_name(), connection=conn)
    except Exception as e:
        logger.warning("job_queue: rq unavailable: %s", e)
        return None


def enqueue(func_path: str, *args: Any, delay_seconds: int = 0,
            rq_job_id: Optional[str] = None) -> bool:
    """Enqueue a dotted-path callable. True on success, False on ANY failure
    (caller falls back — never raises into the upload route).

    func_path is a string ("services.pipeline_jobs.run_processing_job") so
    the WEB process never imports the worker's task module (keeps the
    upload route's import graph light and one-directional).
    """
    q = get_queue()
    if q is None:
        return False
    try:
        kwargs = {
            "job_timeout": job_timeout_seconds(),
            # Results live in Postgres; keep Redis lean.
            "result_ttl": 0,
            "failure_ttl": 7 * 24 * 3600,
        }
        if rq_job_id:
            kwargs["job_id"] = rq_job_id
        if delay_seconds > 0:
            from datetime import timedelta
            q.enqueue_in(timedelta(seconds=delay_seconds), func_path, *args,
                         **kwargs)
        else:
            q.enqueue(func_path, *args, **kwargs)
        return True
    except Exception as e:
        logger.warning("job_queue: enqueue failed (%s): %s", func_path, e)
        return False
