"""The Data page's "Accept the update" card appears only for someone whose
earlier agreement a newer policy replaced (founder 2026-09-28, decision 21)."""
from __future__ import annotations

from types import SimpleNamespace

from services.processing_authorization import ProcessingAuthorizationService


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def __getattr__(self, _name):
        return lambda *a, **k: self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class _Client:
    def __init__(self, status, receipts, fail=False):
        self.status, self.receipts, self.fail = status, receipts, fail

    def rpc(self, _name, _params):
        return _Query([self.status])

    def table(self, _name):
        if self.fail:
            raise RuntimeError("down")
        return _Query(self.receipts)


def _status(code, receipts, fail=False):
    client = _Client({"authorized": code is None, "code": code}, receipts, fail)
    service = ProcessingAuthorizationService(SimpleNamespace(client=client),
                                             mode="off")
    return service.status("p-1")


def test_an_earlier_agreement_replaced_by_a_newer_policy_is_flagged():
    row = _status("PROCESSING_AUTHORIZATION_REQUIRED", [{"id": "r-old"}])
    assert row["accepted_earlier_version"] is True


def test_someone_who_never_agreed_is_not_offered_an_update():
    row = _status("PROCESSING_AUTHORIZATION_REQUIRED", [])
    assert row["accepted_earlier_version"] is False


def test_a_current_agreement_needs_no_update():
    row = _status(None, [{"id": "r-now"}])
    assert row["accepted_earlier_version"] is False


def test_a_failed_read_shows_no_card():
    row = _status("PROCESSING_AUTHORIZATION_REQUIRED", [], fail=True)
    assert row["accepted_earlier_version"] is False
