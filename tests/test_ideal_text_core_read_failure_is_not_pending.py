"""A FAILED Ideal Text read is never answered as "no document yet".

Founder 2026-09-26, from real use: at 16:38:20 UTC the database connection
dropped ("Server disconnected"), the core read swallowed it into ``None``, the
route answered ``404 IDEAL_TEXT_DOCUMENT_PENDING``, and the notebook showed an
existing Ideal Text as a project waiting for its document. Two changes, pinned
here without a database:

- the core reads retry a dropped connection on a fresh client, like every
  other hot read (``_execute_with_retry``);
- a read that still fails raises ``IdealTextCoreReadError`` and the core GET
  answers ``503 IDEAL_TEXT_READ_FAILED`` — try again — never the 404.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import auth
from flask import Flask

import routes.v2.explore_ideal_text  # noqa: F401  (attaches the routes)
from routes.v2.blueprint import v2_bp
from services.db import IdealTextCoreReadError, db

DISCONNECT = RuntimeError(
    "RemoteProtocolError: Server disconnected without sending a response.")


class _Execute:
    def __init__(self, outcome):
        self._outcome = outcome

    def execute(self):
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class _Result:
    def __init__(self, data):
        self.data = data


class _Client:
    """Each RPC name answers from its own queue; the last answer repeats."""

    def __init__(self, **queues):
        self.queues = {name: list(q) for name, q in queues.items()}
        self.calls: list[str] = []

    def rpc(self, name, params=None):
        self.calls.append(name)
        queue = self.queues.get(name, [_Result([])])
        outcome = queue.pop(0) if len(queue) > 1 else queue[0]
        return _Execute(outcome)


def _read(client):
    with patch.object(db, "client", client), \
         patch.object(db, "_build_supabase_client", return_value=client), \
         patch("services.db.time.sleep"):
        return db.get_ideal_text_document_core_v2("arc-1", "user-1")


V1_ROW = {"id": "snap-1", "payload_sha256": "f" * 64,
          "payload": {"status": "verified", "text": "The document."}}


class CoreReadRetriesAndFailsLoudly(unittest.TestCase):
    def test_a_dropped_connection_is_retried_and_the_document_served(self):
        client = _Client(
            read_ideal_text_document_core_v2=[DISCONNECT, _Result([])],
            read_ideal_text_document_core_v1=[_Result([V1_ROW])],
        )
        out = _read(client)
        self.assertEqual(out["snapshot"], V1_ROW)
        self.assertEqual(client.calls[:2], [
            "read_ideal_text_document_core_v2",
            "read_ideal_text_document_core_v2"])

    def test_a_read_that_keeps_failing_raises_instead_of_posing_as_pending(self):
        client = _Client(
            read_ideal_text_document_core_v2=[DISCONNECT],
            read_ideal_text_document_core_v1=[DISCONNECT],
        )
        with self.assertRaises(IdealTextCoreReadError):
            _read(client)

    def test_a_non_transient_read_error_stays_pending_not_503(self):
        # Production 2026-09-26: some arcs' v1 read raises an ordinary RPC
        # error; raising on those made a 503 on every load.
        client = _Client(
            read_ideal_text_document_core_v2=[RuntimeError("P0001 projection invalid")],
            read_ideal_text_document_core_v1=[RuntimeError("P0002 query returned no rows")],
        )
        self.assertIsNone(_read(client))

    def test_an_arc_with_no_document_is_still_pending(self):
        client = _Client(
            read_ideal_text_document_core_v2=[_Result([])],
            read_ideal_text_document_core_v1=[_Result([])],
        )
        self.assertIsNone(_read(client))

    def test_other_callers_of_the_v1_read_keep_none(self):
        # Recording roots and the snapshot helpers must not start raising.
        client = _Client(read_ideal_text_document_core_v1=[DISCONNECT])
        with patch.object(db, "client", client), \
             patch.object(db, "_build_supabase_client", return_value=client), \
             patch("services.db.time.sleep"):
            self.assertIsNone(db.get_ideal_text_document_core("arc-1", "user-1"))


class CoreGetAnswers503OnAFailedRead(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(v2_bp, url_prefix="/v2")
        cls.app = app

    def setUp(self):
        self._orig = auth.verify_supabase_token
        auth.verify_supabase_token = lambda token: {"sub": "user-1"}

    def tearDown(self):
        auth.verify_supabase_token = self._orig

    def _get(self, **patch_kwargs):
        with patch("services.db.db.get_ideal_text_document_core_v2", **patch_kwargs):
            return self.app.test_client().get(
                "/v2/explore/arc/arc-1/ideal-text/core",
                headers={"Authorization": "Bearer t"},
            )

    def test_a_failed_read_is_503_retryable(self):
        response = self._get(side_effect=IdealTextCoreReadError("Server disconnected"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["code"], "IDEAL_TEXT_READ_FAILED")
        self.assertEqual(response.headers.get("Retry-After"), "2")

    def test_no_document_is_still_404_pending(self):
        response = self._get(return_value=None)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["code"], "IDEAL_TEXT_DOCUMENT_PENDING")


if __name__ == "__main__":
    unittest.main()
