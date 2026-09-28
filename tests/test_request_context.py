"""One request id from the BFF to the worker (audit A1, 2026-09-28).

The id arrives as X-Request-Id, is bound for the Flask request, rides a
queued job in job.meta, and is bound again when the worker runs that job.
Every log record carries it, whatever handler formats it.
"""
from __future__ import annotations

import logging

import pytest

from services import request_context as rc


@pytest.fixture(autouse=True)
def _fresh_context():
    rc._REQUEST_ID.set(rc.NO_REQUEST)
    yield
    rc._REQUEST_ID.set(rc.NO_REQUEST)


def test_outside_a_request_the_id_is_a_dash_and_jobs_carry_no_meta():
    assert rc.current_request_id() == "-"
    assert rc.job_meta() == {}


def test_a_well_formed_incoming_id_is_kept():
    assert rc.bind_request_id("bff-4f2a9c1e7b3d") == "bff-4f2a9c1e7b3d"
    assert rc.current_request_id() == "bff-4f2a9c1e7b3d"
    assert rc.job_meta() == {"request_id": "bff-4f2a9c1e7b3d"}


@pytest.mark.parametrize("raw", [None, "", "has space", "x" * 65, "<script>", 42])
def test_a_missing_or_malformed_id_is_replaced_not_logged(raw):
    rid = rc.bind_request_id(raw)
    assert rid != raw
    assert len(rid) == 12 and rid.isalnum()


def test_the_worker_binds_the_id_the_job_was_queued_with():
    assert rc.bind_from_job_meta({"request_id": "abc123def456"}) == "abc123def456"
    assert rc.current_request_id() == "abc123def456"
    # A job queued outside any request gets a fresh id of its own.
    assert rc.bind_from_job_meta({}) != "abc123def456"
    assert len(rc.bind_from_job_meta(None)) == 12


def test_every_log_record_carries_the_id():
    rc.install_log_record_factory()
    rc.install_log_record_factory()  # idempotent
    rc.bind_request_id("rid-1")
    record = logging.getLogger("anything").makeRecord(
        "anything", logging.INFO, __file__, 1, "hello", (), None)
    assert record.request_id == "rid-1"
    # The shared format names it, so the web and the worker print it alike.
    from services.logging_setup import FORMAT
    assert "%(request_id)s" in FORMAT
    assert logging.Formatter(FORMAT).format(record).endswith("[rid-1]: hello")


def test_flask_binds_the_header_echoes_it_and_clears_it_after():
    from flask import Flask

    app = Flask(__name__)
    rc.install_request_id(app)
    seen = {}

    @app.get("/ping")
    def ping():
        seen["inside"] = rc.current_request_id()
        return "ok"

    client = app.test_client()
    resp = client.get("/ping", headers={"X-Request-Id": "bff-0000aaaa1111"})
    assert seen["inside"] == "bff-0000aaaa1111"
    assert resp.headers["X-Request-Id"] == "bff-0000aaaa1111"
    assert rc.current_request_id() == "-"

    resp = client.get("/ping")
    minted = resp.headers["X-Request-Id"]
    assert len(minted) == 12 and seen["inside"] == minted


def test_enqueue_puts_the_id_in_job_meta(monkeypatch):
    from services import job_queue

    calls = []

    class _Queue:
        def enqueue(self, func_path, *args, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(job_queue, "get_queue", lambda name=None: _Queue())
    assert job_queue.enqueue("services.x.run", "job-1") is True
    assert "meta" not in calls[-1]  # outside a request: nothing to carry

    rc.bind_request_id("rid-queued-01")
    assert job_queue.enqueue("services.x.run", "job-2") is True
    assert calls[-1]["meta"] == {"request_id": "rid-queued-01"}


def test_the_worker_loop_uses_the_tracing_worker():
    import inspect

    import worker

    source = inspect.getsource(worker._run_worker_loop)
    assert "_traced_worker_class()" in source
    traced = worker._traced_worker_class()
    from rq import Worker
    assert issubclass(traced, Worker)
    assert "bind_from_job_meta" in inspect.getsource(traced.perform_job)
