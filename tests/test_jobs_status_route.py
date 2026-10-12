"""GET /v2/jobs/<job_id>/status + POST /v2/internal/jobs/sweep — route
tests (async-queue work 2026-08-03).

The poll is the FE's async handoff: mechanical plumbing state ONLY
(status/stage/percent), state vocabulary shared with the readout GETs
(processing|ready|failed), 404 identical for unknown and foreign jobs (no
existence leak), and NEVER a score/verdict in the body (AC-9 probe below).

Flask-route classes skip locally when app deps are missing and run in CI
(house gotcha — keep assertions in sync with the route).

Run: python3 -m unittest tests.test_jobs_status_route
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


    def test_ac9_no_score_vocabulary_in_body(self):
        """Split-sink probe: the poll body must never grow score/verdict
        keys — the read stays qualitative and lives on the readout GETs."""
        body, _, _ = self._call()
        banned = {"score", "scores", "verdict", "rank", "power_score",
                  "overall_score", "charisma", "stress"}
        self.assertFalse(banned & set(body.keys()),
                         f"AC-9: banned keys in poll body: {body.keys()}")


if __name__ == "__main__":
    unittest.main()
