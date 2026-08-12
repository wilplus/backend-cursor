"""One root logging configuration, shared by the web and the worker.

WHY THIS EXISTS (founder 2026-08-12: "something is wrong cause a recording
went through and no timer fired!").

The pipeline timers shipped in 8ed31ad and then could not be found in the
Railway logs. Nothing was wrong with the timers: `logging.getLogger(__name__)`
propagates to the ROOT logger, and under gunicorn the root logger has no
handler at all. Gunicorn configures its own `gunicorn.error`/`gunicorn.access`
loggers and leaves root alone, so an unhandled record falls through to
`logging.lastResort` — which is fixed at WARNING. Every `logger.info(...)` in
the entire Flask process was therefore written to nowhere, and had been since
the app was first deployed. That is not just the timers: it is the auto-send
result, the session-globals line, the snippet counts, the intervention funnel
— the whole diagnostic layer this repo keeps adding and then reasoning about
from database queries instead.

The WORKER never had the problem (worker.py has called basicConfig since it
was written), which is exactly why it went unnoticed: whichever service
happened to run the pipeline decided whether its logs existed.

Shared rather than duplicated on purpose. `PIPELINE_QUEUE_ENABLED` moves
`run_full_analysis` between the two services, so a run's timings can land in
either log — if the two processes formatted differently, a founder grepping
"pipeline timing" would get two different-shaped answers depending on a flag
they were not thinking about.
"""
from __future__ import annotations

import logging
import os

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging() -> None:
    """Attach a stdout handler to the root logger, once.

    Best-effort and NON-DESTRUCTIVE by construction: if root already has
    handlers — pytest's capture plugin, gunicorn's `--log-config`, a future
    structured-logging setup — this leaves them exactly as they are. That is
    plain `basicConfig` semantics and the reason `force=True` is deliberately
    NOT passed: stomping a handler someone else installed is how you lose the
    logs a second time, in a way that is harder to find than the first.

    Level comes from LOG_LEVEL (default INFO). An unparseable value falls back
    to INFO rather than raising — this runs during boot, and instrumentation
    that can refuse a deploy is worse than instrumentation that is missing
    (LIVE LOOP).
    """
    level = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    if level not in ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"):
        level = "INFO"
    logging.basicConfig(level=getattr(logging, level), format=FORMAT)

    # Third-party INFO chatter is not what this turned on for. These libraries
    # are called on every take (storage puts, model calls, DB round-trips) and
    # at INFO they bury the pipeline lines in the exact log the founder is
    # scrolling. Errors and warnings from them still come through.
    for noisy in ("httpx", "httpcore", "urllib3", "openai", "hpack",
                  "botocore", "boto3", "s3transfer", "numba", "matplotlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
