"""processing_jobs — durable job state for the async recording pipeline.

Covers the three layers that keep a session out of "processing forever"
(async-queue work 2026-08-03):

  1. DatabaseService helpers — exact write shapes (the PGRST204
     phantom-column lesson) + the attempts-CAS claim filter.
  2. services.pipeline_jobs.run_processing_job — at-least-once guards:
     duplicate delivery of a finished job is a no-op, a live worker is
     never doubled, the attempts cap goes terminal AND flips
     v2_sessions.analysis_state to 'failed', a failed run releases +
     re-enqueues with backoff.
  3. sweep_stale_jobs — orphaned 'processing' rows (redeploy killed the
     worker) are released + requeued; exhausted ones go terminal.

Run: python3 -m unittest test_processing_jobs
"""
from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

# Stub heavy deps so services.db / services.pipeline_jobs import without a
# live client / sentry (house pattern — see test_db_session_status.py).
for _m in ("supabase", "sentry_sdk"):
    if _m not in sys.modules:
        sys.modules[_m] = types.ModuleType(_m)
if not hasattr(sys.modules["supabase"], "create_client"):
    sys.modules["supabase"].create_client = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["supabase"].Client = object  # type: ignore[attr-defined]
if not hasattr(sys.modules["sentry_sdk"], "capture_exception"):
    sys.modules["sentry_sdk"].capture_exception = lambda *a, **k: None  # type: ignore[attr-defined]

try:
    from services.db import DatabaseService
    import services.pipeline_jobs as pj
    _IMPORT_ERR = None
except Exception as e:  # pragma: no cover - env/bootstrap guard
    DatabaseService = None  # type: ignore[assignment]
    pj = None  # type: ignore[assignment]
    _IMPORT_ERR = e


_JOB = "33333333-3333-4333-8333-333333333333"
_SID = "44444444-4444-4444-8444-444444444444"


class _Chain:
    """Chainable PostgREST fake capturing one call's shape."""

    def __init__(self, calls, rows):
        self.calls = calls
        self._rows = rows
        self.cap = {}

    def table(self, name):
        self.cap = {"table": name}
        self.calls.append(self.cap)
        return self

    def insert(self, payload):
        self.cap["insert"] = payload
        return self

    def update(self, payload):
        self.cap["update"] = dict(payload)
        return self

    def select(self, cols):
        self.cap["select"] = cols
        return self

    def eq(self, col, val):
        self.cap.setdefault("eq", []).append((col, val))
        return self

    def in_(self, col, vals):
        self.cap.setdefault("in_", []).append((col, list(vals)))
        return self

    def lt(self, col, val):
        self.cap.setdefault("lt", []).append((col, val))
        return self

    def limit(self, n):
        self.cap["limit"] = n
        return self

    def execute(self):
        return types.SimpleNamespace(data=self._rows)


@unittest.skipIf(DatabaseService is None, f"import failed: {_IMPORT_ERR}")
class ProcessingJobsDbShapeTests(unittest.TestCase):

    def _svc(self, rows):
        svc = DatabaseService.__new__(DatabaseService)  # skip __init__
        calls = []
        svc.client = _Chain(calls, rows)
        return svc, calls

    def test_create_inserts_pending_row(self):
        svc, calls = self._svc([{"id": _JOB}])
        row = svc.create_processing_job(
            kind="session_recording", user_id="u1", session_id=_SID,
            dedup_key=f"session_recording:{_SID}",
            payload={"bucket": "b", "storage_key": "k"},
        )
        self.assertEqual(row, {"id": _JOB})
        ins = calls[0]["insert"]
        self.assertEqual(calls[0]["table"], "processing_jobs")
        self.assertEqual(ins["status"], "pending")
        self.assertEqual(ins["attempts"], 0)
        self.assertEqual(ins["max_attempts"], 3)
        self.assertEqual(ins["payload"], {"bucket": "b", "storage_key": "k"})

    def test_claim_is_attempts_cas(self):
        svc, calls = self._svc([{"id": _JOB, "attempts": 3}])
        claimed = svc.claim_processing_job(_JOB, 2)
        self.assertIsNotNone(claimed)
        cap = calls[0]
        self.assertEqual(cap["update"]["status"], "processing")
        self.assertEqual(cap["update"]["attempts"], 3)
        self.assertIn(("id", _JOB), cap["eq"])
        # THE guard: the claim only lands if attempts is still what we read.
        self.assertIn(("attempts", 2), cap["eq"])
        self.assertEqual(cap["in_"], [("status", ["pending", "processing"])])

    def test_claim_lost_race_returns_none(self):
        svc, _ = self._svc([])  # CAS matched no row
        self.assertIsNone(svc.claim_processing_job(_JOB, 2))

    def test_finish_completed_shape(self):
        svc, calls = self._svc([{"id": _JOB}])
        self.assertTrue(svc.finish_processing_job(
            _JOB, "completed", result={"snippet_count": 4}))
        up = calls[0]["update"]
        self.assertEqual(up["status"], "completed")
        self.assertEqual(up["percent"], 100)
        self.assertEqual(up["stage"], "completed")
        self.assertIsNone(up["error"])
        self.assertEqual(up["result"], {"snippet_count": 4})

    def test_finish_rejects_non_terminal_status(self):
        svc, calls = self._svc([{"id": _JOB}])
        self.assertFalse(svc.finish_processing_job(_JOB, "processing"))
        self.assertEqual(calls, [])

    def test_release_only_from_processing(self):
        svc, calls = self._svc([{"id": _JOB}])
        self.assertTrue(svc.release_processing_job_for_retry(_JOB, "boom"))
        cap = calls[0]
        self.assertEqual(cap["update"]["status"], "pending")
        self.assertIsNone(cap["update"]["heartbeat_at"])
        self.assertIn(("status", "processing"), cap["eq"])


class _FakeDb:
    """Recorder standing in for services.pipeline_jobs.db."""

    def __init__(self, job=None, claim_result="derive"):
        self.job = job
        self.claim_result = claim_result
        self.claims = []
        self.finishes = []
        self.releases = []
        self.updates = []
        self.states = []
        self.snippet_deletes = []
        self.draft_deletes = []
        self.stale_rows = []

    def get_processing_job(self, job_id):
        return self.job

    def claim_processing_job(self, job_id, expected_attempts):
        self.claims.append((job_id, expected_attempts))
        if self.claim_result == "derive":
            claimed = dict(self.job or {})
            claimed["attempts"] = expected_attempts + 1
            claimed["status"] = "processing"
            return claimed
        return self.claim_result

    def update_processing_job(self, job_id, fields):
        self.updates.append((job_id, fields))
        return True

    def finish_processing_job(self, job_id, status, error=None, result=None):
        self.finishes.append((job_id, status, error, result))
        return True

    def release_processing_job_for_retry(self, job_id, error=None):
        self.releases.append((job_id, error))
        return True

    def set_session_analysis_state(self, sid, state, error=None):
        self.states.append((sid, state, error))
        return True

    def v2_delete_lab_snippets_for_recording(self, rec_id):
        self.snippet_deletes.append(rec_id)
        return 0

    def delete_coach_snippet_drafts_for_session(self, sid):
        self.draft_deletes.append(sid)
        return 0

    def list_stale_processing_jobs(self, stale_minutes=15, max_rows=100):
        return self.stale_rows

    def list_orphaned_processing_sessions(self, stale_minutes=30,
                                          max_rows=100):
        # Orphan reaping has its own suite
        # (test_orphan_sweep_and_concurrency); nothing here exercises it.
        return []


class _FakeQueue:
    def __init__(self, ok=True):
        self.ok = ok
        self.enqueues = []

    def queue_configured(self):
        return True

    def enqueue(self, path, *args, delay_seconds=0, **kw):
        self.enqueues.append((path, args, delay_seconds))
        return self.ok


def _job(status="pending", attempts=0, max_attempts=3, heartbeat_at=None,
         kind="session_recording"):
    return {
        "id": _JOB, "kind": kind, "session_id": _SID, "user_id": "u1",
        "status": status, "attempts": attempts, "max_attempts": max_attempts,
        "heartbeat_at": heartbeat_at,
        "payload": {"session_id": _SID, "recording_id": "rec-1",
                    "bucket": "b", "storage_key": "k"},
    }


@unittest.skipIf(pj is None, f"import failed: {_IMPORT_ERR}")
class RunProcessingJobGuardTests(unittest.TestCase):
    """At-least-once semantics: every guard assumes double delivery."""

    def _run(self, fake_db, fake_q=None, runner=None):
        fake_q = fake_q or _FakeQueue()
        runner = runner or (lambda job: {"snippet_count": 1,
                                         "sent_to_coach": False})
        with patch.object(pj, "db", fake_db), \
                patch.object(pj, "job_queue", fake_q), \
                patch.dict(pj._KIND_RUNNERS,
                           {"session_recording": runner}):
            pj.run_processing_job(_JOB)
        return fake_db, fake_q

    def test_completed_job_redelivery_is_noop(self):
        db, q = self._run(_FakeDb(job=_job(status="completed", attempts=1)))
        self.assertEqual(db.claims, [])
        self.assertEqual(db.finishes, [])
        self.assertEqual(q.enqueues, [])

    def test_fresh_heartbeat_means_live_worker_no_double_run(self):
        hb = datetime.now(timezone.utc).isoformat()
        db, _ = self._run(_FakeDb(job=_job(
            status="processing", attempts=1, heartbeat_at=hb)))
        self.assertEqual(db.claims, [])

    def test_stale_heartbeat_is_reclaimed(self):
        hb = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        db, _ = self._run(_FakeDb(job=_job(
            status="processing", attempts=1, heartbeat_at=hb)))
        self.assertEqual(db.claims, [(_JOB, 1)])
        self.assertEqual(db.finishes[-1][1], "completed")

    def test_attempt_cap_goes_terminal_and_fails_the_session(self):
        db, _ = self._run(_FakeDb(job=_job(attempts=3, max_attempts=3)))
        self.assertEqual(db.claims, [])
        self.assertEqual(db.finishes[-1][1], "failed")
        # The FE must stop polling: analysis_state flips to failed.
        self.assertEqual(db.states[-1][0], _SID)
        self.assertEqual(db.states[-1][1], "failed")

    def test_happy_path_completes_and_readies_the_session(self):
        db, _ = self._run(_FakeDb(job=_job()))
        self.assertEqual(db.claims, [(_JOB, 0)])
        jid, status, _, result = db.finishes[-1]
        self.assertEqual((jid, status), (_JOB, "completed"))
        self.assertEqual(result, {"snippet_count": 1, "sent_to_coach": False})
        # 'processing' stamped on claim, 'ready' on completion.
        self.assertEqual([s[1] for s in db.states], ["processing", "ready"])

    def test_lost_claim_race_is_a_noop(self):
        db, _ = self._run(_FakeDb(job=_job(), claim_result=None))
        self.assertEqual(db.finishes, [])
        self.assertEqual(db.states, [])

    def test_failed_run_releases_and_requeues_with_backoff(self):
        def _boom(job):
            raise RuntimeError("whisper down")
        db, q = self._run(_FakeDb(job=_job()), runner=_boom)
        self.assertEqual(db.releases[-1][0], _JOB)
        self.assertIn("whisper down", db.releases[-1][1])
        path, args, delay = q.enqueues[-1]
        self.assertEqual(path, pj.TASK_PATH)
        self.assertEqual(args, (_JOB,))
        self.assertEqual(delay, 60)  # attempt 1 → 60s backoff
        # NOT terminal: no failed finish, session not failed.
        self.assertTrue(all(f[1] != "failed" for f in db.finishes))
        self.assertNotIn("failed", [s[1] for s in db.states])

    def test_failed_last_attempt_goes_terminal(self):
        def _boom(job):
            raise RuntimeError("still down")
        db, q = self._run(
            _FakeDb(job=_job(attempts=2, max_attempts=3)), runner=_boom)
        self.assertEqual(db.claims, [(_JOB, 2)])
        self.assertEqual(db.finishes[-1][1], "failed")
        self.assertEqual(db.states[-1][1], "failed")
        self.assertEqual(db.releases, [])
        self.assertEqual(q.enqueues, [])

    def test_unknown_kind_goes_terminal_not_poison_loop(self):
        db, _ = self._run(_FakeDb(job=_job(kind="mystery")))
        self.assertEqual(db.finishes[-1][1], "failed")
        self.assertIn("unknown job kind", db.finishes[-1][2])


@unittest.skipIf(pj is None, f"import failed: {_IMPORT_ERR}")
class EnqueueSessionRecordingJobTests(unittest.TestCase):

    def _kwargs(self):
        return dict(
            session_id=_SID, user_id="u1", recording_id="rec-1",
            bucket="b", storage_key="k", filename="lab.webm",
            session_context={"topic": "t"}, parent_audio_url="https://a",
            recording_kind="spoken", paired_session_id=None,
            arc_id=None, take_index=1, arc_take_count=1,
            spark_enabled=False,
        )

    def test_queue_off_returns_none(self):
        fake_q = _FakeQueue()
        fake_q.queue_configured = lambda: False
        with patch.object(pj, "job_queue", fake_q):
            self.assertIsNone(
                pj.enqueue_session_recording_job(**self._kwargs()))

    def test_enqueue_failure_fails_the_row_so_route_falls_back(self):
        fake_db = _FakeDb()
        created = {"id": _JOB, "session_id": _SID}
        fake_db.create_processing_job = lambda **kw: created
        fake_q = _FakeQueue(ok=False)
        with patch.object(pj, "db", fake_db), \
                patch.object(pj, "job_queue", fake_q):
            self.assertIsNone(
                pj.enqueue_session_recording_job(**self._kwargs()))
        # The row must not linger 'pending' with nothing delivering it.
        self.assertEqual(fake_db.finishes[-1][0], _JOB)
        self.assertEqual(fake_db.finishes[-1][1], "failed")

    def test_dedup_conflict_collapses_onto_active_twin(self):
        fake_db = _FakeDb()
        fake_db.create_processing_job = lambda **kw: None
        twin = {"id": _JOB, "status": "processing"}
        fake_db.get_active_processing_job_by_dedup = lambda k: twin
        fake_q = _FakeQueue()
        with patch.object(pj, "db", fake_db), \
                patch.object(pj, "job_queue", fake_q):
            row = pj.enqueue_session_recording_job(**self._kwargs())
        self.assertIs(row, twin)
        self.assertEqual(fake_q.enqueues, [])  # twin already delivered

    def test_success_returns_row_after_enqueue(self):
        fake_db = _FakeDb()
        created = {"id": _JOB, "session_id": _SID}
        fake_db.create_processing_job = lambda **kw: created
        fake_q = _FakeQueue(ok=True)
        with patch.object(pj, "db", fake_db), \
                patch.object(pj, "job_queue", fake_q):
            row = pj.enqueue_session_recording_job(**self._kwargs())
        self.assertIs(row, created)
        path, args, delay = fake_q.enqueues[-1]
        self.assertEqual((path, args, delay), (pj.TASK_PATH, (_JOB,), 0))


@unittest.skipIf(pj is None, f"import failed: {_IMPORT_ERR}")
class SweeperTests(unittest.TestCase):

    def test_orphaned_processing_row_released_and_requeued(self):
        fake_db = _FakeDb()
        fake_db.stale_rows = [_job(status="processing", attempts=1)]
        fake_q = _FakeQueue()
        with patch.object(pj, "db", fake_db), \
                patch.object(pj, "job_queue", fake_q):
            counts = pj.sweep_stale_jobs()
        self.assertEqual(counts["requeued"], 1)
        self.assertEqual(fake_db.releases[-1][0], _JOB)
        self.assertEqual(fake_q.enqueues[-1][0], pj.TASK_PATH)

    def test_lost_pending_row_requeued_without_release(self):
        fake_db = _FakeDb()
        fake_db.stale_rows = [_job(status="pending", attempts=0)]
        fake_q = _FakeQueue()
        with patch.object(pj, "db", fake_db), \
                patch.object(pj, "job_queue", fake_q):
            counts = pj.sweep_stale_jobs()
        self.assertEqual(counts["requeued"], 1)
        self.assertEqual(fake_db.releases, [])

    def test_exhausted_orphan_goes_terminal(self):
        fake_db = _FakeDb()
        fake_db.stale_rows = [_job(status="processing", attempts=3)]
        fake_q = _FakeQueue()
        with patch.object(pj, "db", fake_db), \
                patch.object(pj, "job_queue", fake_q):
            counts = pj.sweep_stale_jobs()
        self.assertEqual(counts["failed"], 1)
        self.assertEqual(fake_db.finishes[-1][1], "failed")
        self.assertEqual(fake_db.states[-1][1], "failed")

    def test_backoff_curve(self):
        self.assertEqual(pj._retry_backoff_seconds(1), 60)
        self.assertEqual(pj._retry_backoff_seconds(2), 120)
        self.assertEqual(pj._retry_backoff_seconds(3), 240)
        self.assertEqual(pj._retry_backoff_seconds(10), 600)  # capped


if __name__ == "__main__":
    unittest.main()
