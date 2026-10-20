"""
STORY    As the founder, I want the general-user service tables locked to
         browser roles and the candidate-set write repaired on the body
         production runs, so that rollout cannot leak data or crash.
OUTCOME
  O1  Every D4 table forces RLS, authenticated has no write, and no rollout
      revision is dataset-eligible.
  O2  On the D4-rewritten candidate-set writer, the 0344 lock repair and the
      0348 variable-conflict pragma both apply, keep D4's access guard, and
      re-apply as a no-op.
PROVES   O1 -> test_permissions_rls_and_learning_boundaries_are_closed
         O2 -> test_the_candidate_set_writer_repairs_land_on_the_d4_body
WHY      Production 42702, 2026-09-21: the writer had never been called.
         O2 reads the function definition from the catalog; it does not call
         the writer with a bundle (that needs the full V3 inventory harness).
"""
from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

DSN = os.environ.get("MLC3_GENERAL_USER_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="disposable D4 rehearsal only")

CAPACITY = {
    "max_concurrent_enrollments": 20,
    "max_new_enrollments_per_hour": 50,
    "max_concurrent_uploads": 10,
    "max_uploads_per_principal": 2,
    "max_outstanding_assignments": 500,
    "max_assignments_per_coach": 100,
    "max_queue_age_hours": 72,
    "max_media_bytes_per_day": 10737418240,
    "max_unresolved_recoveries": 25,
    "max_recovery_age_minutes": 15,
}
D4_TABLES = {
    "mlc3_service_cohort_sets",
    "mlc3_service_cohort_members",
    "mlc3_service_activation_risk_decisions",
    "mlc3_service_rollout_revisions",
    "mlc3_service_enrollment_revisions",
    "mlc3_service_access_events",
    "mlc3_speaker_acquisition_revisions",
    "mlc3_self_speaker_assertions",
    "mlc3_target_speaker_bindings",
    "mlc3_comparison_speaker_eligibility_revisions",
    "mlc3_service_backpressure_events",
}


@pytest.fixture
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_ga_"):
        raise RuntimeError("Refusing a non-disposable database")
    if not parsed.get("host", "").startswith(
        ("/tmp/willab-", "/private/tmp/willab-")
    ):
        raise RuntimeError("Refusing a non-local rehearsal host")
    template_name = parsed["dbname"]
    clone_name = f"willab_ga_case_{uuid4().hex}"
    maintenance_args = {**parsed, "dbname": "postgres"}
    maintenance = psycopg2.connect(**maintenance_args)
    maintenance.autocommit = True
    with maintenance.cursor() as cursor:
        cursor.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(clone_name), sql.Identifier(template_name),
            )
        )
    case_args = {**parsed, "dbname": clone_name}
    connection = psycopg2.connect(**case_args)
    connection.autocommit = False
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()
        with maintenance.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=%s AND pid<>pg_backend_pid()",
                (clone_name,),
            )
            cursor.execute(
                sql.SQL("DROP DATABASE {}").format(sql.Identifier(clone_name))
            )
        maintenance.close()


def rows(db, statement: str, parameters=()):
    with db.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(statement, parameters)
        return cursor.fetchall() if cursor.description else []


def one(db, statement: str, parameters=()):
    result = rows(db, statement, parameters)
    assert len(result) == 1
    return result[0]


def service_rpc(db, name: str, *arguments):
    with db.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SET ROLE service_role")
        try:
            cursor.execute(
                f"SELECT * FROM public.{name}({','.join(['%s'] * len(arguments))})",
                arguments,
            )
            result = cursor.fetchone()
        finally:
            cursor.execute("RESET ROLE")
    return dict(result) if result else None


def service_json_rpc(db, name: str, *arguments):
    with db.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SET ROLE service_role")
        try:
            cursor.execute(
                f"SELECT public.{name}({','.join(['%s'] * len(arguments))}) "
                "AS value",
                arguments,
            )
            result = cursor.fetchone()["value"]
        finally:
            cursor.execute("RESET ROLE")
    return result


def _activate_contract(db):
    rows(
        db,
        "UPDATE mlc3_service_contracts SET state='active',"
        "active_from=clock_timestamp()-interval '1 second',"
        "retired_at=NULL,practice_bucket='practice-r2',"
        "coach_video_bucket='coach-r2' "
        "WHERE contract_version='mlc3-first-client-service-v1'",
    )


def _enable_coach_review_for_fixture(db, context):
    columns = {
        row["column_name"]
        for row in rows(
            db,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' "
            "AND table_name='processing_purpose_registry'",
        )
    }
    if "phase" in columns:
        rows(
            db,
            "INSERT INTO processing_purpose_registry("
            "id,phase,operational,authorizes_processing,capability_version,"
            "reviewed_at,retention_control_version,deletion_control_version,"
            "rights_control_version) VALUES ("
            "'coach_review','phase1',true,true,'coach-review-v1',"
            "clock_timestamp(),'retention-v1','deletion-v1','rights-v1') "
            "ON CONFLICT (id) DO UPDATE SET operational=true,"
            "authorizes_processing=true,capability_version='coach-review-v1',"
            "reviewed_at=clock_timestamp(),"
            "retention_control_version='retention-v1',"
            "deletion_control_version='deletion-v1',"
            "rights_control_version='rights-v1'",
        )
    else:
        rows(
            db,
            "INSERT INTO processing_purpose_registry("
            "id,operational,authorizes_processing) "
            "VALUES ('coach_review',true,true) ON CONFLICT (id) "
            "DO UPDATE SET operational=true,authorizes_processing=true",
        )
    rows(
        db,
        "INSERT INTO processing_policy_purposes(policy_id,purpose_id) "
        "VALUES (%s,'coach_review') ON CONFLICT DO NOTHING",
        (context["policy"],),
    )
    rows(
        db,
        "INSERT INTO processing_authorization_receipt_purposes("
        "receipt_id,purpose_id) VALUES (%s,'coach_review') "
        "ON CONFLICT DO NOTHING",
        (context["receipt"],),
    )


def test_permissions_rls_and_learning_boundaries_are_closed(db):
    tables = rows(
        db,
        "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND left(c.relname,5)='mlc3_' "
        "AND c.relkind='r'",
    )
    d4_tables = [row for row in tables if row["relname"] in D4_TABLES]
    assert {row["relname"] for row in d4_tables} == D4_TABLES
    assert all(row["relrowsecurity"] and row["relforcerowsecurity"] for row in d4_tables)
    for table in d4_tables:
        assert one(
            db,
            "SELECT has_table_privilege('authenticated',%s,'INSERT,UPDATE,DELETE') AS value",
            (f"public.{table['relname']}",),
        )["value"] is False
    assert one(
        db,
        "SELECT count(*) AS n FROM mlc3_service_rollout_revisions "
        "WHERE dataset_eligible",
    )["n"] == 0


MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
WRITER = "public.record_feedback_v3_service_candidate_set_v1(uuid,uuid,uuid,jsonb)"


def _writer_definition(db) -> str:
    return one(db, "SELECT pg_get_functiondef(to_regprocedure(%s)) AS value",
               (WRITER,))["value"]


def _apply(db, name: str) -> None:
    with db.cursor() as cursor:
        cursor.execute((MIGRATIONS / name).read_text())


def test_the_candidate_set_writer_repairs_land_on_the_d4_body(db):
    # The template is cut at 0326, before both repairs: the body production
    # ran when 22P02 (0344) and then 42702 (0348) fired.
    before = _writer_definition(db)
    assert "#variable_conflict use_variable" not in before
    for name in ("fix_candidate_set_advisory_lock_precedence.sql",
                 "the_candidate_set_writer_resolves_its_own_variable.sql"):
        _apply(db, name)
    repaired = _writer_definition(db)
    assert "#variable_conflict use_variable" in repaired
    assert "(p_bundle->>'idempotency_key'), 0" in repaired
    # The in-place repair kept D4's guard rather than reviving D2's text.
    assert "require_mlc3_service_access_v2" in repaired
    for name in ("fix_candidate_set_advisory_lock_precedence.sql",
                 "the_candidate_set_writer_resolves_its_own_variable.sql"):
        _apply(db, name)
    assert _writer_definition(db) == repaired
