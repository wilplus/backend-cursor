"""Adversarial PostgreSQL checks for numbered, disabled D4 migration 0326.

The target must be a disposable local database cloned from the complete
release schema with the pending D4 migration applied. No provider call, real
media, production mutation, exposure, dataset or learning operation occurs.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json, RealDictCursor
import pytest

from tests import test_mlc3_first_client_service_postgres as d2
from tests.test_mlc3_dark_assignments_postgres import (
    assign,
    make_context,
    wait_for_lock,
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
RUNTIME_TABLES = {
    "coach_guidance_attachment_versions", "coach_guidance_attachments",
    "coach_guidance_independent_media_reviews",
    "coach_guidance_lifecycle_events", "coach_guidance_media_bindings",
    "coach_guidance_media_validity_events", "coach_guidance_reveal_accesses",
    "coach_guidance_reveal_grant_judgments", "coach_guidance_reveal_grants",
    "coach_guidance_review_batches", "coach_guidance_review_frame_items",
    "coach_guidance_review_frames", "coach_guidance_upload_events",
    "coach_guidance_upload_permits", "coach_guidance_upload_recoveries",
    "coach_inline_context_assessments", "coach_inline_exercise_drafts",
    "coach_inline_exercise_eligibility_reviews", "coach_inline_source_roles",
    "exercise_practice_attempts", "exercise_practice_events",
    "exercise_practice_measurement_revisions",
    "exercise_practice_selection_revisions", "exercise_practice_sessions",
    "exercise_practice_transcription_runs",
    "exercise_practice_upload_recoveries",
    "exercise_practice_validity_assessments",
    "exercise_service_acquisition_receipts",
    "exercise_service_blind_reveal_accesses",
    "exercise_service_blind_reveal_grants",
    "exercise_service_blind_review_sets",
    "exercise_service_confidence_assignments",
    "exercise_service_confidence_judgments",
    "exercise_service_confidence_render_receipts",
    "exercise_service_offer_candidates", "exercise_service_offer_events",
    "exercise_service_offers", "exercise_service_requests",
    "feedback_v3_membership_items", "feedback_v3_memberships",
    "feedback_v3_owner_responses", "feedback_v3_service_render_receipts",
    "feedback_v3_service_response_bindings",
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


def internal_json_rpc(db, name: str, *arguments):
    return one(
        db,
        f"SELECT public.{name}({','.join(['%s'] * len(arguments))}) AS value",
        arguments,
    )["value"]


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
            "c" * 64,
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


def test_disabled_seed_cannot_enroll_or_serve(db):
    state = one(
        db,
        "SELECT rollout_state,serves_user,dataset_eligible "
        "FROM mlc3_service_rollout_revisions "
        "ORDER BY revision_number DESC LIMIT 1",
    )
    assert state == {
        "rollout_state": "disabled",
        "serves_user": False,
        "dataset_eligible": False,
    }
    rejected(
        db,
        "SELECT ensure_mlc3_service_enrollment_v2(%s,%s,%s)",
        (str(uuid4()), str(uuid4()), "disabled"),
        "MLC3_ROLLOUT_NOT_ACTIVE",
    )
    assert one(db, "SELECT count(*) AS n FROM mlc3_service_enrollment_revisions")[
        "n"
    ] == 0


def test_exact_dual_purpose_ga_enrollment_and_replay(db):
    context = make_context(db)
    user_id, rollout = _activate_ga(db, context)
    enrollment = service_rpc(
        db,
        "ensure_mlc3_service_enrollment_v2",
        context["owner"],
        user_id,
        "first-entry",
    )
    replay = service_rpc(
        db,
        "ensure_mlc3_service_enrollment_v2",
        context["owner"],
        user_id,
        "later-entry",
    )
    assert enrollment and replay
    assert replay["id"] == enrollment["id"]
    assert enrollment["operation_mode"] == "general_service"
    assert enrollment["rollout_revision_id"] == rollout["id"]
    assert enrollment["dataset_eligible"] is False
    assert one(
        db,
        "SELECT count(*) AS n FROM mlc3_service_enrollment_revisions "
        "WHERE acquisition_principal_id=%s",
        (context["owner"],),
    )["n"] == 1


def test_concurrent_first_entry_creates_one_enrollment_revision(db):
    context = make_context(db)
    user_id, rollout = _activate_ga(db, context)
    db.commit()

    def enroll(key: str):
        connection = psycopg2.connect(db.dsn)
        connection.autocommit = False
        try:
            result = service_rpc(
                connection, "ensure_mlc3_service_enrollment_v2",
                context["owner"], user_id, key,
            )
            connection.commit()
            return result
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(enroll, "concurrent-entry-a")
        second_future = pool.submit(enroll, "concurrent-entry-b")
        first = first_future.result(timeout=10)
        second = second_future.result(timeout=10)
    assert first and second and first["id"] == second["id"]
    assert first["rollout_revision_id"] == rollout["id"]
    assert one(
        db,
        "SELECT count(*) AS n FROM mlc3_service_enrollment_revisions "
        "WHERE acquisition_principal_id=%s",
        (context["owner"],),
    )["n"] == 1


def test_split_or_missing_purpose_fails_closed(db):
    context = make_context(db)
    _activate_contract(db)
    user_id = one(
        db,
        "SELECT user_id FROM owner_principals WHERE id=%s",
        (context["owner"],),
    )["user_id"]
    rejected(
        db,
        "SELECT resolve_mlc3_dual_purpose_receipt_v2(%s)",
        (context["owner"],),
        "MLC3_DUAL_PURPOSE_AUTHORITY_REQUIRED",
    )
    assert user_id


def test_rollout_requires_the_exact_authorization_policy(db):
    context = make_context(db)
    user_id, rollout = _activate_ga(db, context)
    foreign_policy = make_context(db)
    _enable_coach_review_for_fixture(db, foreign_policy)
    rows(
        db,
        "UPDATE processing_authorization_receipts SET policy_id=%s "
        "WHERE id=%s",
        (foreign_policy["policy"], context["receipt"]),
    )
    rejected(
        db,
        "SET ROLE service_role; SELECT ensure_mlc3_service_enrollment_v2("
        "%s,%s,%s)",
        (context["owner"], user_id, "wrong-rollout-policy"),
        "MLC3_ROLLOUT_POLICY_AUTHORITY_MISMATCH",
    )
    assert rollout["required_policy_id"] == context["policy"]
    assert one(
        db,
        "SELECT count(*) AS n FROM mlc3_service_enrollment_revisions "
        "WHERE acquisition_principal_id=%s",
        (context["owner"],),
    )["n"] == 0


def test_legacy_allowlist_does_not_replace_rollout_enrollment(db):
    context = make_context(db)
    _activate_contract(db)
    rows(
        db,
        "INSERT INTO mlc3_service_principal_allowlist("
        "acquisition_principal_id,contract_version,state,"
        "approved_by_principal_id,approval_evidence_sha256,idempotency_key) "
        "VALUES (%s,'mlc3-first-client-service-v1','active',%s,%s,%s)",
        (context["owner"], context["reviewer"], "e" * 64, str(uuid4())),
    )
    user_id = one(
        db,
        "SELECT user_id FROM owner_principals WHERE id=%s",
        (context["owner"],),
    )["user_id"]
    rejected(
        db,
        "SET ROLE service_role; SELECT ensure_mlc3_service_enrollment_v2("
        "%s,%s,%s)",
        (context["owner"], user_id, "legacy-only"),
        "MLC3_ROLLOUT_NOT_ACTIVE",
    )


def test_runtime_tables_require_exact_rollout_lineage_and_hash(db):
    registered = rows(
        db,
        "SELECT table_name FROM information_schema.columns "
        "WHERE table_schema='public' AND column_name='operation_mode' "
        "AND left(table_name,5) <> 'mlc3_' "
        "AND EXISTS (SELECT 1 FROM information_schema.columns principal "
        "WHERE principal.table_schema='public' "
        "AND principal.table_name=columns.table_name "
        "AND principal.column_name='acquisition_principal_id')",
    )
    assert len(registered) >= 25
    for item in registered:
        names = {
            row["column_name"]
            for row in rows(
                db,
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=%s",
                (item["table_name"],),
            )
        }
        assert {
            "rollout_revision_id",
            "enrollment_revision_id",
            "access_resolver_version",
            "rollout_identity_sha256",
        } <= names


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


def test_complete_runtime_registry_is_rollout_bound_rls_and_rpc_only(db):
    present = {
        row["table_name"]
        for row in rows(
            db,
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=ANY(%s)",
            (list(RUNTIME_TABLES),),
        )
    }
    assert present == RUNTIME_TABLES
    for table in sorted(RUNTIME_TABLES):
        columns = {
            row["column_name"]
            for row in rows(
                db,
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=%s",
                (table,),
            )
        }
        assert {
            "rollout_revision_id", "enrollment_revision_id",
            "access_resolver_version", "rollout_identity_sha256",
        } <= columns
        relation = one(
            db,
            "SELECT relrowsecurity,relforcerowsecurity,"
            "has_table_privilege('authenticated',c.oid,'INSERT,UPDATE,DELETE') "
            "AS client_write,"
            "has_table_privilege('service_role',c.oid,'INSERT,UPDATE,DELETE') "
            "AS service_write FROM pg_class c JOIN pg_namespace n "
            "ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname=%s",
            (table,),
        )
        assert relation == {
            "relrowsecurity": True,
            "relforcerowsecurity": False,
            "client_write": False,
            "service_write": False,
        }
        assert one(
            db,
            "SELECT count(*) AS n FROM pg_trigger trigger_row "
            "WHERE trigger_row.tgrelid=%s::regclass "
            "AND trigger_row.tgname='a_mlc3_rollout_lineage_v2' "
            "AND NOT trigger_row.tgisinternal",
            (f"public.{table}",),
        )["n"] == 1


@pytest.mark.parametrize(
    ("signature", "service_allowed"),
    (
        ("ensure_mlc3_service_enrollment_v2(uuid,uuid,text)", True),
        ("require_mlc3_service_access_v2(uuid,uuid,uuid)", True),
        ("record_mlc3_feedback_self_speaker_target_v1(uuid,uuid,uuid,uuid,text)", True),
        ("confirm_mlc3_practice_speaker_and_pair_v1(uuid,uuid,uuid,text)", True),
        ("reserve_exercise_practice_service_upload_v2(uuid,uuid,uuid,text,bigint,text,text,text,integer)", True),
        ("get_mlc3_general_service_monitor_v1()", True),
        ("require_mlc3_service_principal_v1(uuid)", False),
        ("record_mlc3_self_speaker_target_v1(uuid,uuid,uuid,uuid,uuid,text)", False),
        ("record_mlc3_practice_self_speaker_target_v1(uuid,uuid,uuid,text)", False),
        ("reserve_exercise_practice_service_upload_v1(uuid,uuid,integer,uuid,text,bigint,text,text,text,integer)", False),
        ("register_mlc3_general_rollout_v2(uuid,uuid,jsonb,jsonb,uuid,timestamptz,text)", False),
        ("assign_synthetic_exercise_pair_v1(uuid,uuid,text,text)", False),
        ("submit_synthetic_exercise_pair_judgment_v1(uuid,uuid,text,text)", False),
        ("halt_mlc3_service_rollout_v1(text,text)", True),
    ),
)
def test_exact_rpc_permissions(db, signature, service_allowed):
    privilege = one(
        db,
        "SELECT has_function_privilege('service_role',%s,'EXECUTE') AS service,"
        "has_function_privilege('authenticated',%s,'EXECUTE') AS client,"
        "has_function_privilege('anon',%s,'EXECUTE') AS anon",
        (
            f"public.{signature}", f"public.{signature}",
            f"public.{signature}",
        ),
    )
    assert privilege == {
        "service": service_allowed, "client": False, "anon": False,
    }


def test_explicit_self_speaker_action_creates_one_pseudonymous_target(db):
    context = make_context(db)
    user_id, _rollout = _activate_ga(db, context)
    service_rpc(
        db,
        "ensure_mlc3_service_enrollment_v2",
        context["owner"],
        user_id,
        "speaker-enrollment",
    )
    rows(
        db,
        "UPDATE snippets SET transcript=%s WHERE id=%s",
        ("I am speaking in this exact practice phrase.", context["snippet"]),
    )
    rows(
        db,
        "UPDATE processing_audio_objects SET verified_at=clock_timestamp() "
        "WHERE id=%s",
        (context["object"],),
    )
    first = internal_json_rpc(
        db,
        "record_mlc3_self_speaker_target_v1",
        context["owner"],
        user_id,
        context["take"],
        context["object"],
        context["snippet"],
        "self-speaker-one",
    )
    replay = internal_json_rpc(
        db,
        "record_mlc3_self_speaker_target_v1",
        context["owner"],
        user_id,
        context["take"],
        context["object"],
        context["snippet"],
        "self-speaker-one",
    )
    assert first["target_binding_id"] == replay["target_binding_id"]
    assert first["speaker_id"] == replay["speaker_id"]
    assert first["replayed"] is False
    assert replay["replayed"] is True
    assert one(
        db,
        "SELECT count(*) AS n FROM mlc3_self_speaker_assertions "
        "WHERE acquisition_principal_id=%s",
        (context["owner"],),
    )["n"] == 1
    assert one(
        db,
        "SELECT dataset_eligible FROM mlc3_target_speaker_bindings "
        "WHERE id=%s",
        (first["target_binding_id"],),
    )["dataset_eligible"] is False

    practice_attempt = str(uuid4())
    practice_recording = str(uuid4())
    practice_audio = str(uuid4())
    practice_clip = str(uuid4())
    rows(
        db,
        "INSERT INTO processing_recording_attempts("
        "id,acquisition_principal_id,project_id,recording_id,status,"
        "authorization_snapshot_id,upload_idempotency_key) "
        "VALUES (%s,%s,%s,%s,'completed',%s,%s)",
        (
            practice_attempt,
            context["owner"],
            context["project"],
            practice_recording,
            context["snapshot"],
            "practice-speaker-upload",
        ),
    )
    rows(
        db,
        "INSERT INTO processing_audio_objects("
        "id,acquisition_principal_id,recording_attempt_id,storage_provider,"
        "bucket,object_key,byte_size,content_type,exact_bytes_sha256,"
        "verification_method,deleted_at,verified_at) VALUES ("
        "%s,%s,%s,'r2','practice-r2',%s,2048,'audio/wav',%s,"
        "'read_after_write_sha256',NULL,clock_timestamp())",
        (
            practice_audio,
            context["owner"],
            practice_attempt,
            str(uuid4()),
            "f" * 64,
        ),
    )
    rows(
        db,
        "INSERT INTO snippets(id,session_id,recording_id,start_offset_ms,"
        "duration_ms,transcript) VALUES (%s,NULL,%s,0,2200,%s)",
        (
            practice_clip,
            practice_recording,
            "I am repeating the same phrase after the exercise.",
        ),
    )
    practice_target = internal_json_rpc(
        db,
        "record_mlc3_self_speaker_target_v1",
        context["owner"],
        user_id,
        practice_attempt,
        practice_audio,
        practice_clip,
        "self-speaker-practice",
    )
    assert practice_target["speaker_id"] == first["speaker_id"]
    eligibility = one(
        db,
        "SELECT * FROM freeze_mlc3_same_speaker_eligibility_v1("
        "%s,%s,%s,%s)",
        (
            context["owner"],
            context["take"],
            practice_attempt,
            "same-speaker-pair",
        ),
    )
    assert eligibility["eligibility_result"] == "same_speaker_eligible"
    assert eligibility["source_speaker_id"] == eligibility[
        "practice_speaker_id"
    ]
    assert eligibility["dataset_eligible"] is False

    different_speaker = str(uuid4())
    rows(db, "INSERT INTO ml_speakers(id) VALUES (%s)", (different_speaker,))
    acquisition_revision = str(uuid4())
    rows(
        db,
        "INSERT INTO mlc3_speaker_acquisition_revisions("
        "id,acquisition_principal_id,recording_attempt_id,audio_object_id,"
        "revision_number,supersedes_revision_id,speaker_count_status,"
        "speaker_identity_status,speaker_id,count_policy_version,"
        "identity_policy_version,evidence_source,audio_sha256,binding_sha256) "
        "SELECT %s,acquisition_principal_id,recording_attempt_id,audio_object_id,"
        "2,id,'single','resolved',%s,'reviewed-count-v1','reviewed-identity-v1',"
        "'reviewed_segmentation',audio_sha256,%s FROM "
        "mlc3_speaker_acquisition_revisions WHERE recording_attempt_id=%s "
        "ORDER BY revision_number DESC LIMIT 1",
        (
            acquisition_revision,
            different_speaker,
            uuid4().hex * 2,
            practice_attempt,
        ),
    )
    rows(
        db,
        "INSERT INTO mlc3_target_speaker_bindings("
        "acquisition_principal_id,recording_attempt_id,audio_object_id,"
        "acquisition_revision_id,speaker_id,reviewed_segmentation_id,"
        "revision_number,supersedes_binding_id,binding_state,clip_id,"
        "target_start_ms,target_duration_ms,transcript_span,transcript_sha256,"
        "audio_sha256,segmentation_policy_version,segmentation_run_version,"
        "target_binding_sha256) SELECT acquisition_principal_id,"
        "recording_attempt_id,audio_object_id,%s,%s,%s,2,id,'active',clip_id,"
        "target_start_ms,target_duration_ms,transcript_span,transcript_sha256,"
        "audio_sha256,'reviewed-target-v1','reviewed-run-v1',%s FROM "
        "mlc3_target_speaker_bindings WHERE recording_attempt_id=%s "
        "ORDER BY revision_number DESC LIMIT 1",
        (
            acquisition_revision,
            different_speaker,
            str(uuid4()),
            uuid4().hex * 2,
            practice_attempt,
        ),
    )
    mismatch = one(
        db,
        "SELECT * FROM freeze_mlc3_same_speaker_eligibility_v1(%s,%s,%s,%s)",
        (
            context["owner"], context["take"], practice_attempt,
            "different-speaker-pair",
        ),
    )
    assert mismatch["eligibility_result"] == (
        "speaker_identity_mismatch_or_unresolved"
    )
    assert mismatch["source_speaker_id"] != mismatch["practice_speaker_id"]
    assert one(
        db,
        "SELECT count(*) AS n FROM exercise_pair_revisions "
        "WHERE acquisition_principal_id=%s AND practice_attempt_id=%s",
        (context["owner"], practice_attempt),
    )["n"] == 0


def test_general_offer_fails_until_exact_source_speaker_is_confirmed(db):
    context, user_id, rollout, feedback, response, prepared = (
        _general_offer_context(db)
    )
    rejected(
        db,
        "SET ROLE service_role; SELECT freeze_exercise_service_offer_v2("
        "%s,%s,%s,%s,%s)",
        (
            context["owner"], response["id"],
            prepared["n1_candidate_set_id"],
            prepared["authorization_check_id"], "offer-before-speaker",
        ),
        "speaker_identity_mismatch_or_unresolved",
    )
    target = service_json_rpc(
        db, "record_mlc3_feedback_self_speaker_target_v1",
        context["owner"], user_id, feedback["membership"]["id"],
        feedback["candidate_id"], "source-speaker-confirmed",
    )
    assert target["speaker_id"]
    offer = service_rpc(
        db, "freeze_exercise_service_offer_v2",
        context["owner"], response["id"],
        prepared["n1_candidate_set_id"], prepared["authorization_check_id"],
        "offer-after-speaker",
    )
    assert offer["operation_mode"] == "general_service"
    assert offer["rollout_revision_id"] == rollout["id"]
    assert offer["dataset_eligible"] is False


def test_foreign_enrolled_principal_cannot_rebind_or_read_offer(db):
    context, user_id, _rollout, feedback, response, prepared = (
        _general_offer_context(db)
    )
    service_json_rpc(
        db, "record_mlc3_feedback_self_speaker_target_v1",
        context["owner"], user_id, feedback["membership"]["id"],
        feedback["candidate_id"], "owner-speaker",
    )
    offer = service_rpc(
        db, "freeze_exercise_service_offer_v2", context["owner"],
        response["id"], prepared["n1_candidate_set_id"],
        prepared["authorization_check_id"], "owner-offer",
    )
    foreign = make_context(db)
    _enable_coach_review_for_fixture(db, foreign)
    rows(
        db,
        "UPDATE processing_authorization_receipts SET policy_id=%s "
        "WHERE id=%s",
        (context["policy"], foreign["receipt"]),
    )
    foreign_user = one(
        db, "SELECT user_id FROM owner_principals WHERE id=%s",
        (foreign["owner"],),
    )["user_id"]
    service_rpc(
        db, "ensure_mlc3_service_enrollment_v2", foreign["owner"],
        foreign_user, "foreign-enrollment",
    )
    rejected(
        db,
        "SET ROLE service_role; SELECT resolve_exercise_service_offer_read_v1("
        "%s,%s)",
        (offer["id"], foreign["owner"]),
    )
    rejected(
        db,
        "SET ROLE service_role; SELECT "
        "record_mlc3_feedback_self_speaker_target_v1(%s,%s,%s,%s,%s)",
        (
            foreign["owner"], foreign_user, feedback["membership"]["id"],
            feedback["candidate_id"], "foreign-speaker-rebind",
        ),
    )
    assert one(
        db,
        "SELECT count(*) AS n FROM mlc3_self_speaker_assertions "
        "WHERE acquisition_principal_id=%s",
        (foreign["owner"],),
    )["n"] == 0


def test_current_service_block_invalidates_enrollment_and_replay(db):
    context = make_context(db)
    user_id, _rollout = _activate_ga(db, context)
    enrollment = service_rpc(
        db, "ensure_mlc3_service_enrollment_v2", context["owner"],
        user_id, "before-block",
    )
    rows(
        db,
        "INSERT INTO processing_service_blocks("
        "acquisition_principal_id,effective_at) "
        "VALUES (%s,clock_timestamp())",
        (context["owner"],),
    )
    rejected(
        db,
        "SET ROLE service_role; SELECT require_mlc3_service_access_v2("
        "%s,%s,%s)",
        (context["owner"], enrollment["rollout_revision_id"], enrollment["id"]),
        "MLC3_DUAL_PURPOSE_AUTHORITY_REQUIRED",
    )
    rejected(
        db,
        "SET ROLE service_role; SELECT ensure_mlc3_service_enrollment_v2("
        "%s,%s,%s)",
        (context["owner"], user_id, "after-block"),
        "MLC3_DUAL_PURPOSE_AUTHORITY_REQUIRED",
    )


def _confirmed_pair_context(
    db, monkeypatch,
):
    context, user_id, _rollout, feedback, response, prepared = (
        _general_offer_context(db)
    )
    source_target = service_json_rpc(
        db, "record_mlc3_feedback_self_speaker_target_v1",
        context["owner"], user_id, feedback["membership"]["id"],
        feedback["candidate_id"], "full-flow-source-speaker",
    )
    offer = service_rpc(
        db, "freeze_exercise_service_offer_v2",
        context["owner"], response["id"],
        prepared["n1_candidate_set_id"], prepared["authorization_check_id"],
        "full-flow-offer",
    )
    practice = service_rpc(
        db, "create_exercise_practice_service_session_v1",
        offer["id"], context["owner"],
        prepared["source_acquisition_receipt_id"], "full-flow-practice",
    )
    legacy_rpc = d2.rpc

    def rollout_rpc(connection, name, *arguments):
        if name == "reserve_exercise_practice_service_upload_v1":
            name = "reserve_exercise_practice_service_upload_v2"
        return legacy_rpc(connection, name, *arguments)

    monkeypatch.setattr(d2, "rpc", rollout_rpc)
    attempt, selection, _media = d2._attach_valid_practice(db, context, practice)
    assert selection["selection_state"] == "selected_first_valid"
    assert one(
        db,
        "SELECT count(*) AS n FROM exercise_pair_revisions "
        "WHERE practice_session_id=%s",
        (practice["id"],),
    )["n"] == 0
    confirmed = service_json_rpc(
        db, "confirm_mlc3_practice_speaker_and_pair_v1",
        context["owner"], user_id, attempt["id"],
        "full-flow-practice-speaker",
    )
    replay = service_json_rpc(
        db, "confirm_mlc3_practice_speaker_and_pair_v1",
        context["owner"], user_id, attempt["id"],
        "full-flow-practice-speaker",
    )
    assert confirmed["eligibility_result"] == "same_speaker_eligible"
    assert confirmed["speaker_target"]["speaker_id"] == source_target["speaker_id"]
    assert confirmed["owner_pair"]["pair_revision_id"] == replay[
        "owner_pair"
    ]["pair_revision_id"]
    assert confirmed["owner_pair"]["pair_assignment_id"] == replay[
        "owner_pair"
    ]["pair_assignment_id"]
    assert one(
        db,
        "SELECT count(*) AS n FROM exercise_pair_revisions "
        "WHERE practice_session_id=%s",
        (practice["id"],),
    )["n"] == 1
    return {
        "context": context,
        "user_id": user_id,
        "practice": practice,
        "attempt": attempt,
        "pair_id": confirmed["owner_pair"]["pair_revision_id"],
        "assignment_id": confirmed["owner_pair"]["pair_assignment_id"],
    }


def _append_superseded_same_binding(db, recording_attempt_id: str):
    latest = one(
        db,
        "SELECT * FROM mlc3_target_speaker_bindings "
        "WHERE recording_attempt_id=%s ORDER BY revision_number DESC LIMIT 1",
        (recording_attempt_id,),
    )
    rows(
        db,
        "INSERT INTO mlc3_target_speaker_bindings("
        "acquisition_principal_id,recording_attempt_id,audio_object_id,"
        "acquisition_revision_id,speaker_id,self_speaker_assertion_id,"
        "reviewed_segmentation_id,revision_number,supersedes_binding_id,"
        "binding_state,clip_id,practice_attempt_id,target_start_ms,"
        "target_duration_ms,transcript_span,transcript_sha256,audio_sha256,"
        "segmentation_policy_version,segmentation_run_version,"
        "target_binding_sha256) VALUES ("
        "%s,%s,%s,%s,%s,%s,%s,%s,%s,'superseded',%s,%s,%s,%s,%s,%s,%s,"
        "%s,%s,%s)",
        (
            latest["acquisition_principal_id"], recording_attempt_id,
            latest["audio_object_id"], latest["acquisition_revision_id"],
            latest["speaker_id"], latest["self_speaker_assertion_id"],
            latest["reviewed_segmentation_id"],
            latest["revision_number"] + 1, latest["id"], latest["clip_id"],
            latest["practice_attempt_id"], latest["target_start_ms"],
            latest["target_duration_ms"], Json(latest["transcript_span"]),
            latest["transcript_sha256"], latest["audio_sha256"],
            latest["segmentation_policy_version"],
            latest["segmentation_run_version"], uuid4().hex * 2,
        ),
    )


def _append_different_speaker_binding(db, recording_attempt_id: str):
    latest_revision = one(
        db,
        "SELECT * FROM mlc3_speaker_acquisition_revisions "
        "WHERE recording_attempt_id=%s ORDER BY revision_number DESC LIMIT 1",
        (recording_attempt_id,),
    )
    latest_binding = one(
        db,
        "SELECT * FROM mlc3_target_speaker_bindings "
        "WHERE recording_attempt_id=%s ORDER BY revision_number DESC LIMIT 1",
        (recording_attempt_id,),
    )
    speaker_id = str(uuid4())
    revision_id = str(uuid4())
    rows(db, "INSERT INTO ml_speakers(id) VALUES (%s)", (speaker_id,))
    rows(
        db,
        "INSERT INTO mlc3_speaker_acquisition_revisions("
        "id,acquisition_principal_id,recording_attempt_id,audio_object_id,"
        "revision_number,supersedes_revision_id,speaker_count_status,"
        "speaker_identity_status,speaker_id,count_policy_version,"
        "identity_policy_version,evidence_source,audio_sha256,binding_sha256) "
        "VALUES (%s,%s,%s,%s,%s,%s,'single','resolved',%s,"
        "'reviewed-count-v1','reviewed-identity-v1','reviewed_segmentation',"
        "%s,%s)",
        (
            revision_id, latest_revision["acquisition_principal_id"],
            recording_attempt_id, latest_revision["audio_object_id"],
            latest_revision["revision_number"] + 1, latest_revision["id"],
            speaker_id, latest_revision["audio_sha256"], uuid4().hex * 2,
        ),
    )
    rows(
        db,
        "INSERT INTO mlc3_target_speaker_bindings("
        "acquisition_principal_id,recording_attempt_id,audio_object_id,"
        "acquisition_revision_id,speaker_id,reviewed_segmentation_id,"
        "revision_number,supersedes_binding_id,binding_state,clip_id,"
        "practice_attempt_id,target_start_ms,target_duration_ms,"
        "transcript_span,transcript_sha256,audio_sha256,"
        "segmentation_policy_version,segmentation_run_version,"
        "target_binding_sha256) VALUES ("
        "%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s,%s,%s,%s,%s,"
        "'reviewed-target-v1','reviewed-run-v1',%s)",
        (
            latest_binding["acquisition_principal_id"], recording_attempt_id,
            latest_binding["audio_object_id"], revision_id, speaker_id,
            str(uuid4()), latest_binding["revision_number"] + 1,
            latest_binding["id"], latest_binding["clip_id"],
            latest_binding["practice_attempt_id"],
            latest_binding["target_start_ms"],
            latest_binding["target_duration_ms"],
            Json(latest_binding["transcript_span"]),
            latest_binding["transcript_sha256"], latest_binding["audio_sha256"],
            uuid4().hex * 2,
        ),
    )


def test_practice_pair_is_created_only_after_exact_same_speaker_confirmation(
    db, monkeypatch,
):
    _confirmed_pair_context(db, monkeypatch)


def test_latest_superseded_binding_is_excluded_and_cannot_create_pair(
    db, monkeypatch,
):
    flow = _confirmed_pair_context(db, monkeypatch)
    attempt = flow["attempt"]
    _append_superseded_same_binding(
        db, attempt["processing_recording_attempt_id"],
    )
    pair = one(
        db,
        "SELECT * FROM exercise_pair_revisions WHERE id=%s",
        (flow["pair_id"],),
    )
    eligibility = one(
        db,
        "SELECT * FROM freeze_mlc3_same_speaker_eligibility_v1("
        "%s,%s,%s,%s)",
        (
            flow["context"]["owner"],
            one(
                db,
                "SELECT recording_attempt_id FROM exercise_audio_lineages "
                "WHERE id=%s",
                (pair["source_audio_lineage_id"],),
            )["recording_attempt_id"],
            attempt["processing_recording_attempt_id"],
            "superseded-binding-eligibility",
        ),
    )
    assert eligibility["eligibility_result"] == (
        "speaker_identity_mismatch_or_unresolved"
    )
    rejected(
        db,
        "SET ROLE service_role; SELECT freeze_exercise_service_pair_v1("
        "%s,%s,%s,%s,%s)",
        (
            flow["practice"]["id"], flow["context"]["owner"],
            pair["selection_revision_id"], pair["comparison_revision"],
            "pair-after-superseded-binding",
        ),
        "speaker_identity_mismatch_or_unresolved",
    )
    assert one(
        db,
        "SELECT count(*) AS n FROM exercise_pair_revisions "
        "WHERE practice_session_id=%s",
        (flow["practice"]["id"],),
    )["n"] == 1


def test_identity_change_rejects_new_owner_preference_without_judgment(
    db, monkeypatch,
):
    flow = _confirmed_pair_context(db, monkeypatch)
    _append_different_speaker_binding(
        db, flow["attempt"]["processing_recording_attempt_id"],
    )
    rejected(
        db,
        "SET ROLE service_role; SELECT "
        "submit_exercise_service_owner_pair_judgment_v1(%s,%s,%s,%s)",
        (
            flow["assignment_id"], flow["context"]["owner"],
            "prefer_right", "judgment-after-identity-change",
        ),
        "speaker_identity_mismatch_or_unresolved",
    )
    assert one(
        db,
        "SELECT count(*) AS n FROM exercise_pair_judgments "
        "WHERE pair_assignment_id=%s",
        (flow["assignment_id"],),
    )["n"] == 0


def test_identity_change_rejects_exact_judgment_replay(db, monkeypatch):
    flow = _confirmed_pair_context(db, monkeypatch)
    judgment = service_rpc(
        db, "submit_exercise_service_owner_pair_judgment_v1",
        flow["assignment_id"], flow["context"]["owner"],
        "prefer_left", "same-speaker-judgment",
    )
    replay = service_rpc(
        db, "submit_exercise_service_owner_pair_judgment_v1",
        flow["assignment_id"], flow["context"]["owner"],
        "prefer_left", "same-speaker-judgment",
    )
    assert replay["id"] == judgment["id"]
    _append_different_speaker_binding(
        db, flow["attempt"]["processing_recording_attempt_id"],
    )
    rejected(
        db,
        "SET ROLE service_role; SELECT "
        "submit_exercise_service_owner_pair_judgment_v1(%s,%s,%s,%s)",
        (
            flow["assignment_id"], flow["context"]["owner"],
            "prefer_left", "same-speaker-judgment",
        ),
        "speaker_identity_mismatch_or_unresolved",
    )
    assert one(
        db,
        "SELECT count(*) AS n FROM exercise_pair_judgments "
        "WHERE pair_assignment_id=%s",
        (flow["assignment_id"],),
    )["n"] == 1


def test_identity_change_wins_judgment_contention_without_partial_row(
    db, monkeypatch,
):
    flow = _confirmed_pair_context(db, monkeypatch)
    recording_attempt_id = flow["attempt"]["processing_recording_attempt_id"]
    db.commit()
    holder = psycopg2.connect(db.dsn)
    waiter = psycopg2.connect(db.dsn)
    holder.autocommit = False
    waiter.autocommit = True
    application = "d4_identity_wait_" + uuid4().hex
    try:
        rows(
            holder,
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            ("mlc3-speaker-attempt:" + recording_attempt_id,),
        )
        rows(waiter, "SET application_name=%s", (application,))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                service_rpc, waiter,
                "submit_exercise_service_owner_pair_judgment_v1",
                flow["assignment_id"], flow["context"]["owner"],
                "prefer_right", "identity-contention-judgment",
            )
            try:
                wait_for_lock(db, application, "advisory")
                _append_different_speaker_binding(
                    holder, recording_attempt_id,
                )
                holder.commit()
            except BaseException as lock_error:
                holder.rollback()
                try:
                    future.result(timeout=2)
                except BaseException as worker_error:
                    raise AssertionError(
                        "judgment worker failed before reaching identity lock"
                    ) from worker_error
                raise lock_error
            with pytest.raises(
                psycopg2.Error,
                match="speaker_identity_mismatch_or_unresolved",
            ):
                future.result(timeout=5)
    finally:
        holder.rollback()
        waiter.close()
        holder.close()
    assert one(
        db,
        "SELECT count(*) AS n FROM exercise_pair_judgments "
        "WHERE pair_assignment_id=%s",
        (flow["assignment_id"],),
    )["n"] == 0


def test_upload_capacity_is_serialized_and_replay_does_not_reserve_twice(db):
    context, user_id, _rollout, feedback, response, prepared = (
        _general_offer_context(db)
    )
    service_json_rpc(
        db, "record_mlc3_feedback_self_speaker_target_v1",
        context["owner"], user_id, feedback["membership"]["id"],
        feedback["candidate_id"], "capacity-source-speaker",
    )
    offer = service_rpc(
        db, "freeze_exercise_service_offer_v2", context["owner"],
        response["id"], prepared["n1_candidate_set_id"],
        prepared["authorization_check_id"], "capacity-offer",
    )
    practice = service_rpc(
        db, "create_exercise_practice_service_session_v1", offer["id"],
        context["owner"], prepared["source_acquisition_receipt_id"],
        "capacity-practice",
    )

    def reserve(label: str):
        return service_rpc(
            db, "reserve_exercise_practice_service_upload_v2",
            practice["id"], context["owner"], str(uuid4()),
            f"mlc3-practice/{context['owner']}/{practice['id']}/{label}.webm",
            4096, "audio/webm", "7" * 64, label, 900,
        )

    first = reserve("capacity-upload-1")
    second = reserve("capacity-upload-2")
    replay = service_rpc(
        db, "reserve_exercise_practice_service_upload_v2",
        practice["id"], context["owner"], first["recording_id"],
        first["object_key"], first["byte_size"], first["content_type"],
        first["intended_exact_bytes_sha256"], "capacity-upload-1", 900,
    )
    assert replay["id"] == first["id"]
    assert (first["attempt_index"], second["attempt_index"]) == (1, 2)
    rejected(
        db,
        "SET ROLE service_role; SELECT "
        "reserve_exercise_practice_service_upload_v2("
        "%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            practice["id"], context["owner"], str(uuid4()),
            f"mlc3-practice/{context['owner']}/{practice['id']}/third.webm",
            4096, "audio/webm", "8" * 64, "capacity-upload-3", 900,
        ),
        "MLC3_UPLOAD_CAPACITY_REACHED",
    )
    monitor = service_json_rpc(db, "get_mlc3_general_service_monitor_v1")
    assert monitor["active_uploads"] == 2
    assert monitor["maximum_active_uploads_per_principal"] == 2
