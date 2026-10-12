"""A corpus split survives a TRUNCATE too, on a disposable database (0434,
N56.4: "never re-shuffled").

0433's row-level trigger refuses UPDATE and DELETE but cannot see a
TRUNCATE. Pins: a TRUNCATE (plain, CASCADE, RESTART IDENTITY) is refused
with CORPUS_SPLIT_IMMUTABLE and every stored split stays; the trigger is
statement-level BEFORE TRUNCATE on 0433's refusing function; applying the
file again leaves exactly one such trigger and changes no row; 0433's
UPDATE/DELETE refusal is untouched; the function is still not PUBLIC."""
from __future__ import annotations

import hashlib
import os
import uuid

import psycopg2
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


def _stored(cur) -> str:
    digest = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    cur.execute(
        "INSERT INTO public.corpus_speaker_splits "
        "(speaker_key_sha256, split, split_version) VALUES (%s, 'test', 'v1') "
        "ON CONFLICT (speaker_key_sha256) DO NOTHING", (digest,))
    return digest


def _count(cur) -> int:
    cur.execute("SELECT count(*) FROM public.corpus_speaker_splits")
    return cur.fetchone()[0]


@pytest.mark.parametrize("statement", [
    "TRUNCATE public.corpus_speaker_splits",
    "TRUNCATE TABLE public.corpus_speaker_splits CASCADE",
    "TRUNCATE public.corpus_speaker_splits RESTART IDENTITY",
])
def test_a_truncate_is_refused_and_every_split_stays(db, statement):
    with db.cursor() as cur:
        digest = _stored(cur)
        before = _count(cur)
        with pytest.raises(psycopg2.errors.CheckViolation,
                           match="CORPUS_SPLIT_IMMUTABLE"):
            cur.execute(statement)
        assert _count(cur) == before
        cur.execute("SELECT split FROM public.corpus_speaker_splits "
                    "WHERE speaker_key_sha256 = %s", (digest,))
        assert cur.fetchone()[0] == "test"
