"""Country of residence is asked once and prefilled after.

FOUNDER 2026-10-05, decisions log N48.4 Q21 A: "country is asked once and
prefilled; location reassessment is dropped unless counsel wants it."

The fact was already stored: every Phase-1 receipt keeps the country it was
accepted under (``processing_authorization_receipts.country_of_residence``,
written lower-cased by the acceptance RPC). So nothing new is stored and no
migration is needed; the status read hands the newest one back when, and
only when, the person is being asked to re-accept. The acceptance screen
shows it already chosen; the person may still change it, and the acceptance
RPC still checks it against the policy in force (COUNTRY_NOT_ALLOWED).

Pinned here:

  * a re-acceptance carries the newest receipt's country, lower-cased, read
    for this principal only and newest first;
  * every other status (first-time, authorized, blocked, inactive) reads
    nothing extra and carries no country: the ordinary path does no work;
  * a failed or empty read leaves the status exactly as it was -- a prefill
    can never turn a readable status into PROCESSING_POLICY_INACTIVE.

Run: python3 -m unittest tests.test_country_asked_once
"""
from __future__ import annotations

import unittest

from services import processing_authorization as pa

PRINCIPAL = "11111111-1111-1111-1111-111111111111"


class _Result:
    def __init__(self, data):
        self.data = data


class _Rpc:
    def __init__(self, client, name, params):
        self.client, self.name, self.params = client, name, params

    def execute(self):
        self.client.calls.append(("rpc", self.name, self.params))
        return _Result(self.client.status_row)


class _Query:
    def __init__(self, client, relation):
        self.client = client
        self.read = {"relation": relation, "filters": [], "order": []}

    def select(self, columns):
        self.read["columns"] = columns
        return self

    def eq(self, column, value):
        self.read["filters"].append((column, value))
        return self

    def order(self, column, desc=False):
        self.read["order"].append((column, desc))
        return self

    def limit(self, count):
        self.read["limit"] = count
        return self

    def execute(self):
        self.client.calls.append(("table", self.read))
        if isinstance(self.client.receipts, Exception):
            raise self.client.receipts
        return _Result(self.client.receipts)


class _Client:
    def __init__(self, status_row, receipts):
        self.status_row = status_row
        self.receipts = receipts
        self.calls: list = []

    def rpc(self, name, params):
        return _Rpc(self, name, params)

    def table(self, relation):
        return _Query(self, relation)


def _service(status_row, receipts=None):
    database = type("Db", (), {"client": _Client(status_row, receipts or [])})()
    return pa.ProcessingAuthorizationService(database, mode="enforce")


def _status(**over):
    row = {
        "authorized": False,
        "code": "PROCESSING_AUTHORIZATION_REQUIRED",
        "policy_available": True,
        "policy_version": "phase1-new",
        "allowed_countries": ["pl", "de"],
        "reacceptance_required": False,
        "accepted_policy_version": None,
    }
    row.update(over)
    return row


def _table_reads(service):
    return [call[1] for call in service.client.calls if call[0] == "table"]


class AReAcceptanceIsPrefilledTests(unittest.TestCase):

    def test_the_newest_receipts_country_comes_back_lower_cased(self):
        service = _service(
            _status(reacceptance_required=True,
                    accepted_policy_version="phase1-old"),
            [{"country_of_residence": " DE "}],
        )
        status = service.status(PRINCIPAL)
        self.assertEqual(status["country_of_residence"], "de")
        # Everything the RPC said is untouched: the prefill adds, never moves.
        self.assertFalse(status["authorized"])
        self.assertEqual(status["code"], "PROCESSING_AUTHORIZATION_REQUIRED")
        self.assertTrue(status["reacceptance_required"])

    def test_it_reads_this_principals_receipts_newest_first(self):
        service = _service(_status(reacceptance_required=True),
                           [{"country_of_residence": "pl"}])
        service.status(PRINCIPAL)
        reads = _table_reads(service)
        self.assertEqual(len(reads), 1)
        read = reads[0]
        # The receipts are the stored fact; nothing else is consulted.
        self.assertEqual(read["relation"], "processing_authorization_receipts")
        self.assertEqual(read["filters"], [("acquisition_principal_id", PRINCIPAL)])
        self.assertEqual(read["order"][0], ("accepted_at", True))
        self.assertEqual(read["limit"], 1)


class EveryOtherStatusReadsNothingExtraTests(unittest.TestCase):

    def test_first_time_authorized_and_blocked_carry_no_country(self):
        for row in (
            _status(),
            _status(authorized=True, code="PROCESSING_AUTHORIZED"),
            # A blocked person is not being asked to re-accept anything.
            _status(code="PROCESSING_SERVICE_BLOCKED"),
            _status(reacceptance_required=None),
            _status(reacceptance_required="true"),
        ):
            service = _service(row, [{"country_of_residence": "pl"}])
            status = service.status(PRINCIPAL)
            self.assertNotIn("country_of_residence", status, row)
            self.assertEqual(_table_reads(service), [], row)


class APrefillNeverBreaksTheStatusTests(unittest.TestCase):

    def test_a_failed_read_leaves_the_status_as_it_was(self):
        service = _service(_status(reacceptance_required=True),
                           RuntimeError("receipts unreadable"))
        with self.assertLogs("services.processing_authorization", "WARNING"):
            status = service.status(PRINCIPAL)
        self.assertNotIn("country_of_residence", status)
        self.assertEqual(status["code"], "PROCESSING_AUTHORIZATION_REQUIRED")
        self.assertTrue(status["policy_available"])

    def test_no_receipt_or_an_empty_country_prefills_nothing(self):
        for receipts in ([], [{"country_of_residence": None}],
                         [{"country_of_residence": "  "}], [{}]):
            service = _service(_status(reacceptance_required=True), receipts)
            self.assertNotIn("country_of_residence", service.status(PRINCIPAL),
                             receipts)

    def test_the_reader_alone_answers_none_rather_than_raising(self):
        service = _service(_status(), RuntimeError("down"))
        with self.assertLogs("services.processing_authorization", "WARNING"):
            self.assertIsNone(service.last_country_of_residence(PRINCIPAL))


if __name__ == "__main__":
    unittest.main()
