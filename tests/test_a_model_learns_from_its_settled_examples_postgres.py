"""
STORY    As a person whose example taught a model, I want every version that
         learned from it found and marked to retrain when it is deleted or
         withdrawn, however it is deleted (PIPE-06, N615 item 3).
OUTCOME
  O1  The kept vectors are locked to the backend (RLS on, nothing for a
      browser role) and go with their example.
  O2  Deleting examples marks every version whose example_ids holds one of
      them, and no other version: one example, many in one statement, and
      many in a cascade (an erased speaker); the trigger is statement-level.
PROVES   O1 -> test_the_vectors_are_locked_to_the_backend_and_go_with_their_example
         O2 -> test_a_deleted_example_marks_every_version_that_learned_from_it
         O2 -> test_many_deleted_at_once_or_in_a_cascade_mark_their_versions
WHY      Migration a_model_learns_from_its_settled_examples (0522), applied
         twice in both rehearsal lanes (the reapply is its idempotency check).
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


def _model(db):
    owner = str(uuid.uuid4())
    _one(db, "INSERT INTO auth.users(id,email) VALUES (%s,%s) RETURNING id", (owner, f"{owner}@example.com"))
    return _one(db, "INSERT INTO public.ai_models(name, owner_id) VALUES ('Pitch coach', %s) RETURNING id",
                (owner,))


def _example(db, model, speaker=None):
    if speaker:
        return _one(db, "INSERT INTO public.ai_model_examples(model_id, source, speaker_id, content) "
                        "VALUES (%s, 'takes', %s, '{\"text\": \"hello\"}') RETURNING id", (model, speaker))
    return _one(db, "INSERT INTO public.ai_model_examples(model_id, source, content) "
                    "VALUES (%s, 'business', '{\"text\": \"hello\"}') RETURNING id", (model,))


def _person(db):
    uid = str(uuid.uuid4())
    _one(db, "INSERT INTO auth.users(id,email) VALUES (%s,%s) RETURNING id", (uid, f"{uid}@example.com"))
    return uid


def test_the_vectors_are_locked_to_the_backend_and_go_with_their_example(db):
    assert _one(db, "SELECT relrowsecurity FROM pg_class WHERE oid = 'public.ai_model_example_vectors'::regclass")
    for role in ("anon", "authenticated"):
        assert _one(db, "SELECT has_table_privilege(%s, 'public.ai_model_example_vectors', 'SELECT')",
                    (role,)) is False
    model = _model(db)
    ex = _example(db, model)
    _one(db, "INSERT INTO public.ai_model_example_vectors(example_id, reader, vector) "
             "VALUES (%s, 'text-embedding-3-small', ARRAY[0.1, 0.2]) RETURNING example_id", (ex,))
    _one(db, "DELETE FROM public.ai_model_examples WHERE id = %s RETURNING id", (ex,))
    assert _one(db, "SELECT count(*) FROM public.ai_model_example_vectors WHERE example_id = %s", (ex,)) == 0


def test_a_deleted_example_marks_every_version_that_learned_from_it(db):
    model = _model(db)
    a, b = _example(db, model), _example(db, model)
    v1 = _one(db, "INSERT INTO public.ai_model_versions(model_id, number, example_ids) "
                  "VALUES (%s, 1, ARRAY[%s, %s]::uuid[]) RETURNING id", (model, a, b))
    v2 = _one(db, "INSERT INTO public.ai_model_versions(model_id, number, example_ids) "
                  "VALUES (%s, 2, ARRAY[%s]::uuid[]) RETURNING id", (model, b))
    _one(db, "DELETE FROM public.ai_model_examples WHERE id = %s RETURNING id", (a,))
    assert _one(db, "SELECT retrain_at IS NOT NULL FROM public.ai_model_versions WHERE id = %s", (v1,)) is True
    assert _one(db, "SELECT retrain_at IS NULL FROM public.ai_model_versions WHERE id = %s", (v2,)) is True


def test_many_deleted_at_once_or_in_a_cascade_mark_their_versions(db):
    assert _one(db, "SELECT (tgtype & 1) = 0 FROM pg_trigger WHERE tgname = 'ai_model_examples_mark_retrain'")
    model = _model(db)
    many = [_example(db, model) for _ in range(30)]
    speaker = _person(db)
    theirs = [_example(db, model, speaker) for _ in range(5)]
    kept = _example(db, model)
    v_many = _one(db, "INSERT INTO public.ai_model_versions(model_id, number, example_ids) "
                      "VALUES (%s, 1, %s::uuid[]) RETURNING id", (model, many + [kept]))
    v_theirs = _one(db, "INSERT INTO public.ai_model_versions(model_id, number, example_ids) "
                        "VALUES (%s, 2, %s::uuid[]) RETURNING id", (model, theirs))
    v_kept = _one(db, "INSERT INTO public.ai_model_versions(model_id, number, example_ids) "
                      "VALUES (%s, 3, ARRAY[%s]::uuid[]) RETURNING id", (model, kept))
    _one(db, "DELETE FROM public.ai_model_examples WHERE id = ANY(%s::uuid[]) RETURNING id", (many,))
    assert _one(db, "SELECT count(*) FROM public.ai_model_examples WHERE id = ANY(%s::uuid[])", (many,)) == 0
    _one(db, "DELETE FROM auth.users WHERE id = %s RETURNING id", (speaker,))   # the cascade
    assert _one(db, "SELECT count(*) FROM public.ai_model_examples WHERE id = ANY(%s::uuid[])", (theirs,)) == 0
    for version, marked in ((v_many, True), (v_theirs, True), (v_kept, False)):
        assert _one(db, "SELECT retrain_at IS NOT NULL FROM public.ai_model_versions WHERE id = %s",
                    (version,)) is marked
