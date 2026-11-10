"""
STORY    As a person who starts or teaches an AI model, I want the models'
         tables to keep my model, my teaching and my answers safely, so that
         a public model outlives its owner's account, my own rows leave with
         mine, and no browser reaches any of it (N528, N563, N566).
OUTCOME
  O1  The five tables exist with RLS on, and no browser role is granted
      anything on them; the ring row ai_models sits at ring 6.
  O2  The tables refuse what the rules never allow: an added example with
      no adder, an example from Takes with no speaker, a known clip in the
      sealed exam, an unknown stage, the same answer twice.
  O3  Erasing the owner's account keeps their public model, with no owner;
      erasing a teacher's account takes their teaching and answers.
PROVES   O1 -> test_the_tables_are_locked_to_the_backend_and_the_ring_is_six
         O2 -> test_the_tables_refuse_what_the_rules_never_allow
         O3 -> test_an_owners_model_outlives_their_account_and_a_teachers_rows_go
WHY      Migration a_person_can_teach_and_start_ai_models (0516), applied
         twice in both rehearsal lanes (the reapply is its idempotency check).
"""
from __future__ import annotations

import os
import uuid

import psycopg2
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="disposable confident-moment rehearsal only")
TABLES = ("ai_models", "ai_model_teachers", "ai_model_examples", "ai_model_answers", "ai_model_invites")


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


def _model(db, owner, visibility="public"):
    return _one(db, "INSERT INTO public.ai_models(name, owner_id, visibility, status) "
                    "VALUES ('Speaking confidence', %s, %s, 'learning') RETURNING id", (owner, visibility))


def test_the_tables_are_locked_to_the_backend_and_the_ring_is_six(db):
    for table in TABLES:
        assert _one(db, "SELECT relrowsecurity FROM pg_class WHERE oid = %s::regclass",
                    (f"public.{table}",)) is True, table
        for role in ("anon", "authenticated"):
            assert _one(db, "SELECT has_table_privilege(%s, %s, 'SELECT')", (role, f"public.{table}")) is False
    assert _one(db, "SELECT min_ring FROM public.feature_rings WHERE feature = 'ai_models'") == 6


def test_the_tables_refuse_what_the_rules_never_allow(db):
    owner = _user(db)
    model = _model(db, owner)
    refused = [
        ("INSERT INTO public.ai_model_examples(model_id, source) VALUES (%s, 'teacher')", (model,)),
        ("INSERT INTO public.ai_model_examples(model_id, source) VALUES (%s, 'takes')", (model,)),
        ("INSERT INTO public.ai_model_examples(model_id, source, in_exam, known_answer) "
         "VALUES (%s, 'upload', true, 'Yes')", (model,)),
        ("UPDATE public.ai_models SET status = 'released' WHERE id = %s", (model,)),
    ]
    for sql, args in refused:
        with pytest.raises(psycopg2.errors.CheckViolation):
            _run(db, sql, args)
    example = _one(db, "INSERT INTO public.ai_model_examples(model_id, source) VALUES (%s, 'upload') "
                       "RETURNING id", (model,))
    _run(db, "INSERT INTO public.ai_model_answers(example_id, model_id, teacher_id, answer) "
             "VALUES (%s, %s, %s, 'Yes')", (example, model, owner))
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _run(db, "INSERT INTO public.ai_model_answers(example_id, model_id, teacher_id, answer) "
                 "VALUES (%s, %s, %s, 'No')", (example, model, owner))


def test_an_owners_model_outlives_their_account_and_a_teachers_rows_go(db):
    owner, teacher = _user(db), _user(db)
    model = _model(db, owner)
    _run(db, "INSERT INTO public.ai_model_teachers(model_id, user_id, role) VALUES (%s, %s, 'contributor')",
         (model, teacher))
    example = _one(db, "INSERT INTO public.ai_model_examples(model_id, source) VALUES (%s, 'upload') "
                       "RETURNING id", (model,))
    _run(db, "INSERT INTO public.ai_model_answers(example_id, model_id, teacher_id, answer) "
             "VALUES (%s, %s, %s, 'Yes')", (example, model, teacher))
    _run(db, "DELETE FROM auth.users WHERE id = %s", (owner,))
    assert _one(db, "SELECT owner_id FROM public.ai_models WHERE id = %s", (model,)) is None
    _run(db, "DELETE FROM auth.users WHERE id = %s", (teacher,))
    assert _one(db, "SELECT count(*) FROM public.ai_model_teachers WHERE model_id = %s", (model,)) == 0
    assert _one(db, "SELECT count(*) FROM public.ai_model_answers WHERE model_id = %s", (model,)) == 0
    assert _one(db, "SELECT count(*) FROM public.ai_models WHERE id = %s", (model,)) == 1
