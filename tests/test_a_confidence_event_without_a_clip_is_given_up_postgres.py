"""
STORY    As the founder, I want a confidence event whose Take has no clip a
         rater could judge to be given up for good, so that the outbox stops
         claiming and failing it every 30 seconds (two events, 30,903
         attempts since 2026-10-08) and keeps the record of why.
OUTCOME
  O1  An event the worker gives up is never claimed again, keeps its error
      code, and cannot be locked by anything afterwards.
  O2  Only the worker holding the lease can give an event up, and only for
      a reason on the allow-list.
  O3  The migration gives up the events already stuck on
      NoEligibleConfidenceClip and leaves every other event as it was.
PROVES   O1 -> test_a_given_up_event_is_never_claimed_again
         O2 -> test_only_the_lease_holder_gives_up_and_only_for_no_clip
         O3 -> test_the_migration_gives_up_only_the_stuck_events
WHY      0486, founder 2026-10-20; runs in one rolled-back transaction on a
         database whose name starts with ``willab_confident_moment_``
         (rehearsal tier only).
"""
from __future__ import annotations

import json
import os
import pathlib
import uuid
from types import SimpleNamespace

import psycopg2
import psycopg2.errors
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

MIGRATION = pathlib.Path(__file__).resolve().parents[1] / (
    "migrations/a_confidence_event_without_a_clip_is_given_up.sql")
STUCK = "NoEligibleConfidenceClip:confidence_frame_failed"


class _Rpc:
    """`client.rpc(name, params).execute()` over the test's transaction."""

    def __init__(self, cur, name, params):
        self.cur, self.name, self.params = cur, name, params

    def execute(self):
        keys = list(self.params)
        placeholders = ", ".join(f"{k} := %s" for k in keys)
        self.cur.execute(f"SELECT * FROM public.{self.name}({placeholders})",
                         [self.params[k] for k in keys])
        return SimpleNamespace(data=[dict(r) for r in self.cur.fetchall()])


class _Client:
    def __init__(self, cur):
        self.cur = cur

    def rpc(self, name, params):
        return _Rpc(self.cur, name, params)


@pytest.fixture()
def cur():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    if not parsed.get("host", "").startswith(("/tmp/willab-", "/private/tmp/willab-")):
        raise RuntimeError("Refusing a database outside the rehearsal socket")
    connection = psycopg2.connect(DSN)
    connection.autocommit = False
    try:
        yield connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    finally:
        connection.rollback()
        connection.close()


def _event(cur, *, last_error_code=None) -> str:
    """One due confidence outbox event, first in claim order."""
    cur.execute(
        "INSERT INTO public.ml_outbox_events (idempotency_key, event_type, "
        "learning_surface_id, aggregate_type, aggregate_id, payload, occurred_at, "
        "available_at, last_error_code, last_error_at) VALUES (%s, "
        "'confidence_take_ready', 'confidence_classification', 'take', %s, %s, "
        "now(), '1970-01-01', %s, CASE WHEN %s IS NULL THEN NULL ELSE now() END) "
        "RETURNING id",
        (f"given-up-{uuid.uuid4()}", str(uuid.uuid4()), json.dumps({}),
         last_error_code, last_error_code))
    return str(cur.fetchone()["id"])


def _claimed(cur, worker: str) -> list[str]:
    cur.execute("SELECT id FROM public.claim_mlc2_confidence_outbox_v1(%s, 100, 60)",
                (worker,))
    return [str(r["id"]) for r in cur.fetchall()]


def _row(cur, event_id: str) -> dict:
    cur.execute("SELECT * FROM public.ml_outbox_events WHERE id = %s", (event_id,))
    return dict(cur.fetchone())


def _refused(cur, sql, params=()) -> bool:
    cur.execute("SAVEPOINT refused")
    try:
        cur.execute(sql, params)
    except psycopg2.Error:
        cur.execute("ROLLBACK TO SAVEPOINT refused")
        return True
    cur.execute("RELEASE SAVEPOINT refused")
    return False


def test_a_given_up_event_is_never_claimed_again(cur):
    from services.mlc2_confidence_producer import Mlc2ConfidenceProducerStore

    event_id = _event(cur)
    assert event_id in _claimed(cur, "worker-a")
    Mlc2ConfidenceProducerStore(_Client(cur)).abandon(
        outbox_event_id=event_id, worker_id="worker-a",
        error_code=STUCK, reason_code="no_eligible_clip")

    row = _row(cur, event_id)
    assert row["abandoned_at"] is not None
    assert row["abandon_reason_code"] == "no_eligible_clip"
    assert row["last_error_code"] == STUCK
    assert row["processed_at"] is None and row["locked_by"] is None
    assert event_id not in _claimed(cur, "worker-b")
    cur.execute("SELECT id FROM public.claim_mlc2_outbox_events_v1(%s, 100, 60)",
                ("worker-c",))
    assert event_id not in [str(r["id"]) for r in cur.fetchall()]
    assert _refused(cur, "UPDATE public.ml_outbox_events SET locked_by = 'x', "
                         "lease_expires_at = now() WHERE id = %s", (event_id,))


def test_only_the_lease_holder_gives_up_and_only_for_no_clip(cur):
    event_id = _event(cur)
    assert event_id in _claimed(cur, "worker-a")
    give_up = ("SELECT * FROM public.abandon_mlc2_confidence_outbox_event_v1("
               "%s, %s, %s, %s)")
    assert _refused(cur, give_up, (event_id, "worker-b", STUCK, "no_eligible_clip"))
    assert _refused(cur, give_up, (event_id, "worker-a", "APIError:x", "database_down"))
    assert _row(cur, event_id)["abandoned_at"] is None
    assert not _refused(cur, give_up, (event_id, "worker-a", STUCK, "no_eligible_clip"))


def test_the_migration_gives_up_only_the_stuck_events(cur):
    stuck = _event(cur, last_error_code=STUCK)
    other = _event(cur, last_error_code="APIError:confidence_frame_failed")
    fresh = _event(cur)
    cur.execute(MIGRATION.read_text())

    assert _row(cur, stuck)["abandon_reason_code"] == "no_eligible_clip"
    for event_id in (other, fresh):
        assert _row(cur, event_id)["abandoned_at"] is None
    assert set(_claimed(cur, "worker-a")) >= {other, fresh}
    assert stuck not in _claimed(cur, "worker-b")
