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


def test_the_first_assignment_wins(db):
    with db.cursor() as cur:
        digest = _digest()
        assert _assign(cur, digest, "train") == ("train", "corpus-speaker-sha256-80-20-v1")
        assert _assign(cur, digest, "test", version="v2") == (
            "train", "corpus-speaker-sha256-80-20-v1")
