"""A corpus speaker keeps its split, on a disposable database (0433, N56.4).

Pins: the table exists with RLS on and nothing granted to the browser roles;
applying the file again changes nothing; the digest, split and version shapes
hold; the write the app makes (ON CONFLICT DO NOTHING) keeps the first
assignment; an UPDATE or a DELETE is refused, so no code path can re-shuffle
a speaker; the trigger function is not executable by PUBLIC."""
from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)
MIGRATION = (Path(__file__).resolve().parents[1] / "migrations"
             / "a_corpus_speaker_keeps_its_split.sql")


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


def _digest() -> str:
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()


def _assign(cur, digest, split, version="corpus-speaker-sha256-80-20-v1"):
    """The app's write: insert once, then read back what is stored."""
    cur.execute(
        "INSERT INTO public.corpus_speaker_splits "
        "(speaker_key_sha256, split, split_version) VALUES (%s, %s, %s) "
        "ON CONFLICT (speaker_key_sha256) DO NOTHING", (digest, split, version))
    cur.execute("SELECT split, split_version FROM public.corpus_speaker_splits "
                "WHERE speaker_key_sha256 = %s", (digest,))
    return cur.fetchone()


def test_the_table_exists_with_rls_and_no_browser_grants(db):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT relrowsecurity FROM pg_class "
                    "WHERE oid = 'public.corpus_speaker_splits'::regclass")
        assert cur.fetchone()["relrowsecurity"] is True
        for role in ("anon", "authenticated"):
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            if cur.fetchone() is None:
                continue
            cur.execute("SELECT has_table_privilege(%s, 'public.corpus_speaker_splits', "
                        "'SELECT') AS s", (role,))
            assert cur.fetchone()["s"] is False
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'corpus_speaker_splits' "
                    "ORDER BY ordinal_position")
        assert [r["column_name"] for r in cur.fetchall()] == [
            "speaker_key_sha256", "split", "split_version", "assigned_at"]


def test_applying_it_again_changes_nothing(db):
    with db.cursor() as cur:
        digest = _digest()
        _assign(cur, digest, "test")
        cur.execute(MIGRATION.read_text())
        cur.execute("SELECT split FROM public.corpus_speaker_splits "
                    "WHERE speaker_key_sha256 = %s", (digest,))
        assert cur.fetchone()[0] == "test"
        cur.execute("SELECT count(*) FROM pg_trigger "
                    "WHERE tgname = 'corpus_speaker_splits_never_change'")
        assert cur.fetchone()[0] == 1


def test_the_shapes_hold(db):
    with db.cursor() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation):
            _assign(cur, "Jane Doe", "train")
        with pytest.raises(psycopg2.errors.CheckViolation):
            _assign(cur, _digest(), "validation")
        with pytest.raises(psycopg2.errors.CheckViolation):
            _assign(cur, _digest(), "train", version=" ")


def test_the_first_assignment_wins(db):
    with db.cursor() as cur:
        digest = _digest()
        assert _assign(cur, digest, "train") == ("train", "corpus-speaker-sha256-80-20-v1")
        assert _assign(cur, digest, "test", version="v2") == (
            "train", "corpus-speaker-sha256-80-20-v1")


def test_a_split_is_never_updated_or_deleted(db):
    with db.cursor() as cur:
        digest = _digest()
        _assign(cur, digest, "train")
        with pytest.raises(psycopg2.errors.CheckViolation, match="CORPUS_SPLIT_IMMUTABLE"):
            cur.execute("UPDATE public.corpus_speaker_splits SET split = 'test' "
                        "WHERE speaker_key_sha256 = %s", (digest,))
        with pytest.raises(psycopg2.errors.CheckViolation, match="CORPUS_SPLIT_IMMUTABLE"):
            cur.execute("DELETE FROM public.corpus_speaker_splits "
                        "WHERE speaker_key_sha256 = %s", (digest,))
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                "INSERT INTO public.corpus_speaker_splits "
                "(speaker_key_sha256, split, split_version) VALUES (%s, 'test', 'v') "
                "ON CONFLICT (speaker_key_sha256) DO UPDATE SET split = EXCLUDED.split",
                (digest,))
        cur.execute("SELECT split FROM public.corpus_speaker_splits "
                    "WHERE speaker_key_sha256 = %s", (digest,))
        assert cur.fetchone()[0] == "train"


def test_the_trigger_function_is_not_public(db):
    with db.cursor() as cur:
        cur.execute("SELECT has_function_privilege('public', "
                    "'public.corpus_speaker_splits_never_change()', 'EXECUTE')")
        assert cur.fetchone()[0] is False
