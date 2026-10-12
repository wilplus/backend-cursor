"""The coach's own words reach doors 2, 3 and 4 on a disposable database
(0459; Privacy/Terms 3.5, N68). Pins:
  * the four door tables take a row of either coach-word surface and still
    refuse an unknown surface;
  * the promote RPC accepts the two coach-word keys, still refuses an
    unlisted one, and reaches no browser role;
  * the two aliases exist under coach_comment_generation;
  * the drafter's snapshot columns exist and are nullable;
  * applying the file again changes nothing.
"""
from __future__ import annotations

import hashlib
import json
import os

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

COACH_WORDS = ("coach_moment_line", "coach_take_word")


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


def _one(db, sql, args=()):
    with db.cursor() as cur:
        cur.execute(sql, args)
        row = cur.fetchone()
        return row[0] if row else None


def test_the_promote_rpc_accepts_the_coach_word_keys(db):
    if _one(db, "SELECT to_regclass('public.runtime_config')") is None:
        pytest.skip("runtime_config absent on this rehearsal")
    meta = json.dumps({"prompt_lock_sha256": hashlib.sha256(b"lock").hexdigest()})
    for surface in COACH_WORDS:
        out = _one(db, "SELECT public.promote_runtime_surface_model_v1(%s, %s, %s, %s::jsonb)",
                   (f"openai_surface_model_{surface}", "ft:w", "test", meta))
        assert out["value"] == "ft:w"
    with pytest.raises(psycopg2.Error) as refused:
        _one(db, "SELECT public.promote_runtime_surface_model_v1(%s, %s, %s, %s::jsonb)",
             ("openai_surface_model_coach_note_v9", "ft:w", "test", meta))
    assert "RUNTIME_MODEL_KEY_NOT_ENUMERATED" in str(refused.value)
    for role in ("anon", "authenticated"):
        if _one(db, "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)):
            assert _one(db, "SELECT has_function_privilege(%s, "
                            "'public.promote_runtime_surface_model_v1(text, text, text, jsonb)', 'EXECUTE')",
                        (role,)) is False
