"""The strict cold-open read never answers 500.

2026-09-15 live-loop incident: every ``GET /v2/explore/arc/<id>/ideal-text/core``
returned 500 in production because ``db.get_ideal_text_document_core_v2``
re-raised whatever ``read_ideal_text_document_core_v2`` raised, and that RPC
raises (STRICT selects, explicit RAISE) for any arc without the Point-7 rows.
The v1 read degraded every failure to ``None`` (the 404 "pending" the FE
renders); the v2 read must do the same. These tests pin that contract without
a database: the client is a fake whose RPC raises or returns what we choose.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from postgrest.exceptions import APIError

from services.db import db


class _Execute:
    def __init__(self, result=None, error=None):
        self._result, self._error = result, error

    def execute(self):
        if self._error is not None:
            raise self._error
        return self._result


class _Result:
    def __init__(self, data):
        self.data = data


class _Client:
    def __init__(self, result=None, error=None):
        self.calls = []
        self._result, self._error = result, error

    def rpc(self, name, params=None):
        self.calls.append((name, params))
        return _Execute(self._result, self._error)


def _read(client):
    with patch.object(db, "client", client):
        return db.get_ideal_text_document_core_v2("arc-1", "user-1")


class CoreReadDegradesTests(unittest.TestCase):
    def test_a_projection_raise_from_the_rpc_is_pending_not_500(self):
        client = _Client(error=APIError({
            "code": "P0001", "message": "CONFIDENT_MOMENT_PROJECTION_INVALID",
            "details": None, "hint": None}))
        self.assertIsNone(_read(client))
        self.assertEqual(client.calls[0][0], "read_ideal_text_document_core_v2")

    def test_a_missing_head_from_a_strict_select_is_pending(self):
        client = _Client(error=APIError({
            "code": "P0002", "message": "query returned no rows",
            "details": None, "hint": None}))
        self.assertIsNone(_read(client))

    def test_a_missing_function_is_pending_as_before(self):
        client = _Client(error=APIError({
            "code": "PGRST202", "details": None, "hint": None,
            "message": "Could not find the function public.read_ideal_text_document_core_v2"}))
        self.assertIsNone(_read(client))

    def test_a_validator_rejection_is_pending_and_serves_nothing(self):
        # A shape the strict validator refuses (extra key at the top level).
        client = _Client(result=_Result([{"unexpected": 1}]))
        self.assertIsNone(_read(client))

    def test_an_empty_result_is_pending(self):
        self.assertIsNone(_read(_Client(result=_Result([]))))

    def test_a_valid_envelope_is_served(self):
        envelope = {"ideal_text_core_read_contract_version": "ideal-text-document-core-v2"}
        client = _Client(result=_Result([envelope]))
        with patch("services.confident_moment_bundle.validate_ideal_text_core_v2",
                   side_effect=lambda value: dict(value, validated=True)):
            out = _read(client)
        self.assertEqual(out, dict(envelope, validated=True))

    def test_the_degradation_is_logged_with_the_cause(self):
        client = _Client(error=RuntimeError("connection reset"))
        with self.assertLogs("services.db", level="WARNING") as captured:
            self.assertIsNone(_read(client))
        self.assertTrue(any("degraded to pending" in line and "connection reset" in line
                            for line in captured.output))


if __name__ == "__main__":
    unittest.main()
