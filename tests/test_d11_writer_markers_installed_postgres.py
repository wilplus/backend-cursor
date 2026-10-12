"""Every D11 writer's INSTALLED body carries 0327's preamble, in place.

The companion of tests/test_d11_writer_markers_survive_the_manifest.py, run
against a database instead of the files.  The existing marker test
(tests/test_confident_moment_coaching_bundle_postgres.py) re-executes 0327
before it looks, so it can only ever see 0327's own result.  This one
re-executes nothing: it reads the definitions as the lane left them.  Since
2026-09-25 the lane re-applies 0335 and 0354 after 0327, as the manifest
does, so the bodies here match production's.

For each writer 0327 injects into, the preamble must sit directly after the
body's ``BEGIN`` line and be byte-identical to 0327's entry.  That covers
placement and lock order in one comparison.  The two legacy root writers are
rewritten by 0327 differently, so for them the marker alone is checked, as
0327's own verifier does.  A writer in UNRESOLVED must be ABSENT here, which
pins production's state.  When a founder-approved fix lands, this fails until
the entry is removed from UNRESOLVED.

``accept_phase1_processing_authorization_v2`` (0357) is checked too.  0327
never named it; 0366 gives it v1's preamble, and ``registered_writers`` lists
it next to 0327's registry.

Rehearsal tier only (the released confident-moment lane).
"""
from __future__ import annotations

import os

import psycopg2
import pytest

from tests.test_d11_writer_markers_survive_the_manifest import (
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
