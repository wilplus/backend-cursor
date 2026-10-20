"""
STORY    As a speaker, I want a practice recording I delete to be impossible to
         send for transcription, even if the deletion lands mid-dispatch, and my
         practice records never to become training data, so that deletion
         really stops processing.
OUTCOME
  O1  A deletion that commits while dispatch is waiting makes the dispatch
      fail, and no transcript is stored.
  O2  The tables of practice actually served to speakers can never be marked
      as training data (a database rule forbids it).
PROVES   O1 -> test_deletion_winning_before_dispatch_rejects_provider_permit
         O2 -> test_served_records_remain_dataset_ineligible_by_constraint
WHY      Rehearsal database only; the service contract stays disabled.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extras import Json

from tests.test_mlc3_dark_assignments_postgres import (
    assign,
    make_context,
    rpc,
)
from tests.test_mlc3_n1_source_pattern_postgres import profile, source_pattern

DSN = os.environ.get("MLC3_FIRST_CLIENT_REHEARSAL_DSN", "")
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
