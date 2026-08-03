"""GET /v2/jobs/<job_id>/status + POST /v2/internal/jobs/sweep — route
tests (async-queue work 2026-08-03).

The poll is the FE's async handoff: mechanical plumbing state ONLY
(status/stage/percent), state vocabulary shared with the readout GETs
(processing|ready|failed), 404 identical for unknown and foreign jobs (no
existence leak), and NEVER a score/verdict in the body (AC-9 probe below).

Flask-route classes skip locally when app deps are missing and run in CI
(house gotcha — keep assertions in sync with the route).

Run: python3 -m unittest test_jobs_status_route
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

# Stub heavy deps before the route imports pull services.db / auth.
for _m in ("supabase", "sentry_sdk"):
    if _m not in sys.modules:
        sys.modules[_m] = types.ModuleType(_m)
if not hasattr(sys.modules["supabase"], "create_client"):
    sys.modules["supabase"].create_client = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["supabase"].Client = object  # type: ignore[attr-defined]
if not hasattr(sys.modules["sentry_sdk"], "capture_exception"):
    sys.modules["sentry_sdk"].capture_exception = lambda *a, **k: None  # type: ignore[attr-defined]

try:
    from flask import Flask, request
    from routes import jobs as jobs_mod
    _IMPORT_ERR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    jobs_mod = None
    _IMPORT_ERR = e


_JOB = "55555555-5555-4555-8555-555555555555"
_SID = "66666666-6666-4666-8666-666666666666"


def _row(status="processing", user_id=None, **extra):
    base = {
        "id": _JOB, "status": status, "user_id": user_id,
        "session_id": _SID, "stage": "analysis", "percent": 40,
        "message": "Transcribing…", "error": None, "result": None,
        "created_at": "2026-08-03T10:00:00+00:00", "finished_at": None,
    }
    base.update(extra)
    return base


@unittest.skipIf(_IMPORT_ERR is not None, f"needs app deps: {_IMPORT_ERR}")
class JobStatusRouteTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)

    def _call(self, job_id=_JOB, row="unset", user_id=None):
        if row == "unset":
            row = _row()
        with patch.object(jobs_mod.db, "get_processing_job",
                          lambda jid: row, create=True):
            with self.app.test_request_context():
                request.user_id = user_id
                resp = jobs_mod.v2_job_status.__wrapped__(job_id)
        if isinstance(resp, tuple):
            body, status = resp
            return body.get_json(), status, body
        return resp.get_json(), resp.status_code, resp

    def test_bad_uuid_is_404(self):
        _, status, _ = self._call(job_id="not-a-uuid")
        self.assertEqual(status, 404)

    def test_unknown_job_is_404(self):
        _, status, _ = self._call(row=None)
        self.assertEqual(status, 404)

    def test_guest_job_readable_without_auth(self):
        body, status, resp = self._call(user_id=None)
        self.assertEqual(status, 200)
        self.assertEqual(body["job_id"], _JOB)
        self.assertEqual(body["status"], "processing")
        self.assertEqual(body["state"], "processing")
        self.assertEqual(body["percent"], 40)
        self.assertEqual(body["session_id"], _SID)
        # Poll freshness: proxies must never cache 'processing'.
        self.assertEqual(resp.headers.get("Cache-Control"), "no-store")

    def test_owned_job_hidden_from_guest_and_stranger(self):
        _, status, _ = self._call(row=_row(user_id="u1"), user_id=None)
        self.assertEqual(status, 404)
        _, status, _ = self._call(row=_row(user_id="u1"), user_id="u2")
        self.assertEqual(status, 404)

    def test_owned_job_readable_by_owner(self):
        body, status, _ = self._call(row=_row(user_id="u1"), user_id="u1")
        self.assertEqual(status, 200)
        self.assertEqual(body["job_id"], _JOB)

    def test_pending_maps_to_processing_state(self):
        body, _, _ = self._call(row=_row(status="pending"))
        self.assertEqual(body["state"], "processing")

    def test_completed_maps_to_ready_and_carries_result(self):
        body, _, _ = self._call(row=_row(
            status="completed",
            result={"snippet_count": 5, "sent_to_coach": True}))
        self.assertEqual(body["state"], "ready")
        self.assertEqual(body["result"]["snippet_count"], 5)
        self.assertNotIn("error", body)

    def test_failed_carries_error_not_result(self):
        body, _, _ = self._call(row=_row(status="failed", error="boom"))
        self.assertEqual(body["state"], "failed")
        self.assertEqual(body["error"], "boom")
        self.assertNotIn("result", body)

    def test_ac9_no_score_vocabulary_in_body(self):
        """Split-sink probe: the poll body must never grow score/verdict
        keys — the read stays qualitative and lives on the readout GETs."""
        body, _, _ = self._call()
        banned = {"score", "scores", "verdict", "rank", "power_score",
                  "overall_score", "charisma", "stress"}
        self.assertFalse(banned & set(body.keys()),
                         f"AC-9: banned keys in poll body: {body.keys()}")


@unittest.skipIf(_IMPORT_ERR is not None, f"needs app deps: {_IMPORT_ERR}")
class InternalSweepRouteTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)

    def _call(self, headers=None, secret_env=None):
        import os
        env = {}
        if secret_env is not None:
            env["PIPELINE_JOBS_SWEEP_SECRET"] = secret_env
        with patch.dict(os.environ, env, clear=False):
            if secret_env is None:
                os.environ.pop("PIPELINE_JOBS_SWEEP_SECRET", None)
            with patch("services.pipeline_jobs.sweep_stale_jobs",
                       lambda: {"requeued": 2, "failed": 1}, create=True):
                with self.app.test_request_context(headers=headers or {}):
                    resp = jobs_mod.v2_internal_jobs_sweep()
        body, status = resp
        return body.get_json(), status

    def test_unset_secret_disables_endpoint(self):
        body, status = self._call(secret_env=None)
        self.assertEqual(status, 503)

    def test_wrong_secret_403(self):
        _, status = self._call(
            headers={"X-Internal-Secret": "wrong"}, secret_env="right")
        self.assertEqual(status, 403)

    def test_right_secret_sweeps(self):
        body, status = self._call(
            headers={"X-Internal-Secret": "right"}, secret_env="right")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["requeued"], 2)
        self.assertEqual(body["failed"], 1)


if __name__ == "__main__":
    unittest.main()
