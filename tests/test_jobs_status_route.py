"""
STORY    As a speaker, I want the processing poll to show only progress, the
         same for an unknown job and someone else's job, and never a score,
         so that waiting is private and judgement-free.
OUTCOME
  O1  The poll body carries status/stage/percent and a state from the
      readout GETs' vocabulary: processing, ready or failed.
  O2  An unknown, malformed or someone else's job gets the identical 404.
  O3  Never-1 (no scores, numbers or verdicts to speakers): no score or
      verdict key or value anywhere in the body, even when the job row
      itself carries one.
  O4  The recovery sweep runs only with the internal secret.
PROVES   O1 -> test_poll_shows_progress_in_the_readout_vocabulary
         O2 -> test_unknown_and_foreign_jobs_look_identical
         O3 -> test_no_score_or_verdict_anywhere_in_the_body
         O4 -> test_sweep_needs_the_internal_secret
WHY      AC-9 split sink: results live on the readout GETs, never on the poll.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from flask import Flask, request

from routes import jobs as jobs_mod

_JOB = "55555555-5555-4555-8555-555555555555"
_OTHER = "77777777-7777-4777-8777-777777777777"
_SID = "66666666-6666-4666-8666-666666666666"
_BANNED = {"score", "scores", "verdict", "rank", "power_score",
           "overall_score", "charisma", "stress", "confidence_score"}


def _row(status="processing", user_id=None, **extra):
    base = {
        "id": _JOB, "status": status, "user_id": user_id,
        "session_id": _SID, "stage": "analysis", "percent": 40,
        "message": "Transcribing…", "error": None, "result": None,
        "created_at": "2026-08-03T10:00:00+00:00", "finished_at": None,
    }
    base.update(extra)
    return base


def _keys(value):
    if isinstance(value, dict):
        for key, inner in value.items():
            yield key
            yield from _keys(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _keys(inner)


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
        body, status = resp if isinstance(resp, tuple) else (resp, 200)
        return body.get_json(), status

    def test_poll_shows_progress_in_the_readout_vocabulary(self):
        for stored, state in (("pending", "processing"),
                              ("processing", "processing"),
                              ("completed", "ready"),
                              ("failed", "failed")):
            with self.subTest(stored=stored):
                body, status = self._call(row=_row(stored, user_id="u1"),
                                          user_id="u1")
                self.assertEqual(status, 200)
                self.assertEqual(body["status"], stored)
                self.assertEqual(body["state"], state)
                self.assertEqual(body["stage"], "analysis")
                self.assertEqual(body["percent"], 40)

    def test_unknown_and_foreign_jobs_look_identical(self):
        unknown = self._call(row=None, user_id="u1")
        foreign = self._call(row=_row(user_id="someone-else"), user_id="u1")
        malformed = self._call(job_id="not-a-job", user_id="u1")
        self.assertEqual(unknown[1], 404)
        self.assertEqual(unknown, foreign)
        self.assertEqual(unknown, malformed)
        # The owner does see it.
        self.assertEqual(self._call(row=_row(user_id="u1"),
                                    user_id="u1")[1], 200)

    def test_no_score_or_verdict_anywhere_in_the_body(self):
        # A finished job with the real runner's summary, on a row that also
        # carries score columns the poll must never pass through.
        row = _row("completed", user_id="u1", percent=100,
                   result={"snippet_count": 4, "sent_to_coach": False,
                           "ideal_text_confirmed": True},
                   score=0.87, verdict="strong", power_score=71)
        body, status = self._call(row=row, user_id="u1")
        self.assertEqual(status, 200)
        self.assertEqual(body["state"], "ready")
        self.assertEqual(body["result"]["snippet_count"], 4)
        self.assertFalse(_BANNED & set(_keys(body)), body)
        text = json.dumps(body)
        for leaked in ("0.87", "strong", "71"):
            self.assertNotIn(leaked, text)

    def test_sweep_needs_the_internal_secret(self):
        def sweep(secret_env, sent):
            env = {"PIPELINE_JOBS_SWEEP_SECRET": secret_env}
            with patch.dict("os.environ", env), \
                    patch("services.pipeline_jobs.sweep_stale_jobs",
                          return_value={"recovered": 1}) as swept, \
                    self.app.test_request_context(
                        method="POST", headers={"X-Internal-Secret": sent}):
                body, status = jobs_mod.v2_internal_jobs_sweep()
                return body.get_json(), status, swept

        self.assertEqual(sweep("", "anything")[1], 503)
        _, status, swept = sweep("s3cret", "wrong")
        self.assertEqual(status, 403)
        swept.assert_not_called()
        body, status, swept = sweep("s3cret", "s3cret")
        self.assertEqual((status, body), (200, {"ok": True, "recovered": 1}))
        swept.assert_called_once()


if __name__ == "__main__":
    unittest.main()
