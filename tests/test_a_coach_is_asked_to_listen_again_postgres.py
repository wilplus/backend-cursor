"""
STORY    As a coach, I want to be asked to listen again only for clips I judged
         blind, once at a time, with a fresh line each time, so that my second
         answer is still my own and not prompted by the machine.
OUTCOME
  O1  The flag opens one ask per coach with a blind judgment of record and
      none for a self-report, a peer, an abstention, an anonymous row or a
      coach whose rating was not blind; no second ask while one is open.
  O2  The coach's new answer closes their ask; the next flag opens a new one
      with the next signed line (A then B) and the closed ask stays as history.
  O3  Never-2: the ask carries no reason, answer or machine read, by the
      table's shape (only take, moment, coach, line key and two times).
PROVES   O1 -> test_the_flag_asks_every_coach_of_record_once_and_only_them
         O2 -> test_an_answer_closes_the_ask_and_the_next_flag_rotates_the_line
         O3 -> test_an_answer_closes_the_ask_and_the_next_flag_rotates_the_line
WHY      0444 (QG12a A, P26c): the coach's second answer must stay blind.
"""
from __future__ import annotations

import os
import uuid

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)


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


def test_an_answer_closes_the_ask_and_the_next_flag_rotates_the_line(db):
    take, snippet = str(uuid.uuid4()), str(uuid.uuid4())
    coach = str(uuid.uuid4())
    with db.cursor() as cur:
        _label(cur, snippet, coach, value="no")
        assert _flag(cur, take, snippet) == 1
        assert _asks(cur, snippet) == [(coach, "P26c-A", True)]

        # The coach's new blind answer lands: their ask closes.
        cur.execute("SELECT public.mark_coach_listen_again_heard_v1(%s, %s)",
                    (snippet, coach))
        assert cur.fetchone()[0] == 1
        assert _asks(cur, snippet) == [(coach, "P26c-A", False)]

        # A later flag opens a new ask with the next line; the old one is history.
        assert _flag(cur, take, snippet) == 1
        assert _asks(cur, snippet) == [(coach, "P26c-A", False), (coach, "P26c-B", True)]

        # Never-2: what the coach's list reads cannot carry why, by its shape.
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' "
                    "AND table_name = 'coach_listen_again_requests'")
        assert {r[0] for r in cur.fetchall()} == {
            "id", "take_session_id", "snippet_id", "coach_id", "line_key",
            "requested_at", "heard_at"}
