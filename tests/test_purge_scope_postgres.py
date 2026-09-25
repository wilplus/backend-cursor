"""0378 on a real database: the account-wide lock is narrowed, nothing else moves.

Run on the released rehearsal lane. Every write happens inside a transaction
that is rolled back.

  * `data_purge_requests.project_id` exists, and a project id is refused on
    any request that is not a project deletion (none can be one yet);
  * every installed function among the nineteen carries the narrowed
    predicate exactly once, and a D11 writer keeps its lock marker;
  * no installed function still holds the old, account-wide-for-anything
    predicate.
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
NARROWED = (
    "create_synthetic_exercise_authoring_draft_v1",
    "create_synthetic_exercise_practice_session_v1",
    "materialize_feedback_language_delivery_job_v1",
    "prepare_coach_inline_blind_batch_v1",
    "register_synthetic_service_no_match_request_v1",
    "require_coach_guidance_assignment_live_v1",
    "require_coach_guidance_authority_v1",
    "require_coach_guidance_media_live_v1",
    "require_coach_guidance_receipt_authority_v1",
    "require_exercise_practice_service_live_v1",
    "require_feedback_language_delivery_scan_authority_v1",
    "require_feedback_v3_service_membership_live_v1",
    "require_mlc3_service_principal_v1",
    "require_practice_source_live_v1",
    "require_synthetic_feedback_v3_membership_live_v1",
    "require_synthetic_root_content_live_v1",
    "resolve_coach_inline_blind_audio_read_v1",
    "resolve_confident_moment_source_playback_authority_v1",
    "resolve_mlc3_dual_purpose_receipt_v2",
)
_OPEN_PURGE = re.compile(
    r"data_purge_requests\s+(\w+)\s+WHERE[^;]*?\b\1\.state\s*<>\s*'done'",
    re.I | re.S)


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


def _definitions(cur):
    cur.execute("""
        SELECT p.proname, pg_get_functiondef(p.oid)
          FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public' AND p.prokind = 'f'
           AND pg_get_functiondef(p.oid) LIKE '%data_purge_requests%'""")
    return cur.fetchall()


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
    cur.execute("SELECT id FROM public.projects LIMIT 1")
    project = cur.fetchone()
    if project is None:
        pytest.skip("the lane holds no project row to point at")
    cur.execute("SAVEPOINT refused")
    with pytest.raises(psycopg2.Error) as refused:
        cur.execute("""
            INSERT INTO public.data_purge_requests (
                acquisition_principal_id, trigger_kind, idempotency_key,
                project_id)
            VALUES (%s, 'account_deletion', %s, %s)""",
            (principal, f"scope-{uuid.uuid4()}", project[0]))
    cur.execute("ROLLBACK TO SAVEPOINT refused")
    assert "data_purge_requests_project_scope_check" in str(refused.value)


def test_every_installed_function_is_narrowed_once(cur):
    installed = {name: body for name, body in _definitions(cur)}
    present = [name for name in NARROWED if name in installed]
    assert present, "the released lane installs none of the nineteen"
    for name in present:
        body = installed[name]
        assert body.count(MARKER) == 1, name
        assert re.search(
            r"\b(\w+)\.state\s*<>\s*'done'\s+AND\s+\1\.project_id IS NULL",
            body), name


def test_no_installed_function_keeps_the_old_lock(cur):
    offenders = []
    for name, body in _definitions(cur):
        for match in _OPEN_PURGE.finditer(body):
            tail = body[match.end():match.end() + 80]
            if f"{match.group(1)}.project_id IS NULL" not in tail:
                offenders.append(name)
    assert not offenders, offenders


def test_d11_writers_keep_their_lock_marker(cur):
    for name, body in _definitions(cur):
        if name in NARROWED and "pg_advisory_xact_lock" in body \
                and "mlc3-service-principal" in body:
            assert "D11 " in body, name
