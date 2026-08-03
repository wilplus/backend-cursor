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

_redis_conn = None  # cached broker connection (per process)


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


def get_redis():
    """Lazily build (and cache) the Redis connection. None on any failure."""
    global _redis_conn
    if _redis_conn is not None:
        return _redis_conn
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        return None
    try:
        import redis  # lazy: package absent → queue silently off
        _redis_conn = redis.from_url(
            url,
            # Fail fast: a dead broker must cost the upload route
            # milliseconds (then fall back to sync), never hang it.
            socket_connect_timeout=2,
            socket_timeout=5,
        )
        return _redis_conn
    except Exception as e:
        logger.warning("job_queue: redis unavailable: %s", e)
        return None


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
