#!/usr/bin/env python3
"""RQ worker entrypoint — the dedicated Railway worker service.

Boot sequence (order matters):
  1. env + logging + Sentry (worker exceptions must reach Sentry exactly
     like web ones — sentry-sdk's default integrations cover plain
     processes; the Flask integration is web-only on purpose).
  2. PRE-IMPORT the analysis stack + warm librosa's numba JIT in THIS
     parent process. RQ forks a work horse per job, and fork inherits the
     parent's memory — so the ~27s JIT (see gunicorn_conf.py, same
     contract) is paid once per deploy here, not once per job.
  3. Boot sweep: recover jobs orphaned by the previous deploy.
  4. Start (or restart) the self-rescheduling sweep chain THROUGH the
     queue (services/pipeline_jobs.py::run_sweep_loop — fork-isolated, so
     no db-touching threads live in this parent to share sockets with
     forked children).
  5. Block in rq.Worker.work(with_scheduler=True) — the scheduler serves
     the delayed retry / sweep-chain enqueues.

Run: sh bin/railway-worker.sh (locates ffmpeg first, exactly like the
web entrypoint). Requires REDIS_URL; exits non-zero without it so
Railway shows a crisp crash instead of a silent idle service.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Same root configuration the web process now uses (2026-08-12). Shared
# rather than duplicated because PIPELINE_QUEUE_ENABLED decides which of the
# two services runs the pipeline, so a take's timing lines can land in either
# log — and "pipeline timing session=…" has to look the same in both.
from services.logging_setup import configure_logging  # noqa: E402

configure_logging()
logger = logging.getLogger("pipeline-worker")


def _enforce_secrets() -> None:
    """Same boot-time secret audit as the web service.

    The worker holds MORE dangerous credentials than the web process (it
    writes storage and runs the pipeline unattended), so a placeholder or
    truncated key here has to be just as fatal. Letting the worker start
    with a broken credential is worse than a crash: jobs get claimed,
    fail, and burn their retries.
    """
    from services.secrets import enforce_at_boot

    enforce_at_boot()

    # WHICH SNIPPET TABLE DOES *THIS* PROCESS SEE?
    #
    # The worker is a SEPARATE RAILWAY SERVICE (see the Procfile), and Railway
    # variables are PER-SERVICE. So SNIPPETS_TABLE can be set on the web
    # service and absent here — and this process is a snippet WRITER
    # (analysis_worker -> process_lab_recording -> create_charisma_snippets_
    # bulk), whose failures are swallowed by design. Mid-rename, that split is
    # invisible: the web app looks healthy while every job the worker
    # processes drops its snippets.
    #
    # app.py runs this same probe for the web service. The worker needs its
    # own copy precisely BECAUSE its environment is a different environment —
    # discovered 2026-08-10, when only the web service had been updated.
    #
    # Never fatal, unlike enforce_at_boot above: a wrong table name is
    # recoverable by setting a variable, and refusing to start would turn a
    # config fix into an outage. It is loud instead.
    try:
        from services.snippet_tables import check_at_boot as snippets_check
        snippets_check()
    except Exception as e:  # pragma: no cover — belt
        logger.warning("snippet table probe failed: %s", e)


def worker_count() -> int:
    """How many jobs this container processes at once (WORKER_COUNT).

    Default 2: enough that recording while another take is mid-flight does
    not queue, which is the realistic near-term case. Each slot is a separate
    process holding its own copy of the analysis stack (~0.5-1 GB resident,
    plus the decoded PCM of whatever take it is on — a 60-minute take is
    ~230 MB), so RAM scales roughly linearly. Past ~4 slots, add REPLICAS
    instead: the claim CAS and the dedup index make replicas safe, and they
    fail independently.

    Set WORKER_COUNT=1 on a memory-tight container.
    """
    raw = (os.getenv("WORKER_COUNT") or "").strip()
    try:
        return max(1, int(raw)) if raw else 2
    except ValueError:
        return 2


def _init_sentry() -> None:
    try:
        import sentry_sdk
        from config import Config
        cfg = Config()
        if cfg.SENTRY_DSN:
            # Same sampling story as app.py: 1.0 meant a transaction per
            # job (and per queue poll), which burns the quota that error
            # capture depends on. Errors are still captured unsampled.
            sentry_sdk.init(
                dsn=cfg.SENTRY_DSN,
                traces_sample_rate=cfg.SENTRY_TRACES_SAMPLE_RATE,
                profiles_sample_rate=cfg.SENTRY_PROFILES_SAMPLE_RATE,
                environment=cfg.ENV,
                release=cfg.RELEASE_SHA or None,
                send_default_pii=False,
                max_request_body_size="never",
            )
            logger.info("sentry initialized (env=%s traces=%.3f)",
                        cfg.ENV, cfg.SENTRY_TRACES_SAMPLE_RATE)
    except Exception as e:
        logger.warning("sentry init skipped: %s", e)


def _warm_analysis_stack() -> None:
    """Import the pipeline modules + pay librosa's numba JIT once, here in
    the parent, so every forked work horse inherits them warm. Best-effort:
    an unwarmed worker degrades to a slow first job, never a crash."""
    try:
        import services.pipeline_jobs  # noqa: F401
        import services.analysis_worker  # noqa: F401
        import services.lab_recording  # noqa: F401
    except Exception as e:
        logger.warning("pipeline module pre-import failed: %s", e)
    try:
        import numpy as np
        import librosa

        y = np.zeros(16000, dtype="float32")
        librosa.feature.mfcc(y=y, sr=16000, n_mfcc=13)
        librosa.feature.chroma_stft(y=y, sr=16000)
        logger.info("librosa numba JIT warmed (pid=%s)", os.getpid())
    except Exception as e:
        logger.warning("librosa warmup skipped: %s", e)


def _preflight() -> list:
    """Names of REQUIRED env vars that are missing.

    The worker shares the web service's whole config: it re-downloads the
    take from object storage, writes through services.db, and calls
    Whisper/LLMs itself. A missing SUPABASE_URL used to surface as a
    supabase traceback from a module import three frames deep, once per
    restart — this turns that into one actionable line naming what to set
    in the Railway service.
    """
    required = (
        "SUPABASE_URL",           # services.db — hard requirement
        "SUPABASE_SERVICE_ROLE_KEY",
        "OPENAI_API_KEY",         # Whisper + the analysis LLM calls
        "REDIS_URL",              # the broker
    )
    return [name for name in required if not (os.getenv(name) or "").strip()]


def main() -> int:
    _enforce_secrets()
    _init_sentry()

    missing = _preflight()
    if missing:
        logger.error(
            "missing required env var(s): %s — the worker service needs the "
            "SAME variables as the web service (Supabase, OpenAI, R2/storage, "
            "Resend) PLUS REDIS_URL and PIPELINE_QUEUE_ENABLED=1. In Railway: "
            "worker service → Variables. See docs/ASYNC-PIPELINE-QUEUE.md §3.",
            ", ".join(missing),
        )
        return 1

    from services import job_queue

    # for_worker=True: no socket read timeout. rq's dequeue is a BLOCKING
    # BLPOP that waits ~415s for a job, so a short socket_timeout aborts it
    # and rq quits ("Redis connection timeout") on a healthy broker.
    conn = job_queue.get_redis(for_worker=True)
    if conn is None:
        logger.error("REDIS_URL missing or broker unreachable — the worker "
                     "service cannot run without its broker.")
        return 1
    try:
        conn.ping()
    except Exception as e:
        logger.error("redis ping failed: %s", e)
        return 1

    _warm_analysis_stack()

    # Recover whatever the previous deploy orphaned, then keep a sweep
    # chain alive through the queue itself.
    from services import pipeline_jobs
    try:
        counts = pipeline_jobs.sweep_stale_jobs()
        logger.info("boot sweep: %s", counts)
    except Exception as e:
        logger.warning("boot sweep failed: %s", e)
    # ONE CHAIN, NOT ONE PER BOOT. run_sweep_loop re-enqueues itself in a
    # `finally`, so a chain never ends — and this used to start a fresh one
    # every boot. Ten restarts left ten immortal chains sweeping in parallel,
    # which is what "eleven sweeps in four seconds" was: not a hot loop,
    # eleven accumulated chains coming due together.
    #
    # The lease value is the chain's IDENTITY (handoff 2026-08-10 §6.5): the
    # chain carries this id through every re-enqueue and re-arms only while
    # the key still holds it, so an accumulated duplicate drains itself
    # within one interval instead of renewing a shared flag forever. A dead
    # chain's key expires and the next boot takes over.
    try:
        import uuid as _uuid
        interval = pipeline_jobs.sweep_interval_seconds()
        chain_id = _uuid.uuid4().hex
        if job_queue.acquire_sweep_lease(
                chain_id,
                ttl_seconds=interval * pipeline_jobs.SWEEP_LEASE_INTERVALS):
            job_queue.enqueue(pipeline_jobs.SWEEP_LOOP_PATH, chain_id,
                              delay_seconds=interval)
            logger.info("sweep chain %s started (every %ss)",
                        chain_id, interval)
        else:
            logger.info("sweep chain already running elsewhere — not starting "
                        "a second")
    except Exception as e:
        logger.warning("sweep chain start failed: %s", e)

    slots = worker_count()
    if slots == 1:
        logger.info("worker starting on queue '%s' (1 slot, job timeout %ss)",
                    job_queue.queue_name(), job_queue.job_timeout_seconds())
        _run_worker_loop(conn, with_scheduler=True)
        return 0

    logger.info("worker starting on queue '%s' (%d slots, job timeout %ss)",
                job_queue.queue_name(), slots,
                job_queue.job_timeout_seconds())
    return _run_worker_pool(slots)


def _run_worker_loop(conn, *, with_scheduler: bool) -> None:
    """Block in one rq worker. Never returns until the worker stops."""
    from rq import Queue, Worker

    from services import job_queue
    q = Queue(job_queue.queue_name(), connection=conn)
    # with_scheduler: serves enqueue_in (delayed retries + the sweep chain).
    # rq guards it with a lock, so it is safe on every slot — but only slot 0
    # asks for it, since one scheduler is all the queue needs.
    Worker([q], connection=conn).work(with_scheduler=with_scheduler)


def _worker_child(slot: int) -> None:
    """Entrypoint for one forked slot.

    The FIRST thing it does is drop the inherited Redis connection: pools are
    not fork-safe, and siblings sharing the parent's socket would interleave
    their replies. Everything expensive (imports, the numba JIT) is inherited
    warm from the parent — that is the whole reason to fork rather than spawn.
    """
    import signal

    # Drop the POOL's signal handlers, which fork handed us. They close over
    # the parent's process table, so running one here raises "can only test a
    # child process" and takes the slot down on every shutdown. Back to
    # default until rq installs its own graceful handlers in work().
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    from services import job_queue as jq
    jq.reset_connections()
    # The DB client is fork-inherited too, and for the same reason: `db =
    # DatabaseService()` runs at import, and the parent touches Supabase
    # (warm-up, boot sweep) BEFORE forking. Two slots sharing one TLS session
    # corrupt each other — SSLV3_ALERT_BAD_RECORD_MAC / "EOF occurred in
    # violation of protocol" — and every DB call in this slot swallows the
    # error and returns nothing, so the slot looks alive and does no work.
    try:
        from services.db import db as _db
        _db.reset_connections()
    except Exception as e:
        logger.error("slot %d: db connection reset failed (%s) — this slot "
                     "shares the parent's TLS socket and its reads will "
                     "corrupt", slot, e)

    conn = jq.get_redis(for_worker=True)
    if conn is None:
        logger.error("slot %d: no broker connection", slot)
        return
    logger.info("slot %d listening (pid=%s)", slot, os.getpid())
    _run_worker_loop(conn, with_scheduler=(slot == 0))


def _run_worker_pool(slots: int) -> int:
    """Fork N worker slots and keep them alive.

    A slot that dies (OOM, a killed work horse taking its parent down, an rq
    shutdown) is restarted, so losing one slot degrades throughput instead of
    silently halving it forever. SIGTERM — how Railway ends a deploy — stops
    the pool cleanly rather than orphaning children.
    """
    import multiprocessing
    import signal

    ctx = multiprocessing.get_context("fork")  # inherit the warmed stack
    procs: Dict[int, Any] = {}
    stopping = {"flag": False}

    def _stop(signum, _frame):
        stopping["flag"] = True
        logger.info("received signal %s — stopping %d slot(s)",
                    signum, len(procs))
        for p in procs.values():
            if p.is_alive():
                p.terminate()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    for slot in range(slots):
        p = ctx.Process(target=_worker_child, args=(slot,),
                        name=f"pipeline-slot-{slot}", daemon=False)
        p.start()
        procs[slot] = p

    while not stopping["flag"]:
        for slot, p in list(procs.items()):
            p.join(timeout=1)
            if stopping["flag"]:
                break
            if not p.is_alive():
                logger.warning("slot %d died (exit %s) — restarting",
                               slot, p.exitcode)
                fresh = ctx.Process(target=_worker_child, args=(slot,),
                                    name=f"pipeline-slot-{slot}", daemon=False)
                fresh.start()
                procs[slot] = fresh
    for p in procs.values():
        p.join(timeout=30)
    return 0


if __name__ == "__main__":
    sys.exit(main())
