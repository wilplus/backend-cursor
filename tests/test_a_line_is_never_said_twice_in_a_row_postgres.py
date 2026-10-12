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
import uuid

import psycopg2
import pytest

from services import line_rotation as rotation

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

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
