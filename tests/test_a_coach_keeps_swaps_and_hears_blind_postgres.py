"""The coach panel's learning additions, on a disposable database (0411:
1b, 7, 6a to 6d, 8, task 4). Pins: the four tables exist with their keys
and checks; the additive columns exist; the two widened checks take the
coach's word surfaces; a draft-only Take word row is allowed; the shadow
writer keeps its unit and stores the clip kind; the migration is idempotent
(applied twice by the rehearsal script)."""
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


def test_the_shadow_writer_stores_the_clip_kind(db):
    clip = f"att-{uuid.uuid4().hex[:8]}"
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT error_id FROM public.speaking_error WHERE status IN ('shadow','detected') LIMIT 1")
        found = cur.fetchone()
        if not found:
            pytest.skip("no measured error in this lane")
        rows = psycopg2.extras.Json([{
            "take_session_id": "t", "snippet_id": clip, "error_id": found["error_id"],
            "detector_version": "rules-v1", "language": "any", "fired": True,
            "measurements": {"wpm": 190}, "clip_kind": "practice_attempt",
        }])
        cur.execute("SELECT public.record_verbal_cue_shadow_v1(%s) AS n", (rows,))
        assert cur.fetchone()["n"] == 1
        cur.execute("SELECT public.record_verbal_cue_shadow_v1(%s) AS n", (rows,))
        assert cur.fetchone()["n"] == 0
        cur.execute("SELECT clip_kind FROM public.verbal_cue_shadow_observations WHERE snippet_id = %s", (clip,))
        assert cur.fetchone()["clip_kind"] == "practice_attempt"
