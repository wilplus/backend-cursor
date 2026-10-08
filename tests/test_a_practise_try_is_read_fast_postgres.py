"""0450: a practise try is read fast (V4 B1.4, build plan D-ML-9; founder
O5, V7 A), on the disposable rehearsal database.

Pins:
  * the read is stored once per try with the server's times; the database
    reads the try's practice, Take and owner itself and computes W and S*W;
  * a failed read keeps its row with no values;
  * the phone's two times are stored once, only for the try's owner; a
    wait outside 0..600 000 ms is refused;
  * the table's checks refuse a wrong W, S*W, outcome or order of times;
  * the read goes with the try (FK cascade);
  * browser roles hold nothing; service_role reads, deletes (the purge) and
    calls; the file applied twice changes nothing.
"""
from __future__ import annotations

import pathlib
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg2
import psycopg2.errors
import psycopg2.extras
import pytest

from tests import test_a_take_draws_its_random_moments_postgres as draw_suite
from tests import test_the_shadow_writer_accepts_the_frame_the_code_builds_postgres as base

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


def _timing(cur, attempt, owner, stopped, shown):
    cur.execute("SELECT public.record_v4_practice_timing_v1(%s::uuid, %s::uuid, %s, %s) AS r",
                (attempt, owner, stopped, shown))
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


def test_one_lexical_signal_is_its_own_w(cur):
    _apply(cur)
    seed = _attempt(cur)
    _read(cur, seed["attempt"], hedging=None)
    assert _row(cur, seed["attempt"])["w"] == Decimal("0.9")


def test_a_failed_read_keeps_its_row(cur):
    _apply(cur)
    seed = _attempt(cur)
    _read(cur, seed["attempt"], outcome="failed", s=None, filler=None, hedging=None)
    row = _row(cur, seed["attempt"])
    assert row["outcome"] == "failed" and row["w"] is None and row["willfident"] is None


def test_an_unknown_try_stores_nothing(cur):
    _apply(cur)
    assert _read(cur, str(uuid.uuid4())) == {"outcome": "no_attempt"}


def test_the_phone_times_are_stored_once_for_the_owner_only(cur):
    _apply(cur)
    seed = _attempt(cur)
    _read(cur, seed["attempt"])
    assert _timing(cur, seed["attempt"], str(uuid.uuid4()), 1000, 4000) == {"outcome": "unchanged"}
    assert _timing(cur, seed["attempt"], seed["owner"], 1000, 4200) == {"outcome": "stored"}
    assert _timing(cur, seed["attempt"], seed["owner"], 1000, 9000) == {"outcome": "unchanged"}
    row = _row(cur, seed["attempt"])
    assert (row["phone_stopped_ms"], row["phone_shown_ms"], row["phone_wait_ms"]) == (1000, 4200, 3200)


@pytest.mark.parametrize("stopped,shown", [(5000, 4000), (0, 600001), (None, 1)])
def test_a_wait_out_of_range_is_refused(cur, stopped, shown):
    _apply(cur)
    seed = _attempt(cur)
    _read(cur, seed["attempt"])
    with pytest.raises(psycopg2.errors.RaiseException, match="V4_PRACTICE_TIMING_INVALID"):
        _timing(cur, seed["attempt"], seed["owner"], stopped, shown)


@pytest.mark.parametrize("kwargs,error", [
    ({"outcome": "maybe"}, psycopg2.errors.CheckViolation),
    ({"outcome": "failed"}, psycopg2.errors.CheckViolation),
    ({"s": 1.2}, psycopg2.errors.CheckViolation),
    ({"ready": T0 - timedelta(seconds=1)}, psycopg2.errors.CheckViolation),
])
def test_the_table_refuses_a_wrong_read(cur, kwargs, error):
    _apply(cur)
    seed = _attempt(cur)
    with pytest.raises(error):
        _read(cur, seed["attempt"], **kwargs)


def test_the_read_goes_with_the_try(cur):
    _apply(cur)
    seed = _attempt(cur)
    _read(cur, seed["attempt"])
    cur.execute("DELETE FROM public.confident_voice_practice_attempt WHERE id = %s",
                (seed["attempt"],))
    assert _row(cur, seed["attempt"]) is None


def test_the_door_and_idempotency(cur):
    _apply(cur)
    _apply(cur)
    for role in ("anon", "authenticated"):
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        if cur.fetchone() is None:
            continue
        cur.execute("SELECT has_table_privilege(%s, 'public.v4_practice_reads', 'SELECT') AS t, "
                    "has_function_privilege(%s, 'public.record_v4_practice_timing_v1(uuid, uuid, bigint, bigint)', 'EXECUTE') AS f",
                    (role, role))
        assert cur.fetchone() == {"t": False, "f": False}
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'service_role'")
    if cur.fetchone() is not None:
        for privilege, held in (("SELECT", True), ("DELETE", True),
                                ("INSERT", False), ("UPDATE", False)):
            cur.execute("SELECT has_table_privilege('service_role', "
                        "'public.v4_practice_reads', %s) AS p", (privilege,))
            assert cur.fetchone()["p"] is held, privilege
