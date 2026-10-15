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

Run: python3 -m unittest tests.test_processing_jobs
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from services import pipeline_jobs

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
    import services.pipeline_jobs as pj
    from services.db import DatabaseService
    _IMPORT_ERR = None
except Exception as e:  # pragma: no cover - env/bootstrap guard
    DatabaseService = None  # type: ignore[assignment]
    pj = None  # type: ignore[assignment]
    _IMPORT_ERR = e


_JOB = "33333333-3333-4333-8333-333333333333"
_SID = "44444444-4444-4444-8444-444444444444"


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
        # audit Q-A1 step 2 / Q-A2: the real db.py routes this through the
        # recordings repository now; tests set the lambda on the same path.
        self.recordings = types.SimpleNamespace(
            get_recording_attempt=lambda _sid: None,
        )

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

    def list_stale_processing_jobs(self, stale_minutes=15, max_rows=100,
                                   max_runtime_minutes=None):
        return self.stale_rows

    def list_orphaned_processing_sessions(self, stale_minutes=30,
                                          max_rows=100):
        # Orphan reaping has its own suite
        # (test_orphan_sweep_and_concurrency); nothing here exercises it.
        return []

    @property
    def takes(self):
        # audit Q-A2: production now calls db.takes.<method>(); this fake
        # implements those methods directly on itself.
        return self


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


    def test_pre_hotfix_noncanary_job_reaches_the_runner(self):
        job = _job()
        job["payload"]["lifecycle_contract_version"] = (
            pj.TAKE_LIFECYCLE_CONTRACT
        )
        fake_db = _FakeDb(job=job)
        fake_db.recordings.get_recording_attempt = lambda _sid: None

        db, _ = self._run(fake_db)

        self.assertEqual(db.finishes[-1][1], "completed")
        self.assertEqual([state[1] for state in db.states], [
            "processing", "ready",
        ])


    def test_failed_run_releases_and_requeues_at_once(self):
        def _boom(job):
            raise RuntimeError("whisper down")
        db, q = self._run(_FakeDb(job=_job()), runner=_boom)
        self.assertEqual(db.releases[-1][0], _JOB)
        self.assertIn("whisper down", db.releases[-1][1])
        path, args, delay = q.enqueues[-1]
        self.assertEqual(path, pj.TASK_PATH)
        self.assertEqual(args, (_JOB,))
        # Attempt 1 → requeued at once: a delayed job waits on rq's
        # scheduler, which ran one 6 min 53 s late in production.
        self.assertEqual(delay, 0)
        # NOT terminal: no failed finish, session not failed.
        self.assertTrue(all(f[1] != "failed" for f in db.finishes))
        self.assertNotIn("failed", [s[1] for s in db.states])


    def test_ideal_text_timeout_is_special_terminal_and_never_requeues(self):
        from services.ideal_text_confirmation import IdealTextUnconfirmedError

        def _unconfirmed(job):
            raise IdealTextUnconfirmedError("arc-1")

        fake_db = _FakeDb(job={
            **_job(),
            "payload": {
                **_job()["payload"],
                "user_id": "u1",
                "arc_id": "arc-1",
                "take_index": 1,
            },
        })
        with patch.object(pj, "mark_ideal_text_unconfirmed") as mark:
            db, q = self._run(fake_db, runner=_unconfirmed)
        self.assertEqual(db.finishes[-1][1], "failed")
        self.assertEqual(db.releases, [])
        self.assertEqual(q.enqueues, [])
        mark.assert_called_once()
        self.assertEqual(mark.call_args.kwargs["session_id"], _SID)
        self.assertEqual(mark.call_args.kwargs["take_index"], 1)

    def test_ideal_text_retry_unexpected_failure_stays_in_special_boundary(self):
        def _boom(job):
            raise RuntimeError("document provider unavailable")

        job = {
            **_job(
                kind=pj.KIND_IDEAL_TEXT_RETRY,
                max_attempts=1,
            ),
            "payload": {
                "session_id": _SID,
                "user_id": "u1",
                "arc_id": "arc-1",
                "take_index": 1,
            },
        }
        fake_db = _FakeDb(job=job)
        fake_q = _FakeQueue()
        with patch.object(pj, "db", fake_db), patch.object(
            pj, "job_queue", fake_q,
        ), patch.dict(
            pj._KIND_RUNNERS,
            {pj.KIND_IDEAL_TEXT_RETRY: _boom},
        ), patch.object(pj, "mark_ideal_text_unconfirmed") as mark:
            pj.run_processing_job(_JOB)
        self.assertEqual(fake_db.finishes[-1][1], "failed")
        self.assertEqual(fake_db.releases, [])
        self.assertEqual(fake_q.enqueues, [])
        mark.assert_called_once()
        self.assertEqual(mark.call_args.kwargs["session_id"], _SID)
        self.assertEqual(mark.call_args.kwargs["take_index"], 1)


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


    def test_registered_job_declares_the_canonical_attempt_contract(self):
        fake_db = _FakeDb()
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return {"id": _JOB, "session_id": _SID}

        fake_db.create_processing_job = create
        with patch.object(pj, "db", fake_db), patch.object(
            pj, "job_queue", _FakeQueue(),
        ):
            pj.enqueue_session_recording_job(
                **self._kwargs(), canonical_attempt_registered=True,
            )

        self.assertEqual(
            captured["payload"]["lifecycle_contract_version"],
            pj.TAKE_LIFECYCLE_CONTRACT,
        )
        self.assertIs(
            captured["payload"]["canonical_attempt_registered"], True,
        )


@unittest.skipIf(pj is None, f"import failed: {_IMPORT_ERR}")
class SweeperTests(unittest.TestCase):


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


# ── merged from tests/test_pipeline_job_retry.py (audit Q-T9) ──

class ManualProcessingRetryTests(unittest.TestCase):
    def test_requeues_the_existing_failed_job_and_preserves_its_payload(self):
        failed = {
            "id": "job-1", "session_id": "session-1", "user_id": "user-1",
            "kind": "session_recording", "status": "failed",
            "payload": {"storage_key": "kept/audio.webm"},
        }
        reopened = {**failed, "status": "pending", "attempts": 0}
        with patch.object(pipeline_jobs.job_queue, "queue_configured",
                          return_value=True), \
             patch.object(pipeline_jobs.db,
                          "get_latest_processing_job_by_session",
                          return_value=failed), \
             patch.object(pipeline_jobs.db,
                          "reset_processing_job_for_manual_retry",
                          return_value=True) as reset, \
             patch.object(pipeline_jobs.job_queue, "enqueue",
                          return_value=True) as enqueue, \
             patch.object(pipeline_jobs.db.takes, "set_session_analysis_state") \
                          as state, \
             patch.object(pipeline_jobs.db, "get_processing_job",
                          return_value=reopened):
            out = pipeline_jobs.retry_failed_session_job(
                "session-1", "user-1")
        self.assertEqual(out["payload"]["storage_key"], "kept/audio.webm")
        reset.assert_called_once_with("job-1")
        enqueue.assert_called_once_with(pipeline_jobs.TASK_PATH, "job-1")
        state.assert_called_once_with("session-1", "processing")


if __name__ == "__main__":
    unittest.main()
