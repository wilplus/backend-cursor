"""A signed line is never said twice in a row, on a disposable database
(0438, D-FW-3; docs/SIGNED-line-bank-2026-10-06.md "Rotation").

Runs services.line_rotation.pick against the real pick_line_bank_line_v1
across two Takes of one speaker. Pins: Take 1 rotates through ordinary
lines and never offers a later line; Take 2 says the later line, naming
Take 1, only when the cue was measurably weaker then, and never twice in a
row; the rotation continues past it; two speakers and two banks keep
separate memories; concurrent picks never return the same index; the
table and the function are closed to the browser roles; applying the file
again keeps every row."""
from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

import psycopg2
import pytest

from services import line_rotation as rotation
from services.line_bank import BANKS

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)
MIGRATION = (Path(__file__).resolve().parents[1] / "migrations"
             / "a_line_is_never_said_twice_in_a_row.sql")

WEAKER_THEN = {"pitch_range": -0.4}
STRONGER_NOW = {"pitch_range": 0.4}


@pytest.fixture(scope="module")
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    try:
        yield conn
    finally:
        conn.close()


class _Database:
    """DatabaseService.pick_line_bank_line, over psycopg2 instead of PostgREST."""

    def __init__(self, conn):
        self.conn = conn

    def pick_line_bank_line(self, *, user_id, bank, size, later_true):
        with self.conn.cursor() as cur:
            cur.execute("SELECT public.pick_line_bank_line_v1(%s, %s, %s, %s)",
                        (user_id, bank, size, later_true))
            return cur.fetchone()[0]


def _speaker() -> str:
    return f"speaker-{uuid.uuid4().hex[:10]}"


def test_two_takes_rotate_and_say_the_later_line_only_when_true(db):
    database, user = _Database(db), _speaker()
    # Take 1: ordinary lines only, never the same twice in a row.
    take_one = [rotation.pick(database, user_id=user, bank="B02", take_index=1,
                              reads_now=STRONGER_NOW, reads_then=WEAKER_THEN)
                for _ in range(3)]
    assert take_one == [{"bank": "B02", "index": i} for i in (0, 1, 2)]
    # Take 2, the cue no weaker on Take 1: still an ordinary line, next in turn.
    flat = rotation.pick(database, user_id=user, bank="B02", take_index=2,
                         earlier_take_index=1, reads_now=WEAKER_THEN,
                         reads_then=WEAKER_THEN)
    assert flat == {"bank": "B02", "index": 3}
    # Take 2, the cue measurably weaker on Take 1: the later line, Take 1 named.
    later = rotation.pick(database, user_id=user, bank="B02", take_index=2,
                          earlier_take_index=1, reads_now=STRONGER_NOW,
                          reads_then=WEAKER_THEN)
    assert later == {"bank": "B02", "later_take": 1}
    assert rotation.say(later) == "Your voice moved more here than on Take 1."
    # True again: never the same later line twice in a row; the rotation
    # continues after the last ordinary line (index 3 of four -> 0).
    again = rotation.pick(database, user_id=user, bank="B02", take_index=2,
                          earlier_take_index=1, reads_now=STRONGER_NOW,
                          reads_then=WEAKER_THEN)
    assert again == {"bank": "B02", "index": 0}
    with db.cursor() as cur:
        cur.execute("SELECT last_index, last_plain_index FROM public.line_bank_memory "
                    "WHERE user_id = %s AND bank = 'B02'", (user,))
        assert cur.fetchone() == (0, 0)


def test_speakers_and_banks_keep_separate_memories(db):
    database = _Database(db)
    a, b = _speaker(), _speaker()
    assert rotation.pick(database, user_id=a, bank="NX3a") == {"bank": "NX3a", "index": 0}
    assert rotation.pick(database, user_id=a, bank="NX3a") == {"bank": "NX3a", "index": 1}
    assert rotation.pick(database, user_id=b, bank="NX3a") == {"bank": "NX3a", "index": 0}
    assert rotation.pick(database, user_id=a, bank="CM3b") == {"bank": "CM3b", "index": 0}


def test_a_long_run_never_repeats(db):
    database, user = _Database(db), _speaker()
    shown = [rotation.pick(database, user_id=user, bank="B11")["index"]
             for _ in range(3 * len(BANKS["B11"]))]
    assert all(x != y for x, y in zip(shown, shown[1:]))


def test_concurrent_picks_never_say_the_same_line(db):
    user = _speaker()
    results: list = []
    barrier = threading.Barrier(4)

    def worker():
        conn = psycopg2.connect(DSN)
        conn.autocommit = True
        try:
            barrier.wait()
            results.append(_Database(conn).pick_line_bank_line(
                user_id=user, bank="B13", size=len(BANKS["B13"]), later_true=False))
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert sorted(results) == [0, 1, 2, 3]


def test_bad_input_is_refused(db):
    with db.cursor() as cur:
        with pytest.raises(psycopg2.Error):
            cur.execute("SELECT public.pick_line_bank_line_v1('', 'B02', 4, false)")
        with pytest.raises(psycopg2.Error):
            cur.execute("SELECT public.pick_line_bank_line_v1('u', 'B02', 0, false)")
        with pytest.raises(psycopg2.Error, match="LINE_BANK_SIZE_INVALID"):
            # GPT-0438: a bank of one line would say it twice in a row.
            cur.execute("SELECT public.pick_line_bank_line_v1('u', 'B02', 1, false)")
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("SELECT public.pick_line_bank_line_v1('u', 'not a bank!', 4, false)")


def test_closed_to_the_browser_and_idempotent(db):
    user = _speaker()
    _Database(db).pick_line_bank_line(user_id=user, bank="B05", size=5, later_true=False)
    with db.cursor() as cur:
        cur.execute("SELECT relrowsecurity FROM pg_class "
                    "WHERE oid = 'public.line_bank_memory'::regclass")
        assert cur.fetchone()[0] is True
        for role in ("anon", "authenticated"):
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            if cur.fetchone() is None:
                continue
            cur.execute("SELECT has_table_privilege(%s, 'public.line_bank_memory', "
                        "'SELECT, INSERT, UPDATE, DELETE')", (role,))
            assert cur.fetchone()[0] is False
            cur.execute("SELECT has_function_privilege(%s, "
                        "'public.pick_line_bank_line_v1(text, text, integer, boolean)', "
                        "'EXECUTE')", (role,))
            assert cur.fetchone()[0] is False
        cur.execute("SELECT has_function_privilege('public', "
                    "'public.pick_line_bank_line_v1(text, text, integer, boolean)', "
                    "'EXECUTE')")
        assert cur.fetchone()[0] is False
        cur.execute("SELECT count(*) FROM public.line_bank_memory")
        before = cur.fetchone()[0]
        cur.execute(MIGRATION.read_text())
        cur.execute("SELECT count(*) FROM public.line_bank_memory")
        assert cur.fetchone()[0] == before
        cur.execute("SELECT last_index FROM public.line_bank_memory "
                    "WHERE user_id = %s AND bank = 'B05'", (user,))
        assert cur.fetchone()[0] == 0
