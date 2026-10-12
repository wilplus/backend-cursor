"""A coach is asked to listen again, blind, on a disposable database (0444;
QG12a A, P26b A, N53.4; P26c, N54.1; Q-B8 A, N62; build plan D-CP-10).

Pins:
  * the table exists with RLS on and, by its shape, no column that could
    carry a reason, an answer or a read; browser roles and PUBLIC hold
    nothing on it or on the two functions; service_role reads, deletes and
    calls the functions, and cannot write the table by hand;
  * the file applied again changes nothing;
  * the flag writes one open ask per coach with a blind judgment of record
    on the clip (coach lane, no self-report, no abstention, no peer, no
    anonymous row), none for a coach who has not judged it, none twice
    while one is open; the line key rotates A, B, C, A per coach;
  * the coach's new answer closes their open ask; a later flag opens a new
    one and the closed one stays as history;
  * a coach whose rating was not blind (0411) is not asked;
  * the rotation reads the coach's latest line, so a purge of older rows
    never makes a line repeat; two flags on one moment at once write one
    ask and neither fails (per-coach lock, ON CONFLICT DO NOTHING);
  * the moment is stored in canonical uuid text, whatever case it was sent
    in, and the heard mark finds it the same way;
  * bad input is refused by name.
"""
from __future__ import annotations

import os
import pathlib
import uuid

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

ROOT = pathlib.Path(__file__).resolve().parents[1]


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


def _label(cur, snippet_id, rater, *, value="no", lane="coach", self_report=False,
           unrateable=False, blind=True):
    cur.execute(
        "INSERT INTO public.confidence_labels (snippet_id, rater_id, source, confident, "
        "state_id, value, lane, self_report, unrateable, blind) VALUES (%s, %s, %s, %s, "
        "'confidence', %s, %s, %s, %s, %s)",
        (snippet_id, rater, "coach" if lane == "coach" else "game",
         True if value == "yes" else False if value == "no" else None,
         value, lane, self_report, unrateable, blind))


def _flag(cur, take, snippet) -> int:
    cur.execute("SELECT public.request_coach_listen_again_v1(%s, %s)", (take, snippet))
    return cur.fetchone()[0]


def _asks(cur, snippet):
    cur.execute("SELECT coach_id, line_key, heard_at IS NULL AS open "
                "FROM public.coach_listen_again_requests WHERE snippet_id = %s "
                "ORDER BY requested_at, coach_id", (snippet,))
    return [tuple(r) for r in cur.fetchall()]


def test_the_flag_asks_every_coach_of_record_once_and_only_them(db):
    take, snippet = str(uuid.uuid4()), str(uuid.uuid4())
    coach_a, coach_b = sorted(str(uuid.uuid4()) for _ in range(2))
    with db.cursor() as cur:
        _label(cur, snippet, coach_a, value="yes")
        _label(cur, snippet, coach_b, value="not_sure")
        # Never asked: the speaker on their own clip, a peer, an Audio-unclear
        # abstention, an anonymous row, a coach whose rating was not blind
        # (0411: they had seen the clip's non-blind side first).
        _label(cur, snippet, str(uuid.uuid4()), value="yes", self_report=True)
        _label(cur, snippet, str(uuid.uuid4()), value="yes", lane="game_peer")
        _label(cur, snippet, str(uuid.uuid4()), value="audio_unclear", unrateable=True)
        _label(cur, snippet, str(uuid.uuid4()), value="no", blind=False)
        cur.execute("INSERT INTO public.confidence_labels (snippet_id, rater_id, source, "
                    "confident, state_id, value, lane) VALUES (%s, NULL, 'coach', true, "
                    "'confidence', 'yes', 'coach')", (snippet,))
        assert _flag(cur, take, snippet) == 2
        assert _asks(cur, snippet) == [(coach_a, "P26c-A", True), (coach_b, "P26c-A", True)]
        # Flagged again while both are open: nothing new.
        assert _flag(cur, take, snippet) == 0
        assert len(_asks(cur, snippet)) == 2
        # A clip nobody judged yet: nothing to add (it is still in the queue).
        assert _flag(cur, take, str(uuid.uuid4())) == 0
