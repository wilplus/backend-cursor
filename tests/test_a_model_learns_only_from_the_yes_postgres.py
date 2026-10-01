"""Doors 3 and 4 on a disposable database (0406). Pins:
  * a pair is marked trained only once, only when released and releasable;
  * a run with an owner whose yes is gone appears in the withdrawn view;
  * the promote RPC accepts the three answer-surface keys and still refuses
    an unlisted one;
  * the two acoustic cues are seeded shadow; the three aliases exist;
  * every new table has RLS on and reaches no browser role.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

TABLES = ("fine_tune_runs", "fine_tune_run_owners", "evaluation_reports", "model_promotions")


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


def _row(db, sql, args=()):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, args)
        got = cur.fetchone()
        return dict(got) if got else None


def _exec(db, sql, args=()):
    with db.cursor() as cur:
        cur.execute(sql, args)


def _principal(db):
    return str(_one(db, "INSERT INTO public.owner_principals (id, user_id) VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id"))


def _pair(db, principal, *, releasable=True, released=True):
    release = None
    if released:
        release = str(_one(db, """
            INSERT INTO public.pair_releases (release_version, surface, week_start, item_count, storage_bucket,
                storage_key, manifest, manifest_sha256, file_sha256, signature, signing_key_id)
            VALUES ('pair-release-v1', 'praise_line', %s, 1, 'b', %s, '{}'::jsonb, repeat('a', 64), repeat('b', 64), 'sig', 'k1')
            RETURNING id""", (f"2001-01-{uuid.uuid4().int % 28 + 1:02d}", f"pair-releases/praise_line/{uuid.uuid4()}/pairs.jsonl")))
    return str(_one(db, """
        INSERT INTO public.feedback_pairs (surface, draft_text, final_text, coach_id, owner_principal_id,
                                           request_id, releasable, release_id, passage_text, consent_state)
        VALUES ('praise_line', 'the draft', 'the final', 'coach-1', %s, gen_random_uuid(), %s, %s, 'the passage', 'yes')
        RETURNING id""", (principal, releasable, release)))


def _run(db):
    return str(_one(db, """
        INSERT INTO public.fine_tune_runs (run_version, surface, base_model, item_count, train_count,
            validation_count, file_sha256, owners_sha256, openai_job_id, openai_file_id)
        VALUES ('fine-tune-run-v1', 'praise_line', 'gpt-4.1-mini', 1, 1, 0, repeat('c', 64), repeat('d', 64), 'job-1', 'file-1')
        RETURNING id"""))


def test_a_pair_trains_once_and_only_when_released_and_releasable(db):
    principal = _principal(db)
    good = _pair(db, principal)
    not_released = _pair(db, principal, released=False)
    withdrawn = _pair(db, principal, releasable=False)
    run = _run(db)
    assert _one(db, "SELECT public.mark_feedback_pairs_trained_v1(%s, %s::uuid[])", (run, [good])) == 1
    assert str(_one(db, "SELECT trained_run_id FROM public.feedback_pairs WHERE id = %s", (good,))) == run
    for bad in (good, not_released, withdrawn):
        with pytest.raises(psycopg2.Error) as refused:
            _one(db, "SELECT public.mark_feedback_pairs_trained_v1(%s, %s::uuid[])", (run, [bad]))
        assert "FINE_TUNE_PAIRS_NOT_TRAINABLE" in str(refused.value)
    with pytest.raises(psycopg2.Error) as unknown:
        _one(db, "SELECT public.mark_feedback_pairs_trained_v1(%s, %s::uuid[])", (str(uuid.uuid4()), [good]))
    assert "FINE_TUNE_RUN_UNKNOWN" in str(unknown.value)


def test_a_run_with_a_withdrawn_owner_is_listed(db):
    principal = _principal(db)   # no grant at all: the yes is absent
    run = _run(db)
    _exec(db, "INSERT INTO public.fine_tune_run_owners (run_id, owner_principal_id) VALUES (%s, %s)", (run, principal))
    got = _row(db, "SELECT run_id, status FROM public.fine_tune_runs_with_withdrawn_owner WHERE run_id = %s", (run,))
    assert got and got["status"] == "running"


def test_the_promote_rpc_accepts_the_answer_surface_keys(db):
    meta = json.dumps({"prompt_lock_sha256": hashlib.sha256(b"lock").hexdigest()})
    if _one(db, "SELECT to_regclass('public.runtime_config')") is None:
        pytest.skip("runtime_config absent on this rehearsal")
    out = _one(db, "SELECT public.promote_runtime_surface_model_v1(%s, %s, %s, %s::jsonb)",
               ("openai_surface_model_praise_line", "ft:x", "test", meta))
    assert out["value"] == "ft:x"
    with pytest.raises(psycopg2.Error) as refused:
        _one(db, "SELECT public.promote_runtime_surface_model_v1(%s, %s, %s, %s::jsonb)",
             ("openai_surface_model_moment_suggestion", "ft:x", "test", meta))
    assert "RUNTIME_MODEL_KEY_NOT_ENUMERATED" in str(refused.value)


def test_the_acoustic_cues_are_shadow_and_the_aliases_exist(db):
    for cue in ("low_volume", "flat_pitch"):
        row = _row(db, "SELECT status, detector_ref FROM public.speaking_error WHERE error_id = %s", (cue,))
        assert row == {"status": "shadow", "detector_ref": f"acoustic_cues:{cue}"}
    for alias, canonical in (("praise_line", "praise_generation"), ("clearer_version", "correction_generation"),
                             ("exercise_script", "coach_comment_generation")):
        row = _row(db, "SELECT learning_surface_id, canonical_writes_allowed FROM public.ml_learning_surface_aliases WHERE alias = %s", (alias,))
        assert row == {"learning_surface_id": canonical, "canonical_writes_allowed": True}


def test_every_new_table_has_rls_and_no_browser_grant(db):
    for table in TABLES:
        got = _row(db, "SELECT relrowsecurity FROM pg_class WHERE oid = %s::regclass", (f"public.{table}",))
        assert got and got["relrowsecurity"] is True, table
        grants = _row(db, "SELECT count(*) AS n FROM information_schema.role_table_grants "
                          "WHERE table_schema = 'public' AND table_name = %s AND grantee IN ('anon', 'authenticated')",
                      (table,))
        assert grants["n"] == 0, table
    anon = _one(db, "SELECT has_function_privilege('anon', 'public.mark_feedback_pairs_trained_v1(uuid, uuid[])', 'EXECUTE')")
    assert anon is False
