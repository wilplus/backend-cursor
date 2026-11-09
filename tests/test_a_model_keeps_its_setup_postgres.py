"""
STORY    As someone starting a model, I want my setup kept with the model
         from step to step, and a moment of a Take gathered into my model
         only once, so ✕ loses nothing and a rerun of the gathering adds
         nothing twice (N566 item 2, MOD-02, MOD-25).
OUTCOME
  O1  ai_models has a setup that is always an object, empty for a model
      made before it, and the column is locked to the backend as the table is.
  O2  The same moment of a Take goes into one model once; a second model may
      take it too, and an upload's rows are never held to it.
PROVES   O1 -> test_a_model_keeps_its_setup_and_it_is_an_object
         O2 -> test_a_moment_goes_into_a_model_once
WHY      Migration a_model_keeps_its_setup (0517), applied twice in both
         rehearsal lanes after 0516 (the reapply is its idempotency check).
"""
from __future__ import annotations

import os
import uuid

import psycopg2
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="disposable confident-moment rehearsal only")


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


def _run(db, sql, args=()):
    with db.cursor() as cur:
        cur.execute(sql, args)


def _user(db):
    uid = str(uuid.uuid4())
    _run(db, "INSERT INTO auth.users(id,email) VALUES (%s,%s)", (uid, f"{uid}@example.com"))
    return uid


def _model(db, owner):
    return _one(db, "INSERT INTO public.ai_models(name, owner_id) VALUES ('Pitch Coach', %s) RETURNING id",
                (owner,))


def test_a_model_keeps_its_setup_and_it_is_an_object(db):
    model = _model(db, _user(db))
    assert _one(db, "SELECT setup::text FROM public.ai_models WHERE id = %s", (model,)) == "{}"
    _run(db, "UPDATE public.ai_models SET setup = %s::jsonb WHERE id = %s",
         ('{"problem": "Founders rush their pitch", "done": ["problem"]}', model))
    assert _one(db, "SELECT setup->>'problem' FROM public.ai_models WHERE id = %s", (model,)) == \
        "Founders rush their pitch"
    with pytest.raises(psycopg2.errors.CheckViolation):
        _run(db, "UPDATE public.ai_models SET setup = '[]'::jsonb WHERE id = %s", (model,))
    for role in ("anon", "authenticated"):
        assert _one(db, "SELECT has_column_privilege(%s, 'public.ai_models', 'setup', 'SELECT')", (role,)) is False


def test_a_moment_goes_into_a_model_once(db):
    speaker = _user(db)
    first, second = _model(db, _user(db)), _model(db, _user(db))
    add = ("INSERT INTO public.ai_model_examples(model_id, source, speaker_id, snippet_id) "
           "VALUES (%s, 'takes', %s, 'clip-1')")
    _run(db, add, (first, speaker))
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _run(db, add, (first, speaker))
    _run(db, add, (second, speaker))
    for _ in range(2):
        _run(db, "INSERT INTO public.ai_model_examples(model_id, source, snippet_id) VALUES (%s, 'upload', 'row-1')",
             (first,))
    assert _one(db, "SELECT count(*) FROM public.ai_model_examples WHERE snippet_id = 'clip-1'") == 2
