"""
STORY    As a speaker, I want a Take stuck at "Working on your take" to be
         closed off rather than spin forever, a broken config to fail fast,
         and my Take not to wait behind someone else's, so that I can always
         record again. (Critical path: record -> process.)
OUTCOME
  O1  A session left in 'processing' with no job is marked 'failed' (which
      stops the polling and offers a re-record).
  O2  One failed write does not stop the sweep: the other orphans are still
      marked 'failed'.
  O3  A config error fails the job and the session at once, without retries.
  O4  WORKER_COUNT=N starts N worker slots, so N Takes process in parallel;
      unset it is 2, and never fewer than 1.
PROVES   O1 -> test_an_orphaned_session_is_marked_failed
         O2 -> test_a_failing_reap_does_not_abort_the_rest
         O3 -> test_config_error_is_terminal_not_retried
         O4 -> test_worker_count_starts_that_many_slots
WHY      "Processing forever" found live 2026-08-04 (no job row to sweep), and
         jobs dead at fetch_audio after 3 retries on missing R2 creds, 2026-08-06.
"""
from __future__ import annotations

import multiprocessing
import signal
import types
from unittest.mock import patch

import pytest

import services.pipeline_jobs as pj
import worker

_SID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_SID2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


class _FakeDb:
    def __init__(self, orphans=None):
        self.orphans = orphans or []
        self.states = []

    def list_orphaned_processing_sessions(self, stale_minutes=30, max_rows=100):
        return self.orphans

    def set_session_analysis_state(self, sid, state, error=None):
        self.states.append((sid, state))
        return True

    @property
    def takes(self):
        # production calls db.takes.<method>(); this fake is its own takes.
        return self


def test_an_orphaned_session_is_marked_failed():
    fake = _FakeDb(orphans=[{"id": _SID}])
    with patch.object(pj, "db", fake):
        assert pj.sweep_orphaned_sessions() == 1
    assert fake.states == [(_SID, "failed")]


def test_a_failing_reap_does_not_abort_the_rest():
    fake = _FakeDb(orphans=[{"id": _SID}, {"id": _SID2}])
    plain = fake.set_session_analysis_state

    def _flaky(sid, state, error=None):
        if sid == _SID:
            raise RuntimeError("write failed")
        return plain(sid, state, error)

    fake.set_session_analysis_state = _flaky
    with patch.object(pj, "db", fake):
        assert pj.sweep_orphaned_sessions() == 1
    assert fake.states == [(_SID2, "failed")]


def test_config_error_is_terminal_not_retried():
    """An env var cannot be fixed by waiting: don't burn 3 attempts."""
    fake = _FakeDb()
    job = {"id": "job-1", "kind": "session_recording", "attempts": 0,
           "max_attempts": 3, "session_id": _SID, "payload": {}}
    fake.get_processing_job = lambda jid: {**job, "status": "pending"}
    fake.claim_processing_job = lambda jid, att: {**job, "status": "processing",
                                                  "attempts": att + 1}
    fake.finishes, fake.releases = [], []
    fake.finish_processing_job = lambda job_id, status, error=None, result=None: \
        fake.finishes.append(status) or True
    fake.release_processing_job_for_retry = lambda job_id, error=None: \
        fake.releases.append(job_id) or True
    fake.update_processing_job = lambda *a, **k: True
    fake_q = types.SimpleNamespace(enqueue=lambda *a, **k: True,
                                   queue_configured=lambda: True)

    def _boom(job):
        raise pj.ConfigMismatchError("missing R2 creds")

    with patch.object(pj, "db", fake), patch.object(pj, "job_queue", fake_q), \
            patch.dict(pj._KIND_RUNNERS, {"session_recording": _boom}):
        pj.run_processing_job("job-1")
    assert fake.finishes[-1] == "failed"
    assert fake.releases == [], "must NOT be requeued"
    assert fake.states[-1] == (_SID, "failed")


@pytest.mark.parametrize("raw, slots", [("3", 3), ("", 2), ("0", 1)])
def test_worker_count_starts_that_many_slots(monkeypatch, raw, slots):
    started: list[int] = []
    handlers: dict = {}

    class _Slot:
        exitcode = 0

        def __init__(self, target, args, name, daemon):
            self.slot = args[0]

        def start(self):
            started.append(self.slot)

        def join(self, timeout=None):
            handlers[signal.SIGTERM](signal.SIGTERM, None)  # the deploy ends the pool

        def is_alive(self):
            return False

    monkeypatch.setenv("WORKER_COUNT", raw)
    monkeypatch.setattr(multiprocessing, "get_context",
                        lambda kind: types.SimpleNamespace(Process=_Slot))
    monkeypatch.setattr(signal, "signal", lambda sig, fn: handlers.__setitem__(sig, fn))
    monkeypatch.setattr(worker, "_start_scheduler_keeper", lambda *a, **k: None)
    monkeypatch.setattr("services.job_queue.get_redis", lambda **k: None)
    assert worker._run_worker_pool(worker.worker_count()) == 0
    assert started == list(range(slots))
