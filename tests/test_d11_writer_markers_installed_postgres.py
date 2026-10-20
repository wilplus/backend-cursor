"""
GUARD     Every installed D11 writer function (the database functions that write
          the feedback inventory) still starts with its lock preamble, in place,
          as the database actually holds it after all migrations.
CATCHES   A later migration that rewrites a writer and drops, moves or doubles
          its lock preamble, so concurrent writes stop being serialised; and a
          writer listed as unresolved that has quietly been repaired.
IF REMOVED  Only the file copy (or 0327's own re-run) is checked, so a writer
          broken by a later migration reaches production unnoticed.
PROVES    test_the_installed_writer_carries_its_d11_marker (one case per
          registered writer: marker once, right after BEGIN; unresolved
          writers have no marker)
WHY       Migration 0327 (D11 lock order); rehearsal database only.
"""
from __future__ import annotations

import os

import psycopg2
import pytest

from tests.d11_manifest_walk import (
    UNRESOLVED,
    registered_writers,
)

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="disposable rehearsal only")


@pytest.fixture
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    connection = psycopg2.connect(**parsed)
    connection.autocommit = True
    try:
        yield connection
    finally:
        connection.close()


def _definition(db, signature: str) -> str:
    with db.cursor() as cur:
        cur.execute("SELECT pg_get_functiondef(%s::regprocedure)", (signature,))
        return cur.fetchone()[0]


@pytest.mark.parametrize("signature", sorted(registered_writers()))
def test_the_installed_writer_carries_its_d11_marker(db, signature):
    spec = registered_writers()[signature]
    body = _definition(db, signature)
    if signature in UNRESOLVED:
        assert spec["marker"] not in body, f"{signature} is repaired: update UNRESOLVED"
        return
    assert spec["marker"] in body, f"{signature} lost '{spec['marker']}'"
    if "sql" in spec:
        preamble = "\nBEGIN\n -- " + spec["marker"] + "\n" + spec["sql"]
        assert preamble in body, f"{signature}: preamble moved or drifted"
        assert body.count(spec["marker"]) == 1, f"{signature}: injected twice"
