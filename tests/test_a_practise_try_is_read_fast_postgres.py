"""
STORY    As a speaker practising, I want each try read once, quickly, against
         my own practice and Take, so that feedback on the try arrives fast,
         belongs to me, and its number never reaches me.
OUTCOME
  O1  One stored read per try; the database takes the owner, practice and
      Take from the try itself and computes W and S*W; a repeat is a no-op.
  O2  A read that fails (services.v4_practice_read.record) still keeps its
      row, with no values, and counts as "not reached yet".
  O3  The phone's times are stored once, only for the try's owner, and only
      for a wait within 0..600 000 ms; the timing route answers 204 with no
      body, so the speaker is told nothing about the read (Never rule 1:
      no numbers shown to speakers).
  O4  The read goes when the try goes (deletion: FK cascade).
PROVES   O1 -> test_the_read_is_stored_once_with_its_owner
         O2 -> test_a_failed_read_keeps_an_empty_row
         O3 -> test_phone_times_are_kept_once_for_the_owner_and_never_answered
         O4 -> test_the_read_goes_with_the_try
WHY      Migration 0450 (V4 B1.4, D-ML-9; founder O5, V7 A). The app's
         writers run over a thin RPC-to-SQL client on the rehearsal tier.
"""
from __future__ import annotations

import inspect
import pathlib
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from psycopg2 import sql

from tests import test_a_take_draws_its_random_moments_postgres as draw_suite
from tests import (
    test_the_shadow_writer_accepts_the_frame_the_code_builds_postgres as base,
)

DSN = base.DSN
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "a_practise_try_is_read_fast.sql"
T0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def cur():
    yield from base.cur.__wrapped__()


def _apply(cur):
    cur.execute(draw_suite._body(MIGRATION))


def _attempt(cur):
    practice, attempt, owner, take = (str(uuid.uuid4()) for _ in range(4))
    cur.execute("INSERT INTO public.confident_voice_practice "
                "(id, owner_user_id, take_session_id) VALUES (%s, %s, %s)",
                (practice, owner, take))
    cur.execute("INSERT INTO public.confident_voice_practice_attempt "
                "(id, practice_id, attempt_index) VALUES (%s, %s, 1)",
                (attempt, practice))
    return {"practice": practice, "attempt": attempt, "owner": owner, "take": take}


def _read(cur, attempt, outcome="read", s=0.8, filler=0.9, hedging=0.5,
          received=T0, ready=T0 + timedelta(seconds=2)):
    cur.execute("SELECT public.record_v4_practice_read_v1(%s::uuid, %s, %s, %s, %s, %s, %s) AS r",
                (attempt, outcome, s, filler, hedging, received, ready))
    return cur.fetchone()["r"]


def _row(cur, attempt):
    cur.execute("SELECT * FROM public.v4_practice_reads WHERE attempt_id = %s", (attempt,))
    return cur.fetchone()


def test_the_read_is_stored_once_with_its_owner(cur):
    _apply(cur)
    seed = _attempt(cur)
    assert _read(cur, seed["attempt"]) == {"outcome": "stored"}
    row = _row(cur, seed["attempt"])
    assert str(row["practice_id"]) == seed["practice"]
    assert str(row["take_session_id"]) == seed["take"]
    assert str(row["owner_user_id"]) == seed["owner"]
    assert row["w"] == Decimal("0.7")
    assert row["willfident"] == Decimal("0.8") * Decimal("0.7")
    assert row["read_version"] == "willfidence-v1-machine-fast"
    assert _read(cur, seed["attempt"], s=0.1) == {"outcome": "already"}
    assert _row(cur, seed["attempt"])["s"] == Decimal("0.8")


class _Rpc:
    """client.rpc(name, params).execute() as one SQL call by named args."""

    def __init__(self, cur):
        self.cur = cur

    def rpc(self, name, params):
        def execute():
            self.cur.execute(
                sql.SQL("SELECT public.{}({}) AS r").format(
                    sql.Identifier(name),
                    sql.SQL(", ").join(sql.SQL("{} => %s").format(sql.Identifier(k))
                                       for k in params)),
                list(params.values()))
            return SimpleNamespace(data=self.cur.fetchone()["r"])
        return SimpleNamespace(execute=execute)


def _service(cur):
    from services.db import DatabaseService
    service = DatabaseService.__new__(DatabaseService)
    service.client = _Rpc(cur)
    return service


def test_a_failed_read_keeps_an_empty_row(cur):
    from services import v4_practice_read
    _apply(cur)
    seed = _attempt(cur)
    with patch.object(v4_practice_read, "fast_read", side_effect=ValueError("bad")):
        stored = v4_practice_read.record(_service(cur), seed["attempt"], received_at=T0,
                                         metrics={}, transcript="um so")
    assert stored == {"outcome": "stored"}
    row = _row(cur, seed["attempt"])
    assert row["outcome"] == "failed"
    assert (row["s"], row["w"], row["willfident"]) == (None, None, None)
    assert v4_practice_read.reached_state(row, 0.0) == "not_reached_yet"


def _timing(service, practice, attempt, user, body):
    from flask import Flask, request

    from routes.v2 import user_sessions as us
    app = Flask(__name__)
    with patch.object(us, "db", service), \
            app.test_request_context(method="POST", json=body):
        request.user_id = user
        resp, status = inspect.unwrap(us.v2_confident_voice_practice_attempt_timing)(
            practice, attempt)
    return status, resp


def test_phone_times_are_kept_once_for_the_owner_and_never_answered(cur):
    _apply(cur)
    seed = _attempt(cur)
    _read(cur, seed["attempt"])
    service = _service(cur)
    service.get_confident_voice_practice = lambda _pid, _uid: {"id": seed["practice"]}
    stranger = str(uuid.uuid4())

    def times():
        return {k: v for k, v in _row(cur, seed["attempt"]).items()
                if k.startswith("phone_")}

    # Another user's times, and a wait past 600 000 ms, store nothing.
    assert _timing(service, seed["practice"], seed["attempt"], stranger,
                   {"stopped_at_ms": 1000, "shown_at_ms": 3000}) == (204, "")
    assert _timing(service, seed["practice"], seed["attempt"], seed["owner"],
                   {"stopped_at_ms": 0, "shown_at_ms": 600_001}) == (204, "")
    assert set(times().values()) == {None}
    # The owner's times are stored, once; the answer still says nothing.
    assert _timing(service, seed["practice"], seed["attempt"], seed["owner"],
                   {"stopped_at_ms": 1000, "shown_at_ms": 3500}) == (204, "")
    assert _timing(service, seed["practice"], seed["attempt"], seed["owner"],
                   {"stopped_at_ms": 1000, "shown_at_ms": 9000}) == (204, "")
    assert times() == {"phone_stopped_ms": 1000, "phone_shown_ms": 3500,
                       "phone_wait_ms": 2500}


def test_the_read_goes_with_the_try(cur):
    _apply(cur)
    seed = _attempt(cur)
    _read(cur, seed["attempt"])
    assert _row(cur, seed["attempt"]) is not None
    cur.execute("DELETE FROM public.confident_voice_practice_attempt WHERE id = %s",
                (seed["attempt"],))
    assert _row(cur, seed["attempt"]) is None
