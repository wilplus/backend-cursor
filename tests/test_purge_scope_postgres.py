"""
STORY    As a speaker deleting one project, I want only account-wide
         deletions to pause my services, so that my other projects keep
         working.
OUTCOME
  O1  data_purge_requests.project_id exists and is refused on any request
      that is not a project deletion.
  O2  All nineteen functions are installed and each carries the narrowed
      predicate exactly once, and none keeps the old account-wide one.
PROVES   O1 -> test_a_project_id_only_belongs_to_a_project_deletion
         O2 -> test_every_lock_check_counts_only_account_wide_purges
WHY      0378 (a_project_deletion_pauses_only_its_project.sql). Runs on the
         released rehearsal lane; every write is rolled back.
"""
from __future__ import annotations

import os
import re
import uuid

import psycopg2
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)


MARKER = "/* 0378: account-wide purges only */"
NINETEEN = {
    "create_synthetic_exercise_authoring_draft_v1": "purge",
    "create_synthetic_exercise_practice_session_v1": "purge",
    "materialize_feedback_language_delivery_job_v1": "p",
    "prepare_coach_inline_blind_batch_v1": "purge",
    "register_synthetic_service_no_match_request_v1": "purge",
    "require_coach_guidance_assignment_live_v1": "purge",
    "require_coach_guidance_authority_v1": "purge",
    "require_coach_guidance_media_live_v1": "purge",
    "require_coach_guidance_receipt_authority_v1": "purge",
    "require_exercise_practice_service_live_v1": "purge",
    "require_feedback_language_delivery_scan_authority_v1": "p",
    "require_feedback_v3_service_membership_live_v1": "purge",
    "require_mlc3_service_principal_v1": "purge",
    "require_practice_source_live_v1": "purge",
    "require_synthetic_feedback_v3_membership_live_v1": "purge",
    "require_synthetic_root_content_live_v1": "purge",
    "resolve_coach_inline_blind_audio_read_v1": "purge",
    "resolve_confident_moment_source_playback_authority_v1": "p",
    "resolve_mlc3_dual_purpose_receipt_v2": "purge",
}


@pytest.fixture
def cur():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cursor:
            yield cursor
    finally:
        conn.rollback()
        conn.close()


def test_a_project_id_only_belongs_to_a_project_deletion(cur):
    cur.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = 'data_purge_requests'
           AND column_name = 'project_id'""")
    assert cur.fetchone()
    cur.execute("""
        INSERT INTO public.owner_principals (id, user_id)
        VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id""")
    principal = cur.fetchone()[0]
    cur.execute("SAVEPOINT refused")
    with pytest.raises(psycopg2.Error) as refused:
        cur.execute("""
            INSERT INTO public.data_purge_requests (
                acquisition_principal_id, trigger_kind, idempotency_key,
                project_id)
            VALUES (%s, 'account_deletion', %s, %s)""",
            (principal, f"scope-{uuid.uuid4()}", str(uuid.uuid4())))
    cur.execute("ROLLBACK TO SAVEPOINT refused")
    assert "data_purge_requests_project_scope_check" in str(refused.value)


def test_every_lock_check_counts_only_account_wide_purges(cur):
    cur.execute("""
        SELECT p.proname, pg_get_functiondef(p.oid)
          FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public' AND p.proname = ANY(%s)""",
        (list(NINETEEN),))
    carriers = [(name, body) for name, body in cur.fetchall()
                if "data_purge_requests" in body]
    assert {name for name, _ in carriers} == set(NINETEEN)
    for name, body in carriers:
        alias = NINETEEN[name]
        assert body.count(MARKER) == 1, name
        old = re.compile(rf"\b{alias}\.state\s*<>\s*'done'(?!\s+AND\s+{alias}\.project_id IS NULL)")
        assert not old.search(body), f"{name} still pauses on a project purge"
