"""Keep one rq scheduler alive per queue, through a deploy.

WHY NOT ``Worker.work(with_scheduler=True)`` (rq 1.16.2, read from the
installed source, founder 2026-10-15). A delayed job (``enqueue_in``: the
retry backoff, the sweep chain) sits in the ScheduledJobRegistry until a
scheduler moves it onto the queue. rq guards the scheduler with a Redis lock
per queue (``rq:scheduler-lock:<queue>``, TTL 61 s, refreshed every second
by its heartbeat). The worker asks for that lock exactly once at boot
(``Worker._start_scheduler``), and asks again only from
``run_maintenance_tasks``, which runs every ``DEFAULT_MAINTENANCE_TASK_
INTERVAL`` = 600 s and skips the scheduler on its first run. A deploy
starts the new container while the old one still holds the lock, so the new
worker boots without a scheduler and does not ask again for ten minutes:
nothing delayed moved for 6 min 53 s on 2026-10-15 (the 60 s retry of job
affb641b and the sweep chain fired together at 19:24:33, one maintenance
tick after boot).

This keeper runs rq's own scheduler steps (``acquire_locks``,
``enqueue_scheduled_jobs``, ``heartbeat``, ``release_locks``) in a thread
of a process that is always awake, polling for the lock every few seconds
until it holds it, and releasing it the moment the container drains, so the
next container takes over within one poll. It never installs signal
handlers and never forks, which is why it does not call ``RQScheduler.work``
or ``.start``. The scheduler dials its own Redis connection (rq builds one
from the connection it is given), so no socket is shared with the worker.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Iterable, Optional

logger = logging.getLogger(__name__)

POLL_SECONDS = 2.0


def _rq_scheduler(queue_names: Iterable[str], connection: Any) -> Any:
    from rq.scheduler import RQScheduler

    return RQScheduler(list(queue_names), connection=connection, interval=1)


class SchedulerKeeper:
    """One thread that holds the queue's scheduler lock and moves due jobs.

    ``draining`` answers whether this container is shutting down; the keeper
    then releases the lock and stops, so the next container needs no TTL to
    run out. ``scheduler_factory`` exists for the contract test; production
    uses rq's scheduler.
    """

    def __init__(
        self, queue_names: Iterable[str], connection: Any, *,
        draining: Optional[Callable[[], bool]] = None,
        poll_seconds: float = POLL_SECONDS,
        scheduler_factory: Callable[[Iterable[str], Any], Any] = _rq_scheduler,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.queue_names = set(queue_names)
        self.connection = connection
        self.draining = draining or (lambda: False)
        self.poll_seconds = max(0.0, float(poll_seconds))
        self._scheduler_factory = scheduler_factory
        self._sleep = sleep
        self._stop = threading.Event()
        self._scheduler: Any = None
        self._thread: Optional[threading.Thread] = None
        self.ticks = 0

    # ── lifecycle ──────────────────────────────────────────────────────

    def start(self) -> threading.Thread:
        self._thread = threading.Thread(
            target=self.run, name="rq-scheduler-keeper", daemon=True)
        self._thread.start()
        return self._thread

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    @property
    def holds_lock(self) -> bool:
        scheduler = self._scheduler
        return bool(scheduler is not None
                    and set(scheduler.acquired_locks) == self.queue_names)

    # ── the loop ───────────────────────────────────────────────────────

    def run(self) -> None:
        while not self._stop.is_set() and not self.draining():
            self.tick()
            self._sleep(self.poll_seconds)
        self.release()

    def tick(self) -> None:
        """One poll: ask for the lock while it is held elsewhere; while it
        is ours, move every due job and keep the lock alive. A broken Redis
        connection is dropped and dialled again on the next tick."""
        self.ticks += 1
        try:
            if self._scheduler is None:
                self._scheduler = self._scheduler_factory(
                    self.queue_names, self.connection)
            scheduler = self._scheduler
            if set(scheduler.acquired_locks) != self.queue_names:
                got = scheduler.acquire_locks()
                if got:
                    logger.info("scheduler keeper: holding the scheduler "
                                "lock for %s", ", ".join(sorted(got)))
            if scheduler.acquired_locks:
                scheduler.enqueue_scheduled_jobs()
                scheduler.heartbeat()
        except Exception as error:
            logger.warning("scheduler keeper: tick failed (%s: %s); "
                           "dialling again on the next poll",
                           type(error).__name__, error, exc_info=True)
            self._scheduler = None

    def release(self) -> None:
        scheduler = self._scheduler
        if scheduler is None or not scheduler.acquired_locks:
            return
        try:
            held = ", ".join(sorted(scheduler.acquired_locks))
            scheduler.release_locks()
            logger.info("scheduler keeper: released the scheduler lock "
                        "for %s", held)
        except Exception as error:
            logger.warning("scheduler keeper: lock release failed (%s); "
                           "it expires on its own within 61 s", error,
                           exc_info=True)
