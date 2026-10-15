"""Delayed jobs move within seconds, even right after a deploy.

rq 1.16.2 asks for its scheduler lock once at boot and again only on its
ten-minute maintenance tick, so a container deployed while the previous one
still held the lock moved no delayed job for 6 min 53 s (2026-10-15). The
keeper polls for the lock every few seconds and releases it when the
container drains, so the next one takes over at once.
"""
from __future__ import annotations

from services.scheduler_keeper import SchedulerKeeper


class _Lock:
    """The Redis lock as rq's scheduler sees it: one holder per queue."""

    def __init__(self):
        self.holder = None


class _FakeRQScheduler:
    def __init__(self, names, lock, label):
        self.names = set(names)
        self.lock = lock
        self.label = label
        self.acquired_locks = set()
        self.moved = 0
        self.heartbeats = 0

    def acquire_locks(self):
        if self.lock.holder in (None, self.label):
            self.lock.holder = self.label
            self.acquired_locks = set(self.names)
            return set(self.names)
        return set()

    def enqueue_scheduled_jobs(self):
        self.moved += 1

    def heartbeat(self):
        self.heartbeats += 1

    def release_locks(self):
        if self.lock.holder == self.label:
            self.lock.holder = None
        self.acquired_locks = set()


def _keeper(lock, label, draining):
    made = {}

    def factory(names, _conn):
        made["scheduler"] = _FakeRQScheduler(names, lock, label)
        return made["scheduler"]

    keeper = SchedulerKeeper(
        ["pipeline"], connection=None, draining=draining,
        poll_seconds=0, scheduler_factory=factory, sleep=lambda _s: None,
    )
    return keeper, made


def test_the_new_container_takes_the_lock_as_soon_as_the_old_one_drains():
    lock = _Lock()
    old_draining = {"flag": False}
    old, old_made = _keeper(lock, "old", lambda: old_draining["flag"])
    old.tick()
    assert old.holds_lock and lock.holder == "old"

    new, new_made = _keeper(lock, "new", lambda: False)
    for _ in range(3):
        new.tick()
    # Held elsewhere: the new keeper keeps asking every poll, moves nothing.
    assert not new.holds_lock
    assert new_made["scheduler"].moved == 0

    # SIGTERM on the old container: its keeper releases on the way out.
    old_draining["flag"] = True
    old.run()
    assert lock.holder is None

    new.tick()
    assert new.holds_lock and lock.holder == "new"
    # Holding it, every poll moves the due jobs and keeps the lock alive.
    new.tick()
    assert new_made["scheduler"].moved == 2
    assert new_made["scheduler"].heartbeats == 2


def test_a_broken_connection_is_dialled_again_on_the_next_poll():
    lock = _Lock()
    keeper, made = _keeper(lock, "k", lambda: False)
    keeper.tick()
    made["scheduler"].heartbeat = lambda: (_ for _ in ()).throw(
        ConnectionError("redis gone"))
    keeper.tick()  # fails, drops the scheduler
    first = made["scheduler"]
    keeper.tick()  # a fresh scheduler re-acquires (the old holder is us)
    assert made["scheduler"] is not first
    assert keeper.holds_lock
