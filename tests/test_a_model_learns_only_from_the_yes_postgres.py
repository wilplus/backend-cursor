"""
STORY    As a speaker, I want the model trained only on my coached pairs that
         I said yes to and that were released, and only once, so that my
         "no" is respected.
OUTCOME
  O1  A released pair that is still allowed is marked trained, once.
  O2  A pair that is not released, no longer allowed, or already trained
      is refused.
  O3  An unknown training run is refused.
PROVES   O1, O2, O3 -> test_a_pair_trains_once_and_only_when_released_and_releasable
WHY      Doors 3 and 4 (migration 0406).
"""
from __future__ import annotations

import os
import uuid
from datetime import date, timedelta

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


def _one(db, sql, args=()):
    with db.cursor() as cur:
        cur.execute(sql, args)
        row = cur.fetchone()
        return row[0] if row else None


def _principal(db):
    return str(_one(db, "INSERT INTO public.owner_principals (id, user_id) VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id"))


def _unique_week() -> str:
    """A release week no other test will draw. `pair_releases` holds one row
    per (surface, week_start); the old draw (one of 28 January days) made two
    releases in one run collide about one run in three."""
    return str(date(1900, 1, 1) + timedelta(days=uuid.uuid4().int % 60000))


def _pair(db, principal, *, releasable=True, released=True):
    release = None
    if released:
        release = str(_one(db, """
            INSERT INTO public.pair_releases (release_version, surface, week_start, item_count, storage_bucket,
                storage_key, manifest, manifest_sha256, file_sha256, signature, signing_key_id)
            VALUES ('pair-release-v1', 'praise_line', %s, 1, 'b', %s, '{}'::jsonb, repeat('a', 64), repeat('b', 64), 'sig', 'k1')
            RETURNING id""", (_unique_week(), f"pair-releases/praise_line/{uuid.uuid4()}/pairs.jsonl")))
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
