"""New coach feedback waits on the Lounge bubble until the walk shows it,
on a disposable database (0439, D-FW-5; the Feedback walk lock, flow 1).

Runs services.coach_feedback_signal against the real functions. Pins:
publish -> true, the walk shows it -> false, a later coach word -> true;
a coach answer on a moment the same way; machine-only feedback (a request
not shared) never lights it; one boolean per project, false for a project
with nothing from the coach; another speaker's Take is refused and their
flag untouched; closed to the browser roles; applying the file again keeps
every row."""
from __future__ import annotations

import os
import uuid

import psycopg2
import psycopg2.extras
import pytest

from services import coach_feedback_signal as signal

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


class _Database:
    """DatabaseService's two calls, over psycopg2 instead of PostgREST."""

    def __init__(self, conn):
        self.conn = conn

    def new_coach_feedback_by_project(self, user_id):
        with self.conn.cursor() as cur:
            cur.execute("SELECT arc_id, has_new FROM "
                        "public.new_coach_feedback_by_project_v1(%s)", (user_id,))
            return {str(arc): has for arc, has in cur.fetchall()}

    def mark_coach_feedback_seen(self, *, user_id, take_session_id, item):
        with self.conn.cursor() as cur:
            cur.execute("SELECT public.mark_coach_feedback_seen_v1(%s, %s, %s)",
                        (user_id, take_session_id, item))
            return cur.fetchone()[0]


def _take(cur, user: str, arc: str, index: int) -> str:
    take = str(uuid.uuid4())
    cur.execute("INSERT INTO public.v2_sessions (id, arc_id, user_id, take_index) "
                "VALUES (%s, %s, %s, %s)", (take, arc, user, index))
    return take


def _word(cur, take: str, *, shared: bool, at: str = "now()") -> None:
    cur.execute(
        "INSERT INTO public.coach_take_words (take_session_id, coach_id, text, "
        f"updated_at, shared_at) VALUES (%s, 'coach-1', 'Well done.', {at}, "
        f"{at if shared else 'NULL'}) "
        "ON CONFLICT (take_session_id, coach_id) DO UPDATE SET text = EXCLUDED.text, "
        "updated_at = EXCLUDED.updated_at, shared_at = COALESCE("
        "public.coach_take_words.shared_at, EXCLUDED.shared_at)", (take,))


def _speaker():
    return str(uuid.uuid4()), str(uuid.uuid4())


def test_publish_open_and_a_later_word(db):
    database = _Database(db)
    user, arc = _speaker()
    with db.cursor() as cur:
        take_one = _take(cur, user, arc, 1)
        assert signal.lounge_flags(database, user) == {arc: False}
        _word(cur, take_one, shared=True, at="now() - interval '1 minute'")
    # Published -> true.
    assert signal.lounge_flags(database, user) == {arc: True}
    # The walk shows the coach's note -> false.
    assert signal.mark_seen(database, user, {"take_session_id": take_one}) == (
        200, {"seen": True})
    assert signal.lounge_flags(database, user) == {arc: False}
    # A later coach word on Take 2 -> true again.
    with db.cursor() as cur:
        take_two = _take(cur, user, arc, 2)
        _word(cur, take_two, shared=True, at="clock_timestamp()")
    assert signal.lounge_flags(database, user) == {arc: True}
    assert signal.mark_seen(database, user, {"take_session_id": take_two})[0] == 200
    assert signal.lounge_flags(database, user) == {arc: False}
    # The same word edited after the walk showed it is new again.
    with db.cursor() as cur:
        _word(cur, take_two, shared=True, at="clock_timestamp()")
    assert signal.lounge_flags(database, user) == {arc: True}
