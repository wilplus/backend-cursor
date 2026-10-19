"""
STORY    As the founder, I want each corpus speaker to stay in the train or
         test split they were first given, so that evaluation results are
         honest.
OUTCOME
  O1  The app's writer (services.corpus_split.assign_speaker_split) stores a
      speaker's split once, and a stored split wins over a later computation.
  O2  The stored row cannot be changed or removed: an UPDATE and a DELETE
      are refused with CORPUS_SPLIT_IMMUTABLE, so no path can re-shuffle.
PROVES   O1 -> test_the_first_assignment_wins
         O2 -> test_an_update_or_delete_is_refused
WHY      Migration 0433 (N56.4). Runs only on a disposable database whose
         name starts with willab_confident_moment_.
"""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import psycopg2
import psycopg2.extras
import pytest

from services import corpus_split

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


class _Table:
    """The two PostgREST calls corpus_split makes, as SQL."""

    def __init__(self, conn, name):
        self.conn, self.name, self.row, self.key = conn, name, None, None

    def upsert(self, row, on_conflict, ignore_duplicates):
        assert ignore_duplicates and on_conflict == "speaker_key_sha256"
        self.row = row
        return self

    def select(self, _columns):
        return self

    def eq(self, _column, value):
        self.key = value
        return self

    def limit(self, _n):
        return self

    def execute(self):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if self.row is not None:
                cur.execute(
                    "INSERT INTO public.corpus_speaker_splits "
                    "(speaker_key_sha256, split, split_version) VALUES (%s, %s, %s) "
                    "ON CONFLICT (speaker_key_sha256) DO NOTHING",
                    (self.row["speaker_key_sha256"], self.row["split"],
                     self.row["split_version"]))
                return SimpleNamespace(data=[])
            cur.execute("SELECT split, split_version, assigned_at "
                        "FROM public.corpus_speaker_splits "
                        "WHERE speaker_key_sha256 = %s", (self.key,))
            return SimpleNamespace(data=[dict(r) for r in cur.fetchall()])


def _database(conn):
    return SimpleNamespace(client=SimpleNamespace(
        table=lambda name: _Table(conn, name)))


def test_the_first_assignment_wins(db):
    database = _database(db)
    fresh = f"speaker-{uuid.uuid4()}"
    stored = corpus_split.assign_speaker_split(database, fresh)
    assert stored["split"] == corpus_split.corpus_split(fresh)
    assert stored["split_version"] == corpus_split.SPLIT_VERSION
    # A speaker already stored on the other side (an older salt, say) keeps
    # that side: the app's writer never replaces it.
    moved = f"speaker-{uuid.uuid4()}"
    other = "test" if corpus_split.corpus_split(moved) == "train" else "train"
    with db.cursor() as cur:
        cur.execute("INSERT INTO public.corpus_speaker_splits "
                    "(speaker_key_sha256, split, split_version) VALUES (%s, %s, 'old-v0')",
                    (corpus_split.speaker_key_digest(moved), other))
    again = corpus_split.assign_speaker_split(database, moved)
    assert (again["split"], again["split_version"]) == (other, "old-v0")


def test_an_update_or_delete_is_refused(db):
    key = f"speaker-{uuid.uuid4()}"
    digest = corpus_split.speaker_key_digest(key)
    corpus_split.assign_speaker_split(_database(db), key)
    with db.cursor() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation, match="CORPUS_SPLIT_IMMUTABLE"):
            cur.execute("UPDATE public.corpus_speaker_splits SET split = "
                        "CASE split WHEN 'train' THEN 'test' ELSE 'train' END "
                        "WHERE speaker_key_sha256 = %s", (digest,))
        with pytest.raises(psycopg2.errors.CheckViolation, match="CORPUS_SPLIT_IMMUTABLE"):
            cur.execute("DELETE FROM public.corpus_speaker_splits "
                        "WHERE speaker_key_sha256 = %s", (digest,))
        cur.execute("SELECT count(*) FROM public.corpus_speaker_splits "
                    "WHERE speaker_key_sha256 = %s", (digest,))
        assert cur.fetchone()[0] == 1
