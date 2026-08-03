"""Upload defenses for the synchronous multipart routes.

Two guards, both aimed at the same failure: a single request that never
ends. With ``--workers 2`` (bin/railway-web.sh) and ``--timeout 1800``,
two stalled uploads take the whole web service down for 30 minutes.

1. ``read_capped`` — a BOUNDED read.
   The routes checked ``request.content_length`` and then called
   ``audio_file.read()`` with no argument. Content-Length is a client
   assertion: a chunked or mis-declared body sails past the precheck and
   the unbounded read materialises the entire thing in the worker's
   heap. ``read_capped`` copies at most ``max_bytes + 1`` and refuses on
   the overflow byte, so the cap is enforced on what actually arrived
   rather than on what the client claimed.

2. ``Deadline`` — a wall-clock BUDGET across the pipeline stages.
   The sync lab path runs the gate, the upload, transcription and the
   full analysis inline. Each step has its own timeout now (OpenAI
   client timeouts, ffmpeg ``timeout=``), but nothing bounds their SUM,
   so a run where every step is merely slow still parks a worker until
   gunicorn reaps it — and the client sees a dead socket, not an error.
   A Deadline checked at stage boundaries converts that into a clean 504
   with a code the FE can act on.

The deadline is deliberately NOT a hard interrupt (no signals, no
threads): it can only fire between stages. That is the honest bound for
a synchronous WSGI worker, and it's the one that matters — the stalls
seen in practice are "eight slow stages", not "one uninterruptible C
call". The durable queue (PIPELINE_QUEUE_ENABLED) is the real fix for
long work; this is the guardrail for the sync fallback that still runs.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class UploadTooLarge(Exception):
    """Raised by ``read_capped`` when the stream exceeds the cap."""

    def __init__(self, max_bytes: int):
        super().__init__(f"upload exceeds {max_bytes} bytes")
        self.max_bytes = max_bytes


class DeadlineExceeded(Exception):
    """Raised by ``Deadline.check`` once the budget is spent."""

    def __init__(self, stage: str, elapsed: float, budget: float):
        super().__init__(
            f"deadline exceeded at stage={stage} "
            f"({elapsed:.1f}s of {budget:.1f}s)"
        )
        self.stage = stage
        self.elapsed = elapsed
        self.budget = budget


def read_capped(file_storage: Any, max_bytes: int, *,
                chunk_size: int = 1024 * 1024) -> bytes:
    """Read at most ``max_bytes`` from a Werkzeug FileStorage.

    Raises ``UploadTooLarge`` the moment the stream proves longer,
    WITHOUT buffering the excess — we stop at the first byte past the
    cap rather than reading to EOF and measuring afterwards.

    Returns the bytes read (possibly empty; the caller decides whether an
    empty upload is a 400).
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")

    stream = getattr(file_storage, "stream", None) or file_storage
    chunks: list[bytes] = []
    total = 0
    limit = max_bytes + 1  # one byte past the cap proves the overflow
    while total < limit:
        chunk = stream.read(min(chunk_size, limit - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    if total > max_bytes:
        raise UploadTooLarge(max_bytes)
    return b"".join(chunks)


class Deadline:
    """Wall-clock budget for one request's synchronous work.

        deadline = Deadline(seconds=600, label="lab-upload")
        ...
        deadline.check("transcribe")   # raises DeadlineExceeded when spent

    ``seconds <= 0`` disables the deadline entirely (``check`` becomes a
    no-op) so the guard can be turned off by config without touching the
    call sites — the same never-crash-on-a-bad-env contract config.py
    holds everywhere else.
    """

    __slots__ = ("budget", "label", "started_at")

    def __init__(self, seconds: float, *, label: str = "request"):
        self.budget = float(seconds or 0)
        self.label = label
        self.started_at = time.monotonic()

    @property
    def enabled(self) -> bool:
        return self.budget > 0

    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def remaining(self) -> float:
        """Seconds left, or ``float('inf')`` when disabled.

        Useful for handing a shrinking timeout down to a subprocess so
        the child can't outlive the budget on its own.
        """
        if not self.enabled:
            return float("inf")
        return max(0.0, self.budget - self.elapsed())

    def expired(self) -> bool:
        return self.enabled and self.elapsed() >= self.budget

    def check(self, stage: str) -> None:
        """Raise ``DeadlineExceeded`` if the budget is spent.

        Call at stage BOUNDARIES — after a step completes, before the
        next one starts. Checking before a step means we never begin work
        we already know we can't finish.
        """
        if self.expired():
            elapsed = self.elapsed()
            logger.warning(
                "%s: deadline exceeded at stage=%s (%.1fs of %.1fs)",
                self.label, stage, elapsed, self.budget,
            )
            raise DeadlineExceeded(stage, elapsed, self.budget)


def deadline_for(label: str, seconds: Optional[float] = None) -> Deadline:
    """Build a Deadline from config, with an explicit override.

    Reads ``Config.SYNC_UPLOAD_DEADLINE_SECONDS`` when ``seconds`` is
    None. Never raises on a bad config value — a malformed env must not
    take down the upload path (live loop).
    """
    if seconds is None:
        try:
            from config import Config

            seconds = float(getattr(Config(), "SYNC_UPLOAD_DEADLINE_SECONDS", 0)
                            or 0)
        except Exception:  # pragma: no cover - defensive
            seconds = 0
    return Deadline(seconds, label=label)
