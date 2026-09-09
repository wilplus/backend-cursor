"""Database-bound checks for the disabled First-Client Service D2 slice.

The target must be a disposable local database whose name starts with
``willab_service_``. These tests never activate the service contract or write
real media.
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import psycopg2
from psycopg2.extras import Json
import pytest

from tests.test_mlc3_dark_assignments_postgres import (
    assign,
    make_context,
    rpc,
    wait_for_lock,
)
from tests.test_mlc3_n1_source_pattern_postgres import profile, source_pattern
from tests.test_coach_guidance_delivery_d3_postgres import (
    _authorize_coach,
    _install_full_review_shape,
)

DSN = os.environ.get("MLC3_FIRST_CLIENT_REHEARSAL_DSN", "")
ATTACHMENT_SIGNATURE = (
    "public.create_coach_guidance_service_attachment_v1(uuid,uuid,uuid,uuid,"
    "text,text,text,uuid,uuid,uuid,uuid,text,text,text,text,text)"
)
pytestmark = pytest.mark.skipif(not DSN, reason="disposable D2 rehearsal only")


@pytest.fixture
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith(
        ("willab_service_", "willab_m33_")
    ):
        raise RuntimeError("Refusing a non-disposable database")
    if not parsed.get("host", "").startswith(
        ("/tmp/willab-", "/private/tmp/willab-")
    ):
        raise RuntimeError("Refusing a non-local rehearsal host")
    connection = psycopg2.connect(DSN)
    connection.autocommit = True
    yield connection
    connection.close()


def rows(db, statement: str, parameters=()):
    with db.cursor() as cursor:
        cursor.execute(statement, parameters)
        columns = [column.name for column in cursor.description or ()]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def one(db, statement: str, parameters=()):
    result = rows(db, statement, parameters)
    assert len(result) == 1
    return result[0]


def execute(db, statement: str, parameters=()):
    with db.cursor() as cursor:
        cursor.execute(statement, parameters)


def _age_authorization_checks(db, *check_ids):
    execute(
        db,
        "ALTER TABLE exercise_authorization_checks DISABLE TRIGGER "
        "exercise_authorization_checks_append_only",
    )
    try:
        execute(
            db,
            "UPDATE exercise_authorization_checks "
            "SET checked_at=clock_timestamp()-interval '6 minutes' "
            "WHERE id = ANY(%s::uuid[])",
            (list(check_ids),),
        )
    finally:
        execute(
            db,
            "ALTER TABLE exercise_authorization_checks ENABLE TRIGGER "
            "exercise_authorization_checks_append_only",
        )


def rejected_without_aborting(db, name: str, *args):
    execute(db, "SAVEPOINT expected_rejection")
    try:
        with pytest.raises(psycopg2.Error):
            rpc(db, name, *args)
    finally:
        execute(db, "ROLLBACK TO SAVEPOINT expected_rejection")
        execute(db, "RESET ROLE")
        execute(db, "RELEASE SAVEPOINT expected_rejection")


def _activate_service(db, ctx):
    execute(
        db,
        "UPDATE mlc3_service_contracts SET state='active',"
        "active_from=clock_timestamp()-interval '1 second',"
        "retired_at=NULL,"
        "practice_bucket='practice-r2',coach_video_bucket='coach-r2' "
        "WHERE contract_version='mlc3-first-client-service-v1'",
    )
    execute(
        db,
        "INSERT INTO mlc3_service_principal_allowlist("
        "acquisition_principal_id,contract_version,state,"
        "approved_by_principal_id,approval_evidence_sha256,idempotency_key) "
        "VALUES (%s,'mlc3-first-client-service-v1','active',%s,%s,%s)",
        (ctx["owner"], ctx["reviewer"], "a" * 64, str(uuid4())),
    )
    execute(
        db,
        "UPDATE processing_authorization_snapshots SET source_recording_id=%s "
        "WHERE id=%s",
        (ctx["recording"], ctx["snapshot"]),
    )
    execute(
        db,
        "UPDATE processing_recording_attempts SET authorization_snapshot_id=%s "
        "WHERE id=%s",
        (ctx["snapshot"], ctx["take"]),
    )


def _service_membership(db, ctx):
    owner_user = one(
        db, "SELECT user_id FROM owner_principals WHERE id=%s", (ctx["owner"],)
    )["user_id"]
    execute(db, "UPDATE v2_sessions SET user_id=%s WHERE id=%s", (
        owner_user, ctx["take"],
    ))
    evidence_id = str(uuid4())
    manager_set_id = str(uuid4())
    candidate_id = str(uuid4())
    exposure_id = str(uuid4())
    part_id = str(uuid4())
    document_id = str(uuid4())
    exact_passage = "We finish this phrase with steady deliberate pacing."
    candidate_key = "candidate-" + ctx["snippet"]
    execute(
        db,
        "INSERT INTO evidence_spans(id,owner_principal_id,project_id,take_id,"
        "recording_id,legacy_piece_id,evidence_kind,task_type,start_ms,end_ms,"
        "exact_text,evidence_hash,input_hash) VALUES "
        "(%s,%s,%s,%s,%s,%s,'audio_and_transcript',"
        "'confidence_classification',1250,3650,%s,%s,%s)",
        (evidence_id, ctx["owner"], ctx["project"], ctx["take"],
         ctx["recording"], ctx["snippet"], exact_passage,
         str(uuid4()), str(uuid4())),
    )
    execute(
        db,
        "INSERT INTO candidate_sets(id,owner_principal_id,project_id,take_id,"
        "taxonomy_version,selector_version,manager_rules_version,"
        "threshold_version,input_hash,idempotency_key,code_commit) VALUES "
        "(%s,%s,%s,%s,'feedback-v3','selector-v1',"
        "'take-feedback-policy-v3-serving-v1','threshold-v1',%s,%s,'test')",
        (manager_set_id, ctx["owner"], ctx["project"], ctx["take"],
         "b" * 64, str(uuid4())),
    )
    execute(
        db,
        "INSERT INTO feedback_candidates(id,candidate_set_id,evidence_span_id,"
        "feedback_family,lane,candidate_key,generated_output) VALUES "
        "(%s,%s,%s,'confident_voice','vocal',%s,%s)",
        (candidate_id, manager_set_id, evidence_id, candidate_key,
         Json({"quote": exact_passage})),
    )
    execute(
        db,
        "INSERT INTO feedback_exposures(id,candidate_set_id,candidate_id,"
        "feedback_family,lane,is_selected,position_shown,shown_at,"
        "selector_version,manager_rules_version,threshold_version,input_hash) "
        "VALUES (%s,%s,%s,'confident_voice','vocal',true,1,NULL,"
        "'selector-v1','take-feedback-policy-v3-serving-v1','threshold-v1',%s)",
        (exposure_id, manager_set_id, candidate_id, "c" * 64),
    )
    payload = {
        "parts": [{"id": part_id, "text": exact_passage}],
        "pieces": [{"part_id": part_id, "slide_index": 0}],
    }
    execute(
        db,
        "INSERT INTO ideal_text_document_generations(arc_id,generation) "
        "VALUES (%s,1)", (str(ctx["project"]),),
    )
    execute(
        db,
        "INSERT INTO ideal_text_document_snapshots(id,arc_id,actor_id,"
        "acquisition_principal_id,project_id,source_take_session_id,version,"
        "source_generation,source_fingerprint_sha256,payload_sha256,payload) "
        "VALUES (%s,%s,%s,%s,%s,%s,1,1,%s,%s,%s)",
        (document_id, str(ctx["project"]), str(owner_user), ctx["owner"],
         ctx["project"], ctx["take"], "d" * 64, "e" * 64, Json(payload)),
    )
    execute(
        db,
        "INSERT INTO ideal_text_document_heads(arc_id,actor_id,snapshot_id) "
        "VALUES (%s,%s,%s)",
        (str(ctx["project"]), str(owner_user), document_id),
    )
    items = Json([{
        "candidate_id": candidate_id,
        "candidate_key": candidate_key,
        "feedback_family": "confident_voice",
        "slide_index": 0,
        "block_key": 0,
        "source_ideal_part_id": part_id,
        "eligibility": "eligible",
        "exclusion_reason": None,
        "selected": True,
        "position_shown": 1,
    }])
    membership = rpc(
        db, "freeze_feedback_v3_service_membership_v1", ctx["owner"],
        ctx["project"], ctx["take"], manager_set_id, document_id,
        "slide-75-words-v1", items, str(uuid4()),
    )
    return {
        "owner_user": owner_user,
        "membership": membership,
        "candidate_id": candidate_id,
        "exposure_id": exposure_id,
        "document_id": document_id,
        "exact_passage": exact_passage,
    }


def _create_live_practice_context(db):
    """Create committed synthetic service state for concurrency probes."""
    ctx = make_context(db)
    source = source_pattern(db, ctx, "confident")
    for version in ctx["versions"]:
        profile(db, version["id"], ["confident"])
    assignment = assign(db, ctx)
    rpc(
        db, "freeze_exercise_n1_pattern_snapshot_v1",
        assignment["id"], source["id"], str(uuid4()),
    )
    _activate_service(db, ctx)
    feedback = _service_membership(db, ctx)
    render = rpc(
        db, "ack_feedback_v3_service_render_v1", ctx["owner"],
        feedback["owner_user"], feedback["membership"]["id"],
        feedback["candidate_id"], feedback["exposure_id"], str(uuid4()),
        feedback["membership"]["content_identity_sha256"],
        one(db, "SELECT clock_timestamp() AS value")["value"],
        "postgres-rehearsal", str(uuid4()),
    )
    response = rpc(
        db, "record_feedback_v3_service_response_v1", ctx["project"],
        ctx["take"], ctx["owner"], feedback["owner_user"],
        feedback["membership"]["id"], feedback["candidate_id"],
        feedback["exposure_id"], render["id"], "confident_yes", str(uuid4()),
    )
    prepared = rpc(
        db, "prepare_feedback_v3_service_context_v1",
        feedback["membership"]["id"], feedback["candidate_id"],
        ctx["owner"], str(uuid4()),
    )["prepare_feedback_v3_service_context_v1"]
    offer = rpc(
        db, "freeze_exercise_service_offer_v2", ctx["owner"], response["id"],
        prepared["n1_candidate_set_id"], prepared["authorization_check_id"],
        str(uuid4()),
    )
    practice = rpc(
        db, "create_exercise_practice_service_session_v1", offer["id"],
        ctx["owner"], prepared["source_acquisition_receipt_id"], str(uuid4()),
    )
    return ctx, practice


def _prepare_transcription_run(
    db, ctx, practice, *, dispatch=True,
):
    recording_id = str(uuid4())
    processing_attempt_id = str(uuid4())
    audio_object_id = str(uuid4())
    digest = "7" * 64
    object_key = (
        f"mlc3-practice/{ctx['owner']}/{practice['id']}/{audio_object_id}.webm"
    )
    recovery = rpc(
        db, "reserve_exercise_practice_service_upload_v1", practice["id"],
        ctx["owner"], recording_id, object_key, 4096, "audio/webm",
        digest, str(uuid4()), 900,
    )
    rpc(
        db, "ack_exercise_practice_service_upload_v1", recovery["id"],
        ctx["owner"], digest, 4096, str(uuid4()),
    )
    media_finalization_key = str(uuid4())
    finalized = rpc(
        db, "finalize_exercise_practice_service_media_v1", recovery["id"],
        ctx["owner"], processing_attempt_id, audio_object_id,
        "read_after_write_sha256", media_finalization_key,
    )["finalize_exercise_practice_service_media_v1"]
    transcription_key = str(uuid4())
    transcription_run = rpc(
        db, "authorize_exercise_practice_transcription_v1", recovery["id"],
        ctx["owner"], processing_attempt_id, audio_object_id,
        finalized["practice_acquisition_receipt_id"], "openai", "whisper-1",
        "disfluent-preservation-v1", "auto-detect-no-hint-v1", None,
        "whisper-verbose-word-timestamps-v1", transcription_key,
    )
    if dispatch:
        transcription_run = rpc(
            db, "mark_exercise_practice_transcription_dispatched_v1",
            transcription_run["id"], ctx["owner"],
            transcription_key + ":dispatch",
        )
    return transcription_run, {
        "recovery": recovery,
        "processing_attempt_id": processing_attempt_id,
        "audio_object_id": audio_object_id,
        "acquisition_receipt_id": finalized[
            "practice_acquisition_receipt_id"
        ],
        "transcription_key": transcription_key,
        "media_finalization_key": media_finalization_key,
    }


def _attach_valid_practice(db, ctx, practice):
    transcription_run, media = _prepare_transcription_run(
        db, ctx, practice
    )
    transcription_run = rpc(
        db, "finalize_exercise_practice_transcription_v1",
        transcription_run["id"], ctx["owner"], "finalized",
        Json({
            "provider_response_id": "synthetic-whisper-response",
            "transcript": practice["exact_passage"],
            "language": "en",
            "words": [],
            "transcribed_duration_ms": 4000,
        }), None, str(uuid4()),
    )
    captured_at = one(db, "SELECT clock_timestamp() AS value")["value"]
    attempt = rpc(
        db, "attach_exercise_practice_service_attempt_v1",
        media["recovery"]["id"], media["processing_attempt_id"],
        media["audio_object_id"], media["acquisition_receipt_id"],
        transcription_run["id"], practice["exact_passage"],
        4000, captured_at, captured_at, Json({"fixture": True}),
        str(uuid4()),
    )
    measurement = rpc(
        db, "record_exercise_practice_service_measurement_v1", attempt["id"],
        1, "rushed-phrase-endings-n1-extractor-v1",
        "rushed-phrase-endings-n1-features-v1",
        Json({
            "phrase_span": {"start_ms": 0, "end_ms": 4000},
            "prefix_span": {"start_ms": 0, "end_ms": 2500},
            "ending_span": {"start_ms": 2500, "end_ms": 4000},
            "measurement_status": "complete",
        }),
        Json({"missingness_reasons": [], "uncertainty": {}}), str(uuid4()),
    )
    rpc(
        db, "record_exercise_practice_service_validity_v1", attempt["id"],
        measurement["id"], practice["baseline_revision"], "valid", [],
        "rushed-phrase-endings-n1-validity-v1", str(uuid4()),
    )
    selection = rpc(
        db, "freeze_exercise_practice_service_selection_v1", practice["id"],
        ctx["owner"], practice["baseline_revision"], 1, str(uuid4()),
    )
    assert selection["selected_attempt_id"] == attempt["id"]
    return attempt, selection, {
        **media,
        "transcription_run": transcription_run,
    }


def test_all_database_activation_inputs_are_closed(db):
    contract = one(
        db,
        "SELECT state,active_from,retired_at,practice_bucket,coach_video_bucket "
        "FROM mlc3_service_contracts WHERE contract_version=%s",
        ("mlc3-first-client-service-v1",),
    )
    assert contract == {
        "state": "disabled",
        "active_from": None,
        "retired_at": None,
        "practice_bucket": None,
        "coach_video_bucket": None,
    }
    assert one(
        db,
        "SELECT count(*) AS count FROM mlc3_service_principal_allowlist",
    )["count"] == 0


@pytest.mark.parametrize(
    "signature",
    (
        "record_feedback_v3_service_candidate_set_v1(uuid,uuid,uuid,jsonb)",
        "freeze_feedback_v3_service_membership_v1(uuid,uuid,uuid,uuid,uuid,text,jsonb,text)",
        "ack_feedback_v3_service_render_v1(uuid,uuid,uuid,uuid,uuid,uuid,text,timestamptz,text,text)",
        "record_feedback_v3_service_response_v1(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid,text,text)",
        "freeze_exercise_service_offer_v2(uuid,uuid,uuid,uuid,text)",
        "create_exercise_practice_service_session_v1(uuid,uuid,uuid,text)",
        "reserve_exercise_practice_service_upload_v1(uuid,uuid,uuid,text,bigint,text,text,text,integer)",
        "reserve_coach_guidance_service_upload_v1(uuid,uuid,text,text,text,text,bigint,text,timestamptz,text)",
        "create_coach_guidance_service_attachment_v1(uuid,uuid,uuid,uuid,text,text,text,uuid,uuid,uuid,uuid,text,text,text,text,text)",
        "record_coach_guidance_service_event_v1(uuid,uuid,text,uuid,jsonb,text)",
        "resolve_coach_guidance_service_media_read_v1(uuid,uuid)",
        "resolve_exercise_service_offer_read_v1(uuid,uuid)",
        "resolve_exercise_practice_session_read_v1(uuid,uuid)",
        "resolve_exercise_practice_media_read_v1(uuid,uuid)",
        "resolve_exercise_confidence_media_read_v1(uuid,uuid)",
        "publish_coach_guidance_service_exercise_v1(uuid,uuid,text,text,text,text)",
        "mark_exercise_practice_transcription_dispatched_v1(uuid,uuid,text)",
        "reconcile_exercise_practice_transcription_v1(uuid,uuid,text)",
        "reconcile_exercise_practice_transcription_request_v1(uuid,uuid,text,text)",
    ),
)
def test_only_service_role_can_execute_public_service_writers(db, signature):
    privilege = one(
        db,
        "SELECT has_function_privilege('service_role',%s,'EXECUTE') AS service,"
        "has_function_privilege('authenticated',%s,'EXECUTE') AS client,"
        "has_function_privilege('anon',%s,'EXECUTE') AS anon",
        (f"public.{signature}", f"public.{signature}", f"public.{signature}"),
    )
    assert privilege == {"service": True, "client": False, "anon": False}


@pytest.mark.parametrize(
    "signature",
    (
        "prepare_feedback_v3_service_row_v1()",
        "prepare_exercise_service_row_v1()",
        "prepare_exercise_practice_service_row_v1()",
        "reject_feedback_exposure_mutation_v2()",
        "serialize_mlc3_service_purge_v1()",
        "serialize_mlc3_processing_audio_leaf_v1()",
        "serialize_mlc3_exercise_media_leaf_v1()",
        "require_mlc3_service_principal_v1(uuid)",
        "require_feedback_v3_service_membership_live_v1(uuid,uuid)",
        "issue_exercise_service_authority_v1(uuid,uuid,uuid,text,text)",
        "require_exercise_practice_service_live_v1(uuid,uuid)",
        "require_coach_guidance_service_access_v1(uuid,uuid,text)",
        "require_coach_guidance_service_media_live_v1(uuid,uuid)",
    ),
)
def test_internal_authority_helpers_are_not_runtime_callable(db, signature):
    assert one(
        db,
        "SELECT has_function_privilege('service_role',%s,'EXECUTE') AS allowed",
        (f"public.{signature}",),
    )["allowed"] is False


@pytest.mark.parametrize(
    "table",
    (
        "mlc3_service_contracts",
        "mlc3_service_principal_allowlist",
        "feedback_v3_service_response_bindings",
        "feedback_v3_service_render_receipts",
        "exercise_service_acquisition_receipts",
        "exercise_service_confidence_assignments",
        "exercise_service_confidence_render_receipts",
        "exercise_service_confidence_judgments",
        "exercise_service_blind_review_sets",
        "exercise_service_blind_reveal_grants",
        "exercise_service_blind_reveal_accesses",
    ),
)
def test_new_relations_have_rls_and_runtime_read_only_access(db, table):
    relation = one(
        db,
        "SELECT relrowsecurity,has_table_privilege('service_role',c.oid,'SELECT') "
        "AS can_read,has_table_privilege('service_role',c.oid,'INSERT') AS can_write "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relname=%s",
        (table,),
    )
    assert relation == {
        "relrowsecurity": True,
        "can_read": True,
        "can_write": False,
    }


def test_served_records_remain_dataset_ineligible_by_constraint(db):
    for table in (
        "exercise_service_offers",
        "exercise_practice_sessions",
        "coach_guidance_attachment_versions",
        "coach_guidance_lifecycle_events",
    ):
        definitions = rows(
            db,
            "SELECT pg_get_constraintdef(con.oid) AS definition "
            "FROM pg_constraint con WHERE con.conrelid=%s::regclass "
            "AND con.contype='c'",
            (f"public.{table}",),
        )
        assert any(
            "NOT dataset_eligible" in row["definition"]
            for row in definitions
        ), table


def test_offer_and_guidance_functions_embed_live_exact_identity_checks(db):
    offer = one(
        db,
        "SELECT pg_get_functiondef(%s::regprocedure) AS definition",
        ("public.freeze_exercise_service_offer_v2(uuid,uuid,uuid,uuid,text)",),
    )["definition"]
    attachment = one(
        db,
        "SELECT pg_get_functiondef(%s::regprocedure) AS definition",
        (ATTACHMENT_SIGNATURE,),
    )["definition"]
    assert "require_feedback_v3_service_response_v1" in offer
    assert "confident_audio_unclear" not in offer
    assert "require_coach_guidance_service_access_v1" in attachment
    assert "require_coach_guidance_service_media_live_v1" in attachment
    assert "COACH_GUIDANCE_GENERAL_EXERCISE_FIELDS_FORBIDDEN" in attachment


def test_full_render_response_offer_chain_and_cross_principal_rejection(db):
    ctx = make_context(db)
    source = source_pattern(db, ctx, "confident")
    for version in ctx["versions"]:
        profile(db, version["id"], ["confident"])
    assignment = assign(db, ctx)
    rpc(
        db, "freeze_exercise_n1_pattern_snapshot_v1",
        assignment["id"], source["id"], str(uuid4()),
    )
    db.autocommit = False
    try:
        _activate_service(db, ctx)
        feedback = _service_membership(db, ctx)
        rendered_at = one(db, "SELECT clock_timestamp() AS value")["value"]
        render = rpc(
            db, "ack_feedback_v3_service_render_v1", ctx["owner"],
            feedback["owner_user"], feedback["membership"]["id"],
            feedback["candidate_id"], feedback["exposure_id"], str(uuid4()),
            feedback["membership"]["content_identity_sha256"], rendered_at,
            "postgres-rehearsal", str(uuid4()),
        )
        assert one(
            db, "SELECT shown_at FROM feedback_exposures WHERE id=%s",
            (feedback["exposure_id"],),
        )["shown_at"] == rendered_at
        reopened_at = one(
            db, "SELECT clock_timestamp() AS value",
        )["value"]
        reopened_render = rpc(
            db, "ack_feedback_v3_service_render_v1", ctx["owner"],
            feedback["owner_user"], feedback["membership"]["id"],
            feedback["candidate_id"], feedback["exposure_id"], str(uuid4()),
            feedback["membership"]["content_identity_sha256"], reopened_at,
            "postgres-rehearsal", str(uuid4()),
        )
        assert reopened_render["id"] != render["id"]
        assert one(
            db, "SELECT shown_at FROM feedback_exposures WHERE id=%s",
            (feedback["exposure_id"],),
        )["shown_at"] == rendered_at
        response = rpc(
            db, "record_feedback_v3_service_response_v1", ctx["project"],
            ctx["take"], ctx["owner"], feedback["owner_user"],
            feedback["membership"]["id"], feedback["candidate_id"],
            feedback["exposure_id"], reopened_render["id"], "confident_yes",
            str(uuid4()),
        )
        execute(
            db,
            "INSERT INTO processing_purpose_registry("
            "id,operational,authorizes_processing) VALUES "
            "('pooled_model_improvement',true,true) ON CONFLICT DO NOTHING",
        )
        execute(
            db,
            "INSERT INTO processing_policy_purposes(policy_id,purpose_id) "
            "VALUES (%s,'pooled_model_improvement') ON CONFLICT DO NOTHING",
            (ctx["policy"],),
        )
        execute(
            db,
            "INSERT INTO processing_authorization_receipt_purposes("
            "receipt_id,purpose_id) VALUES (%s,'pooled_model_improvement') "
            "ON CONFLICT DO NOTHING",
            (ctx["receipt"],),
        )
        execute(
            db,
            "INSERT INTO processing_authorization_snapshots("
            "acquisition_principal_id,receipt_id,policy_id,purpose_id,"
            "source_take_id,source_recording_id,operation_kind,"
            "authority_evidence_sha256,pooled_learning_eligible) VALUES "
            "(%s,%s,%s,'pooled_model_improvement',%s,%s,"
            "'later_opt_in',%s,false)",
            (ctx["owner"], ctx["receipt"], ctx["policy"], ctx["take"],
             ctx["recording"], "9" * 64),
        )
        prepared = rpc(
            db, "prepare_feedback_v3_service_context_v1",
            feedback["membership"]["id"], feedback["candidate_id"],
            ctx["owner"], str(uuid4()),
        )
        prepared = prepared["prepare_feedback_v3_service_context_v1"]
        assert prepared["pooled_state_at_acquisition"] == "not_authorized"
        offer = rpc(
            db, "freeze_exercise_service_offer_v2", ctx["owner"],
            response["id"], prepared["n1_candidate_set_id"],
            prepared["authorization_check_id"], str(uuid4()),
        )
        assert offer["outcome"] == "service_matched"
        assert offer["acquisition_principal_id"] == ctx["owner"]
        practice = rpc(
            db, "create_exercise_practice_service_session_v1", offer["id"],
            ctx["owner"], prepared["source_acquisition_receipt_id"],
            str(uuid4()),
        )
        assert practice["exact_passage"] == feedback["exact_passage"]
        assert practice["closes_at"] - practice["opens_at"] == timedelta(hours=24)
        _install_full_review_shape(db)
        _authorize_coach(db, ctx)
        practice_attempt, _, practice_media = _attach_valid_practice(
            db, ctx, practice
        )
        transcription = one(
            db,
            "SELECT status,provider,model_version,prompt_version,"
            "language_policy_version,request_sha256,response_sha256,"
            "run_sha256,dataset_eligible FROM "
            "exercise_practice_transcription_runs WHERE id=%s",
            (practice_attempt["transcription_run_id"],),
        )
        assert transcription["status"] == "finalized"
        assert transcription["provider"] == "openai"
        assert transcription["model_version"] == "whisper-1"
        assert transcription["prompt_version"] == "disfluent-preservation-v1"
        assert transcription["language_policy_version"] == (
            "auto-detect-no-hint-v1"
        )
        assert all(
            len(transcription[key]) == 64
            for key in ("request_sha256", "response_sha256", "run_sha256")
        )
        assert transcription["dataset_eligible"] is False
        rejected_without_aborting(
            db, "authorize_exercise_practice_transcription_v1",
            practice_media["recovery"]["id"], ctx["owner"],
            practice_media["processing_attempt_id"],
            practice_media["audio_object_id"],
            practice_media["acquisition_receipt_id"], "openai",
            "whisper-2", "disfluent-preservation-v1",
            "auto-detect-no-hint-v1", None,
            "whisper-verbose-word-timestamps-v1",
            practice_media["transcription_key"],
        )
        rejected_without_aborting(
            db, "authorize_exercise_practice_transcription_v1",
            practice_media["recovery"]["id"], ctx["owner"],
            practice_media["processing_attempt_id"],
            practice_media["audio_object_id"],
            practice_media["acquisition_receipt_id"], "openai",
            "whisper-1", "different-prompt-v2",
            "auto-detect-no-hint-v1", None,
            "whisper-verbose-word-timestamps-v1",
            practice_media["transcription_key"],
        )
        rejected_without_aborting(
            db, "attach_exercise_practice_service_attempt_v1",
            practice_media["recovery"]["id"],
            practice_media["processing_attempt_id"],
            practice_media["audio_object_id"],
            practice_media["acquisition_receipt_id"], str(uuid4()),
            practice["exact_passage"], 4000,
            one(db, "SELECT clock_timestamp() AS value")["value"],
            one(db, "SELECT clock_timestamp() AS value")["value"],
            Json({"fixture": True}), str(uuid4()),
        )
        execute(db, "SAVEPOINT revoked_provider_processing")
        try:
            execute(
                db,
                "INSERT INTO processing_service_blocks("
                "acquisition_principal_id,effective_at) "
                "VALUES (%s,clock_timestamp())",
                (ctx["owner"],),
            )
            with pytest.raises(psycopg2.Error):
                rpc(
                    db, "authorize_exercise_practice_transcription_v1",
                    practice_media["recovery"]["id"], ctx["owner"],
                    practice_media["processing_attempt_id"],
                    practice_media["audio_object_id"],
                    practice_media["acquisition_receipt_id"], "openai",
                    "whisper-1", "disfluent-preservation-v1",
                    "auto-detect-no-hint-v1", None,
                    "whisper-verbose-word-timestamps-v1",
                    practice_media["transcription_key"],
                )
        finally:
            execute(db, "ROLLBACK TO SAVEPOINT revoked_provider_processing")
            execute(db, "RESET ROLE")
            execute(db, "RELEASE SAVEPOINT revoked_provider_processing")
        review_key = str(uuid4())
        first_review = rpc(
            db, "freeze_exercise_service_blind_review_set_v1",
            practice["id"], ctx["reviewer"], review_key,
        )
        initial_source = one(
            db, "SELECT * FROM exercise_service_confidence_assignments "
            "WHERE id=%s", (first_review["source_confidence_assignment_id"],),
        )
        opaque_media = rpc(
            db, "resolve_exercise_confidence_media_read_v1",
            initial_source["playback_reference_id"], ctx["reviewer"],
        )["resolve_exercise_confidence_media_read_v1"]
        assert opaque_media["start_offset_ms"] == initial_source[
            "start_offset_ms"
        ]
        assert opaque_media["duration_ms"] == initial_source["duration_ms"]
        rejected_without_aborting(
            db, "resolve_exercise_confidence_media_read_v1",
            initial_source["id"], ctx["reviewer"],
        )
        execute(
            db,
            "ALTER TABLE exercise_service_confidence_assignments DISABLE "
            "TRIGGER exercise_service_confidence_assignments_append_only",
        )
        execute(
            db,
            "UPDATE exercise_service_confidence_assignments "
            "SET assigned_at=clock_timestamp()-interval '8 days',"
            "expires_at=clock_timestamp()-interval '1 day' "
            "WHERE practice_session_id=%s AND reviewer_principal_id=%s",
            (practice["id"], ctx["reviewer"]),
        )
        execute(
            db,
            "ALTER TABLE exercise_service_confidence_assignments ENABLE "
            "TRIGGER exercise_service_confidence_assignments_append_only",
        )
        successor = rpc(
            db, "freeze_exercise_service_blind_review_set_v1",
            practice["id"], ctx["reviewer"], review_key,
        )
        assert successor["review_revision"] == 2
        assert successor["supersedes_review_set_id"] == first_review["id"]
        successor_source = one(
            db, "SELECT * FROM exercise_service_confidence_assignments "
            "WHERE id=%s", (successor["source_confidence_assignment_id"],),
        )
        successor_practice = one(
            db, "SELECT * FROM exercise_service_confidence_assignments "
            "WHERE id=%s", (successor["practice_confidence_assignment_id"],),
        )
        source_render = rpc(
            db, "ack_exercise_service_confidence_render_v1",
            successor_source["id"], ctx["reviewer"], str(uuid4()),
            successor_source["packet_sha256"],
            one(db, "SELECT clock_timestamp() AS value")["value"],
            "postgres-rehearsal", str(uuid4()),
        )
        rpc(
            db, "submit_exercise_service_confidence_judgment_v1",
            successor_source["id"], ctx["reviewer"], source_render["id"],
            "rating_yes", one(db, "SELECT clock_timestamp() AS value")["value"],
            str(uuid4()),
        )
        execute(
            db,
            "ALTER TABLE exercise_service_confidence_assignments DISABLE "
            "TRIGGER exercise_service_confidence_assignments_append_only",
        )
        execute(
            db,
            "UPDATE exercise_service_confidence_assignments "
            "SET assigned_at=clock_timestamp()-interval '8 days',"
            "expires_at=clock_timestamp()-interval '1 day' "
            "WHERE id IN (%s,%s)",
            (successor_source["id"], successor_practice["id"]),
        )
        execute(
            db,
            "ALTER TABLE exercise_service_confidence_assignments ENABLE "
            "TRIGGER exercise_service_confidence_assignments_append_only",
        )
        partial_successor = rpc(
            db, "freeze_exercise_service_blind_review_set_v1",
            practice["id"], ctx["reviewer"], review_key,
        )
        assert partial_successor["review_revision"] == 3
        assert partial_successor["source_confidence_assignment_id"] == (
            successor_source["id"]
        )
        assert partial_successor["practice_confidence_assignment_id"] != (
            successor_practice["id"]
        )
        final_practice = one(
            db, "SELECT * FROM exercise_service_confidence_assignments "
            "WHERE id=%s",
            (partial_successor["practice_confidence_assignment_id"],),
        )
        practice_render = rpc(
            db, "ack_exercise_service_confidence_render_v1",
            final_practice["id"], ctx["reviewer"], str(uuid4()),
            final_practice["packet_sha256"],
            one(db, "SELECT clock_timestamp() AS value")["value"],
            "postgres-rehearsal", str(uuid4()),
        )
        rpc(
            db, "submit_exercise_service_confidence_judgment_v1",
            final_practice["id"], ctx["reviewer"], practice_render["id"],
            "rating_in_between",
            one(db, "SELECT clock_timestamp() AS value")["value"],
            str(uuid4()),
        )
        execute(
            db,
            "ALTER TABLE exercise_service_confidence_assignments DISABLE "
            "TRIGGER exercise_service_confidence_assignments_append_only",
        )
        execute(
            db,
            "UPDATE exercise_service_confidence_assignments "
            "SET assigned_at=clock_timestamp()-interval '8 days',"
            "expires_at=clock_timestamp()-interval '1 day' "
            "WHERE id IN (%s,%s)",
            (successor_source["id"], final_practice["id"]),
        )
        execute(
            db,
            "ALTER TABLE exercise_service_confidence_assignments ENABLE "
            "TRIGGER exercise_service_confidence_assignments_append_only",
        )
        grant = rpc(
            db, "complete_exercise_service_blind_review_v1",
            partial_successor["id"], ctx["reviewer"], str(uuid4()),
        )
        assert grant["source_judgment_id"] is not None
        assert grant["practice_judgment_id"] is not None
        stable = rpc(
            db, "freeze_exercise_service_blind_review_set_v1",
            practice["id"], ctx["reviewer"], review_key,
        )
        assert stable["id"] == partial_successor["id"]
        assert one(
            db, "SELECT count(*) AS count FROM "
            "exercise_service_confidence_assignments "
            "WHERE practice_session_id=%s AND reviewer_principal_id=%s",
            (practice["id"], ctx["reviewer"]),
        )["count"] == 5

        with pytest.raises(psycopg2.Error):
            rpc(
                db, "freeze_exercise_service_offer_v2", ctx["reviewer"],
                response["id"], prepared["n1_candidate_set_id"],
                prepared["authorization_check_id"], str(uuid4()),
            )
        with pytest.raises(psycopg2.Error):
            rpc(
                db, "create_exercise_practice_service_session_v1",
                offer["id"], ctx["reviewer"],
                prepared["source_acquisition_receipt_id"], str(uuid4()),
            )
    finally:
        db.rollback()
        db.autocommit = True


def test_practice_attempt_indices_are_server_allocated_under_concurrency(db):
    ctx, practice = _create_live_practice_context(db)
    barrier = threading.Barrier(2)

    def reserve(suffix: str):
        connection = psycopg2.connect(DSN)
        connection.autocommit = True
        recording_id = str(uuid4())
        object_key = (
            f"mlc3-practice/{ctx['owner']}/{practice['id']}/{suffix}.webm"
        )
        idempotency_key = f"server-sequence:{practice['id']}:{suffix}"
        try:
            barrier.wait(timeout=5)
            result = rpc(
                connection, "reserve_exercise_practice_service_upload_v1",
                practice["id"], ctx["owner"], recording_id, object_key,
                4096, "audio/webm", "7" * 64, idempotency_key, 900,
            )
            replay = rpc(
                connection, "reserve_exercise_practice_service_upload_v1",
                practice["id"], ctx["owner"], recording_id, object_key,
                4096, "audio/webm", "7" * 64, idempotency_key, 900,
            )
            assert replay["id"] == result["id"]
            assert replay["attempt_index"] == result["attempt_index"]
            return result
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, ("first", "second")))
    assert {row["attempt_index"] for row in results} == {1, 2}
    assert one(
        db,
        "SELECT count(*) AS count FROM pg_proc "
        "WHERE oid::regprocedure::text LIKE "
        "'reserve_exercise_practice_service_upload_v1(uuid,uuid,integer,%%'",
    )["count"] == 0


def test_service_window_refreshes_expired_historical_authority(db):
    ctx, practice = _create_live_practice_context(db)
    offer = one(
        db,
        "SELECT id,authorization_check_id FROM exercise_service_offers "
        "WHERE id=%s",
        (practice["source_offer_id"],),
    )
    historical_ids = (
        offer["authorization_check_id"],
        practice["authorization_check_id"],
    )
    _age_authorization_checks(db, *historical_ids)
    before = one(
        db,
        "SELECT count(*) AS count FROM exercise_authorization_checks "
        "WHERE acquisition_principal_id=%s",
        (ctx["owner"],),
    )["count"]

    resolved_offer = rpc(
        db, "resolve_exercise_service_offer_read_v1",
        offer["id"], ctx["owner"],
    )["resolve_exercise_service_offer_read_v1"]
    resolved_practice = rpc(
        db, "resolve_exercise_practice_session_read_v1",
        practice["id"], ctx["owner"],
    )["resolve_exercise_practice_session_read_v1"]
    assert resolved_offer["offer"]["id"] == offer["id"]
    assert resolved_practice["id"] == practice["id"]
    assert one(
        db,
        "SELECT count(*) AS count FROM exercise_authorization_checks "
        "WHERE acquisition_principal_id=%s",
        (ctx["owner"],),
    )["count"] >= before + 2
    historical = rows(
        db,
        "SELECT id,checked_at FROM exercise_authorization_checks "
        "WHERE id IN (%s,%s) ORDER BY id",
        historical_ids,
    )
    assert len(historical) == 2
    assert all(
        row["checked_at"] < one(
            db, "SELECT clock_timestamp()-interval '5 minutes' AS cutoff"
        )["cutoff"]
        for row in historical
    )


@pytest.mark.parametrize(
    "revocation", ("service_block", "policy_retired", "source_deleted")
)
def test_service_window_refresh_fails_for_current_revocation(db, revocation):
    ctx, practice = _create_live_practice_context(db)
    offer = one(
        db,
        "SELECT id,authorization_check_id FROM exercise_service_offers "
        "WHERE id=%s",
        (practice["source_offer_id"],),
    )
    _age_authorization_checks(
        db, offer["authorization_check_id"], practice["authorization_check_id"]
    )
    if revocation == "service_block":
        execute(
            db,
            "INSERT INTO processing_service_blocks("
            "acquisition_principal_id,effective_at) "
            "VALUES (%s,clock_timestamp())",
            (ctx["owner"],),
        )
    elif revocation == "policy_retired":
        execute(
            db,
            "UPDATE processing_policy_versions "
            "SET status='retired',retired_at=clock_timestamp() WHERE id=%s",
            (ctx["policy"],),
        )
    else:
        execute(
            db,
            "UPDATE processing_audio_objects SET deleted_at=clock_timestamp() "
            "WHERE id=(SELECT processing_audio_object_id "
            "FROM exercise_audio_lineages WHERE id=%s)",
            (practice["source_audio_lineage_id"],),
        )
    with pytest.raises(psycopg2.Error):
        rpc(
            db, "resolve_exercise_service_offer_read_v1",
            offer["id"], ctx["owner"],
        )
    with pytest.raises(psycopg2.Error):
        rpc(
            db, "resolve_exercise_practice_session_read_v1",
            practice["id"], ctx["owner"],
        )


def _offer_delivery_event(db, ctx, offer_id, key, occurred_at):
    user_id = one(
        db, "SELECT user_id FROM owner_principals WHERE id=%s", (ctx["owner"],)
    )["user_id"]
    return rpc(
        db, "record_exercise_offer_service_event_v1", offer_id,
        ctx["owner"], user_id, "delivery_prepared", None, "d" * 64,
        Json({"surface": "practice-offer"}), occurred_at, key,
    )


def test_offer_event_refreshes_expired_historical_authority(db):
    ctx, practice = _create_live_practice_context(db)
    offer = one(
        db,
        "SELECT id,authorization_check_id FROM exercise_service_offers "
        "WHERE id=%s",
        (practice["source_offer_id"],),
    )
    _age_authorization_checks(db, offer["authorization_check_id"])
    event_key = str(uuid4())
    occurred_at = one(db, "SELECT clock_timestamp() AS value")["value"]
    event = _offer_delivery_event(
        db, ctx, offer["id"], event_key, occurred_at
    )
    replay = _offer_delivery_event(
        db, ctx, offer["id"], event_key, occurred_at
    )
    assert replay["id"] == event["id"]
    assert one(
        db,
        "SELECT count(*) AS count FROM exercise_authorization_checks "
        "WHERE acquisition_principal_id=%s AND operation_kind="
        "'catalog_assignment' AND checked_at>clock_timestamp()-interval "
        "'5 minutes'",
        (ctx["owner"],),
    )["count"] >= 2


@pytest.mark.parametrize(
    "revocation",
    ("service_block", "policy_retired", "source_deleted", "service_closed"),
)
def test_offer_event_creation_and_replay_reject_current_revocation(
    db, revocation,
):
    ctx, practice = _create_live_practice_context(db)
    offer = one(
        db,
        "SELECT id FROM exercise_service_offers WHERE id=%s",
        (practice["source_offer_id"],),
    )
    event_key = str(uuid4())
    occurred_at = one(db, "SELECT clock_timestamp() AS value")["value"]
    _offer_delivery_event(db, ctx, offer["id"], event_key, occurred_at)
    before = one(
        db,
        "SELECT count(*) AS count FROM exercise_service_offer_events "
        "WHERE offer_id=%s",
        (offer["id"],),
    )["count"]
    if revocation == "service_block":
        execute(
            db,
            "INSERT INTO processing_service_blocks("
            "acquisition_principal_id,effective_at) "
            "VALUES (%s,clock_timestamp())",
            (ctx["owner"],),
        )
    elif revocation == "policy_retired":
        execute(
            db,
            "UPDATE processing_policy_versions SET status='retired',"
            "retired_at=clock_timestamp() WHERE id=%s",
            (ctx["policy"],),
        )
    elif revocation == "source_deleted":
        execute(
            db,
            "UPDATE processing_audio_objects SET deleted_at=clock_timestamp() "
            "WHERE id=(SELECT processing_audio_object_id "
            "FROM exercise_audio_lineages WHERE id=%s)",
            (practice["source_audio_lineage_id"],),
        )
    else:
        execute(
            db,
            "UPDATE mlc3_service_contracts SET state='retired',"
            "retired_at=clock_timestamp() WHERE contract_version="
            "'mlc3-first-client-service-v1'",
        )
    with pytest.raises(psycopg2.Error):
        _offer_delivery_event(db, ctx, offer["id"], event_key, occurred_at)
    with pytest.raises(psycopg2.Error):
        _offer_delivery_event(
            db, ctx, offer["id"], str(uuid4()),
            one(db, "SELECT clock_timestamp() AS value")["value"],
        )
    assert one(
        db,
        "SELECT count(*) AS count FROM exercise_service_offer_events "
        "WHERE offer_id=%s",
        (offer["id"],),
    )["count"] == before


@pytest.mark.parametrize("mutation", ("service_block", "source_deleted"))
def test_offer_event_revalidates_after_idempotency_lock_contention(
    db, mutation,
):
    ctx, practice = _create_live_practice_context(db)
    offer_id = practice["source_offer_id"]
    event_key = str(uuid4())
    occurred_at = one(db, "SELECT clock_timestamp() AS value")["value"]
    holder = psycopg2.connect(DSN)
    waiter = psycopg2.connect(DSN)
    holder.autocommit = False
    waiter.autocommit = True
    application = "offer_event_wait_" + uuid4().hex
    try:
        with holder.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("exercise-service-offer-event:" + event_key,),
            )
        with waiter.cursor() as cursor:
            cursor.execute("SET application_name=%s", (application,))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                _offer_delivery_event,
                waiter, ctx, offer_id, event_key, occurred_at,
            )
            wait_for_lock(db, application, "advisory")
            if mutation == "service_block":
                execute(
                    db,
                    "INSERT INTO processing_service_blocks("
                    "acquisition_principal_id,effective_at) "
                    "VALUES (%s,clock_timestamp())",
                    (ctx["owner"],),
                )
            else:
                execute(
                    db,
                    "UPDATE processing_audio_objects "
                    "SET deleted_at=clock_timestamp() WHERE id=("
                    "SELECT processing_audio_object_id "
                    "FROM exercise_audio_lineages WHERE id=%s)",
                    (practice["source_audio_lineage_id"],),
                )
            holder.commit()
            with pytest.raises(psycopg2.Error):
                future.result(timeout=5)
        assert one(
            db,
            "SELECT count(*) AS count FROM exercise_service_offer_events "
            "WHERE idempotency_key=%s",
            (event_key,),
        )["count"] == 0
    finally:
        holder.rollback()
        holder.close()
        waiter.close()


def test_source_acquisition_does_not_inherit_later_pooling(db):
    definition = one(
        db,
        "SELECT pg_get_functiondef(%s::regprocedure) AS definition",
        ("public.prepare_feedback_v3_service_context_v1(uuid,uuid,uuid,text)",),
    )["definition"]
    assert "pooled.receipt_id = service.receipt_id" in definition
    assert "pooled.policy_id = service.policy_id" in definition
    assert "pooled.created_at <= source_attempt.created_at" in definition
    assert "source_attempt.authorization_snapshot_id" in definition
    assert "latest" not in definition.lower()


def _provider_result(practice):
    return Json({
        "provider_response_id": "synthetic-whisper-response",
        "transcript": practice["exact_passage"],
        "language": "en",
        "words": [],
        "transcribed_duration_ms": 4000,
    })


def test_expired_transcription_permit_discards_provider_output(db):
    ctx, practice = _create_live_practice_context(db)
    run, media = _prepare_transcription_run(db, ctx, practice)
    execute(
        db,
        "ALTER TABLE exercise_practice_transcription_runs DISABLE TRIGGER "
        "exercise_practice_transcription_runs_immutable",
    )
    execute(
        db,
        "UPDATE exercise_practice_transcription_runs "
        "SET permit_expires_at=authorized_at+interval '1 microsecond' "
        "WHERE id=%s",
        (run["id"],),
    )
    execute(
        db,
        "ALTER TABLE exercise_practice_transcription_runs ENABLE TRIGGER "
        "exercise_practice_transcription_runs_immutable",
    )
    terminal = rpc(
        db, "finalize_exercise_practice_transcription_v1", run["id"],
        ctx["owner"], "finalized", _provider_result(practice), None,
        str(uuid4()),
    )
    assert terminal["status"] == "expired_after_dispatch"
    assert terminal["normalized_output"] is None
    assert terminal["response_sha256"] is None
    assert terminal["transcript_text"] is None
    assert terminal["provider_error_code"] == (
        "PERMIT_EXPIRED_AFTER_DISPATCH"
    )
    with pytest.raises(psycopg2.Error):
        rpc(
            db, "attach_exercise_practice_service_attempt_v1",
            media["recovery"]["id"], media["processing_attempt_id"],
            media["audio_object_id"], media["acquisition_receipt_id"],
            run["id"], practice["exact_passage"], 4000,
            one(db, "SELECT clock_timestamp() AS value")["value"],
            one(db, "SELECT clock_timestamp() AS value")["value"],
            Json({"fixture": True}), str(uuid4()),
        )
    assert one(
        db,
        "SELECT count(*) AS count FROM exercise_practice_attempts "
        "WHERE transcription_run_id=%s",
        (run["id"],),
    )["count"] == 0


@pytest.mark.parametrize("provider_status", ("finalized", "uncertain"))
def test_revocation_after_dispatch_is_sanitized(db, provider_status):
    ctx, practice = _create_live_practice_context(db)
    run, _media = _prepare_transcription_run(db, ctx, practice)
    execute(
        db,
        "INSERT INTO processing_service_blocks("
        "acquisition_principal_id,effective_at) "
        "VALUES (%s,clock_timestamp())",
        (ctx["owner"],),
    )
    terminal = rpc(
        db, "finalize_exercise_practice_transcription_v1", run["id"],
        ctx["owner"], provider_status,
        _provider_result(practice) if provider_status == "finalized" else None,
        None if provider_status == "finalized" else "PROVIDER_TIMEOUT",
        str(uuid4()),
    )
    assert terminal["status"] == "revoked_after_dispatch"
    assert terminal["normalized_output"] is None
    assert terminal["response_sha256"] is None
    assert terminal["transcript_text"] is None
    assert terminal["provider_error_code"] == (
        "AUTHORITY_REVOKED_AFTER_DISPATCH"
    )
    assert one(
        db,
        "SELECT count(*) AS count FROM exercise_practice_attempts "
        "WHERE transcription_run_id=%s",
        (run["id"],),
    )["count"] == 0


def test_service_contract_closure_after_dispatch_is_sanitized(db):
    ctx, practice = _create_live_practice_context(db)
    run, _media = _prepare_transcription_run(db, ctx, practice)
    execute(
        db,
        "UPDATE mlc3_service_contracts SET state='retired',"
        "retired_at=clock_timestamp() "
        "WHERE contract_version='mlc3-first-client-service-v1'",
    )
    terminal = rpc(
        db, "finalize_exercise_practice_transcription_v1", run["id"],
        ctx["owner"], "finalized", _provider_result(practice), None,
        str(uuid4()),
    )
    assert terminal["status"] == "revoked_after_dispatch"
    assert terminal["normalized_output"] is None
    assert terminal["response_sha256"] is None
    assert terminal["transcript_text"] is None
    assert terminal["provider_error_code"] == (
        "AUTHORITY_REVOKED_AFTER_DISPATCH"
    )
    assert one(
        db,
        "SELECT count(*) AS count FROM exercise_practice_attempts "
        "WHERE transcription_run_id=%s",
        (run["id"],),
    )["count"] == 0


def test_finalized_practice_submission_replays_without_new_dispatch(db):
    ctx, practice = _create_live_practice_context(db)
    run, media = _prepare_transcription_run(db, ctx, practice)
    terminal = rpc(
        db, "finalize_exercise_practice_transcription_v1", run["id"],
        ctx["owner"], "finalized", _provider_result(practice), None,
        str(uuid4()),
    )
    execute(
        db,
        "UPDATE exercise_practice_upload_recoveries "
        "SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",
        (media["recovery"]["id"],),
    )
    finalized_replay_ack = rpc(
        db, "ack_exercise_practice_service_upload_v1",
        media["recovery"]["id"], ctx["owner"], "7" * 64, 4096,
        str(uuid4()),
    )
    assert finalized_replay_ack["status"] == "write_acknowledged"
    rpc(
        db, "finalize_exercise_practice_service_media_v1",
        media["recovery"]["id"], ctx["owner"],
        media["processing_attempt_id"], media["audio_object_id"],
        "read_after_write_sha256", media["media_finalization_key"],
    )
    captured_at = one(db, "SELECT clock_timestamp() AS value")["value"]
    attempt_key = str(uuid4())
    conditions = Json({"fixture": "http-replay"})
    attempt = rpc(
        db, "attach_exercise_practice_service_attempt_v1",
        media["recovery"]["id"], media["processing_attempt_id"],
        media["audio_object_id"], media["acquisition_receipt_id"],
        terminal["id"], practice["exact_passage"], 4000,
        captured_at, captured_at, conditions, attempt_key,
    )
    replayed_ack = rpc(
        db, "ack_exercise_practice_service_upload_v1",
        media["recovery"]["id"], ctx["owner"], "7" * 64, 4096,
        str(uuid4()),
    )
    assert replayed_ack["status"] == "attached"
    replayed_media = rpc(
        db, "finalize_exercise_practice_service_media_v1",
        media["recovery"]["id"], ctx["owner"],
        media["processing_attempt_id"], media["audio_object_id"],
        "read_after_write_sha256", media["media_finalization_key"],
    )["finalize_exercise_practice_service_media_v1"]
    assert replayed_media["processing_audio_object_id"] == (
        media["audio_object_id"]
    )
    replayed_run = rpc(
        db, "authorize_exercise_practice_transcription_v1",
        media["recovery"]["id"], ctx["owner"],
        media["processing_attempt_id"], media["audio_object_id"],
        media["acquisition_receipt_id"], "openai", "whisper-1",
        "disfluent-preservation-v1", "auto-detect-no-hint-v1", None,
        "whisper-verbose-word-timestamps-v1", media["transcription_key"],
    )
    assert replayed_run["id"] == terminal["id"]
    replayed_attempt = rpc(
        db, "attach_exercise_practice_service_attempt_v1",
        media["recovery"]["id"], media["processing_attempt_id"],
        media["audio_object_id"], media["acquisition_receipt_id"],
        terminal["id"], practice["exact_passage"], 4000,
        captured_at, captured_at, conditions, attempt_key,
    )
    assert replayed_attempt["id"] == attempt["id"]
    assert one(
        db,
        "SELECT count(*) AS count FROM exercise_practice_transcription_runs "
        "WHERE upload_recovery_id=%s",
        (media["recovery"]["id"],),
    )["count"] == 1


def test_lost_terminal_write_has_durable_reconciliation(db):
    ctx, practice = _create_live_practice_context(db)
    run, media = _prepare_transcription_run(db, ctx, practice)
    reconciliation_key = str(uuid4())
    execute(
        db,
        "INSERT INTO processing_service_blocks("
        "acquisition_principal_id,effective_at) "
        "VALUES (%s,clock_timestamp())",
        (ctx["owner"],),
    )
    terminal = rpc(
        db, "reconcile_exercise_practice_transcription_request_v1",
        media["recovery"]["id"], ctx["owner"],
        media["transcription_key"], reconciliation_key,
    )
    assert terminal["status"] == "outcome_uncommitted"
    assert terminal["normalized_output"] is None
    assert terminal["transcript_text"] is None
    replay = rpc(
        db, "reconcile_exercise_practice_transcription_request_v1",
        media["recovery"]["id"], ctx["owner"],
        media["transcription_key"], reconciliation_key,
    )
    assert replay["id"] == terminal["id"]
    assert replay["run_sha256"] == terminal["run_sha256"]
    with pytest.raises(psycopg2.Error):
        rpc(
            db, "reconcile_exercise_practice_transcription_v1", run["id"],
            ctx["owner"], str(uuid4()),
        )


def test_permit_expiry_during_finalization_contention_fails_closed(db):
    ctx, practice = _create_live_practice_context(db)
    run, _media = _prepare_transcription_run(db, ctx, practice)
    execute(
        db,
        "ALTER TABLE exercise_practice_transcription_runs DISABLE TRIGGER "
        "exercise_practice_transcription_runs_immutable",
    )
    execute(
        db,
        "UPDATE exercise_practice_transcription_runs "
        "SET permit_expires_at=authorized_at+interval '1 second' WHERE id=%s",
        (run["id"],),
    )
    execute(
        db,
        "ALTER TABLE exercise_practice_transcription_runs ENABLE TRIGGER "
        "exercise_practice_transcription_runs_immutable",
    )
    holder = psycopg2.connect(DSN)
    waiter = psycopg2.connect(DSN)
    holder.autocommit = False
    waiter.autocommit = True
    try:
        with holder.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM exercise_practice_transcription_runs "
                "WHERE id=%s FOR UPDATE", (run["id"],),
            )

        def finalize_waiting_run():
            return rpc(
                waiter, "finalize_exercise_practice_transcription_v1",
                run["id"], ctx["owner"], "finalized",
                _provider_result(practice), None, str(uuid4()),
            )

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(finalize_waiting_run)
            time.sleep(1.2)
            assert not future.done()
            holder.commit()
            terminal = future.result(timeout=5)
        assert terminal["status"] == "expired_after_dispatch"
        assert terminal["normalized_output"] is None
        assert terminal["transcript_text"] is None
    finally:
        holder.rollback()
        holder.close()
        waiter.close()


def test_deletion_winning_before_dispatch_rejects_provider_permit(db):
    ctx, practice = _create_live_practice_context(db)
    run, media = _prepare_transcription_run(
        db, ctx, practice, dispatch=False
    )
    holder = psycopg2.connect(DSN)
    waiter = psycopg2.connect(DSN)
    holder.autocommit = False
    waiter.autocommit = True
    try:
        with holder.cursor() as cursor:
            cursor.execute(
                "UPDATE processing_audio_objects "
                "SET deleted_at=clock_timestamp() WHERE id=%s",
                (media["audio_object_id"],),
            )

        def dispatch_waiting_run():
            return rpc(
                waiter,
                "mark_exercise_practice_transcription_dispatched_v1",
                run["id"], ctx["owner"],
                media["transcription_key"] + ":dispatch",
            )

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(dispatch_waiting_run)
            time.sleep(0.2)
            assert not future.done()
            holder.commit()
            with pytest.raises(psycopg2.Error):
                future.result(timeout=5)
        persisted = one(
            db,
            "SELECT status,normalized_output,transcript_text "
            "FROM exercise_practice_transcription_runs WHERE id=%s",
            (run["id"],),
        )
        assert persisted == {
            "status": "authorized",
            "normalized_output": None,
            "transcript_text": None,
        }
    finally:
        holder.rollback()
        holder.close()
        waiter.close()


def test_deletion_winning_during_finalization_discards_output(db):
    ctx, practice = _create_live_practice_context(db)
    run, media = _prepare_transcription_run(db, ctx, practice)
    holder = psycopg2.connect(DSN)
    waiter = psycopg2.connect(DSN)
    holder.autocommit = False
    waiter.autocommit = True
    try:
        with holder.cursor() as cursor:
            cursor.execute(
                "UPDATE processing_audio_objects "
                "SET deleted_at=clock_timestamp() WHERE id=%s",
                (media["audio_object_id"],),
            )

        def finalize_waiting_run():
            return rpc(
                waiter, "finalize_exercise_practice_transcription_v1",
                run["id"], ctx["owner"], "finalized",
                _provider_result(practice), None, str(uuid4()),
            )

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(finalize_waiting_run)
            time.sleep(0.2)
            assert not future.done()
            holder.commit()
            terminal = future.result(timeout=5)
        assert terminal["status"] == "revoked_after_dispatch"
        assert terminal["normalized_output"] is None
        assert terminal["response_sha256"] is None
        assert terminal["transcript_text"] is None
        assert one(
            db,
            "SELECT count(*) AS count FROM exercise_practice_attempts "
            "WHERE transcription_run_id=%s",
            (run["id"],),
        )["count"] == 0
    finally:
        holder.rollback()
        holder.close()
        waiter.close()


def test_unexpected_authority_lock_failure_is_not_false_revocation(db):
    ctx, practice = _create_live_practice_context(db)
    run, _media = _prepare_transcription_run(db, ctx, practice)
    holder = psycopg2.connect(DSN)
    waiter = psycopg2.connect(DSN)
    holder.autocommit = False
    waiter.autocommit = True
    try:
        with holder.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"mlc3-service-principal:{ctx['owner']}",),
            )
        with waiter.cursor() as cursor:
            cursor.execute("SET lock_timeout='200ms'")
        with pytest.raises(psycopg2.Error):
            rpc(
                waiter, "finalize_exercise_practice_transcription_v1",
                run["id"], ctx["owner"], "finalized",
                _provider_result(practice), None, str(uuid4()),
            )
        persisted = one(
            db,
            "SELECT status,provider_error_code,normalized_output "
            "FROM exercise_practice_transcription_runs WHERE id=%s",
            (run["id"],),
        )
        assert persisted == {
            "status": "dispatched",
            "provider_error_code": None,
            "normalized_output": None,
        }
        holder.rollback()
        terminal = rpc(
            db, "reconcile_exercise_practice_transcription_v1", run["id"],
            ctx["owner"], str(uuid4()),
        )
        assert terminal["status"] == "outcome_uncommitted"
    finally:
        holder.rollback()
        holder.close()
        waiter.close()


def test_practice_passage_and_window_are_server_derived(db):
    definition = one(
        db,
        "SELECT pg_get_functiondef(%s::regprocedure) AS definition",
        ("public.create_exercise_practice_service_session_v1(uuid,uuid,uuid,text)",),
    )["definition"]
    assert "exact_passage := btrim(source_evidence.exact_text)" in definition
    assert "opens_at := clock_timestamp()" in definition
    assert "closes_at := opens_at + INTERVAL '24 hours'" in definition
    assert "p_exact_passage" not in definition
    assert "p_opens_at" not in definition
    assert "p_closes_at" not in definition


def test_first_valid_selection_uses_only_session_validity_contract(db):
    definition = one(
        db,
        "SELECT pg_get_functiondef(%s::regprocedure) AS definition",
        ("public.freeze_exercise_practice_service_selection_v1(uuid,uuid,integer,integer,text)",),
    )["definition"]
    assert definition.count("validity_contract_version") >= 3
    assert definition.count("practice.validity_contract_version") >= 3


def test_expired_confidence_assignments_create_successor_revisions(db):
    definition = one(
        db,
        "SELECT pg_get_functiondef(%s::regprocedure) AS definition",
        ("public.freeze_exercise_service_blind_review_set_v1(uuid,uuid,text)",),
    )["definition"]
    assert "assignment_revision" in definition
    assert "supersedes_assignment_id" in definition
    assert "expired_unanswered_successor" in definition
    assert "source_judged" in definition
    assert "practice_judged" in definition
    assert "review_revision" in definition
