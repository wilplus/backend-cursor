"""Adversarial PostgreSQL checks for numbered, disabled D4 migration 0326.

The target must be a disposable local database cloned from the complete
release schema with the pending D4 migration applied. No provider call, real
media, production mutation, exposure, dataset or learning operation occurs.
"""

from __future__ import annotations

import hashlib
import os
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extras import Json, RealDictCursor

from tests import test_mlc3_first_client_service_postgres as d2
from tests.test_mlc3_dark_assignments_postgres import (
    assign,
    make_context,
)
from tests.test_mlc3_n1_source_pattern_postgres import profile, source_pattern

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


def rejected(db, statement: str, parameters=(), match: str | None = None):
    with db.cursor() as cursor:
        cursor.execute("SAVEPOINT expected_rejection")
        try:
            with pytest.raises(psycopg2.Error, match=match):
                cursor.execute(statement, parameters)
        finally:
            cursor.execute("ROLLBACK TO SAVEPOINT expected_rejection")
            cursor.execute("RESET ROLE")
            cursor.execute("RELEASE SAVEPOINT expected_rejection")


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


def _activate_ga(db, context):
    _activate_contract(db)
    _enable_coach_review_for_fixture(db, context)
    user_id = one(
        db,
        "SELECT user_id FROM owner_principals WHERE id=%s",
        (context["owner"],),
    )["user_id"]
    capacity_hash = one(
        db,
        "SELECT exercise_json_sha256_v1(%s::jsonb) AS value",
        (Json(CAPACITY),),
    )["value"]
    risk = one(
        db,
        "SELECT * FROM register_mlc3_activation_risk_decision_v1("
        "%s,%s,%s,%s,%s,%s,clock_timestamp()-interval '1 second',%s,%s)",
        (
            "4ee8cc5f1dda8cf5e727fefdaef12a1a96a85d9fcd01c74e8953564026bf1085",
            "a" * 40,
            "b" * 40,
            "Founder explicitly accepted a GA-first zero-user rollout.",
            capacity_hash,
            user_id,
            "founder-signed-test",
            hashlib.sha256(f"ga-risk:{user_id}".encode()).hexdigest(),
        ),
    )
    rollout = one(
        db,
        "SELECT * FROM register_mlc3_general_rollout_v2("
        "%s,%s,%s::jsonb,%s::jsonb,%s,clock_timestamp(),%s)",
        (
            context["policy"],
            risk["id"],
            Json(CAPACITY),
            Json({"language": "en-v1", "safety": "safety-v1"}),
            user_id,
            "d" * 64,
        ),
    )
    return user_id, rollout


def _general_offer_context(db):
    context = make_context(db)
    source = source_pattern(db, context, "confident")
    for version in context["versions"]:
        profile(db, version["id"], ["confident"])
    # The dark-assignment foundation deliberately rejects source rows whose
    # creating transaction has not committed yet.
    db.commit()
    assignment = assign(db, context)
    service_rpc(
        db, "freeze_exercise_n1_pattern_snapshot_v1",
        assignment["id"], source["id"], str(uuid4()),
    )
    user_id, rollout = _activate_ga(db, context)
    rows(
        db,
        "UPDATE processing_authorization_snapshots "
        "SET source_recording_id=%s WHERE id=%s",
        (context["recording"], context["snapshot"]),
    )
    rows(
        db,
        "UPDATE processing_recording_attempts "
        "SET authorization_snapshot_id=%s WHERE id=%s",
        (context["snapshot"], context["take"]),
    )
    rows(
        db,
        "UPDATE processing_audio_objects SET verified_at=clock_timestamp() "
        "WHERE id=%s",
        (context["object"],),
    )
    rows(
        db,
        "UPDATE snippets SET transcript=%s WHERE id=%s",
        (
            "We finish this phrase with steady deliberate pacing.",
            context["snippet"],
        ),
    )
    service_rpc(
        db, "ensure_mlc3_service_enrollment_v2",
        context["owner"], user_id, "general-flow-entry",
    )
    feedback = d2._service_membership(db, context)
    render = service_rpc(
        db, "ack_feedback_v3_service_render_v1",
        context["owner"], feedback["owner_user"],
        feedback["membership"]["id"], feedback["candidate_id"],
        feedback["exposure_id"], str(uuid4()),
        feedback["membership"]["content_identity_sha256"],
        one(db, "SELECT clock_timestamp() AS value")["value"],
        "d4-postgres", str(uuid4()),
    )
    response = service_rpc(
        db, "record_feedback_v3_service_response_v1",
        context["project"], context["take"], context["owner"],
        feedback["owner_user"], feedback["membership"]["id"],
        feedback["candidate_id"], feedback["exposure_id"], render["id"],
        "confident_yes", str(uuid4()),
    )
    prepared = service_json_rpc(
        db, "prepare_feedback_v3_service_context_v1",
        feedback["membership"]["id"], feedback["candidate_id"],
        context["owner"], str(uuid4()),
    )
    return context, user_id, rollout, feedback, response, prepared


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


# ---------------------------------------------------------------------------
#  THE CANDIDATE-SET WRITE, CALLED FOR REAL (0348).
#
#  PRODUCTION, 2026-09-21: with 0344's parenthesis in place the write got
#  past its lock for the first time and then raised 42702 on the first
#  `WHERE row.candidate_set_id = candidate_set_id` — a bare name that is both
#  the PL/pgSQL variable and a column of `row`. No test had ever CALLED this
#  function: the D2 module writes candidate_sets rows by hand, and its only
#  other mention is the privilege check. It lives here, not in D2, because
#  this clone carries the lineage tables and the D4-rewritten body that
#  production runs.
# ---------------------------------------------------------------------------

MIGRATIONS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")
