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

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
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


def main() -> int:
    _enforce_secrets()
    _init_sentry()

    from services import job_queue

    conn = job_queue.get_redis()
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
    try:
        job_queue.enqueue(
            pipeline_jobs.SWEEP_LOOP_PATH,
            delay_seconds=pipeline_jobs.sweep_interval_seconds(),
        )
    except Exception as e:
        logger.warning("sweep chain start failed: %s", e)

    from rq import Queue, Worker
    q = Queue(job_queue.queue_name(), connection=conn)
    logger.info("worker starting on queue '%s' (job timeout %ss)",
                q.name, job_queue.job_timeout_seconds())
    # with_scheduler: serves enqueue_in (delayed retries + the sweep chain).
    Worker([q], connection=conn).work(with_scheduler=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
