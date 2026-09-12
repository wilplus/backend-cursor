"""Executable checks run only against a disposable production-shaped clone."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
from uuid import uuid4

import psycopg2
from psycopg2.extras import Json
import pytest

from tests import test_coach_guidance_delivery_d3_postgres as d3
from tests import test_mlc3_coach_inline_authoring_d5_postgres as d5
from tests import test_mlc3_first_client_service_postgres as d2
from tests.test_mlc3_dark_assignments_postgres import assign, make_context
from tests.test_mlc3_general_user_service_d4_postgres import (
    CAPACITY,
    _activate_contract,
    _enable_coach_review_for_fixture,
    one,
    rows,
    service_json_rpc,
    service_rpc,
)
from tests.test_mlc3_n1_source_pattern_postgres import profile, source_pattern
from tests.test_rooting_phrase_qualification_postgres import (
    _direct_qualification,
    _v3_context,
)

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="disposable rehearsal only")
SQL = (Path(__file__).resolve().parents[1] / "migrations/pending/add_confident_moment_coaching_bundle_v1.sql").read_text()
FOUNDATION_SQL = (
    Path(__file__).resolve().parents[1] / "migrations/add_mlc2_foundation.sql"
).read_text()


def _install_released_render_ack(db):
    """Install the exact released dependency omitted by the narrowed clone."""
    declaration = "CREATE OR REPLACE FUNCTION public.ack_mlc2_rendered_exposure_v1("
    body = FOUNDATION_SQL.split(declaration, 1)[1].split("\n$$;", 1)[0]
    with db.cursor() as cur:
        cur.execute(declaration + body + "\n$$;")


@pytest.fixture
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(**parsed)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def _positive_projection_context(db):
    context = make_context(db)
    source = source_pattern(db, context, "confident")
    for version in context["versions"]:
        profile(db, version["id"], ["confident"])
    db.commit()
    assignment = assign(db, context)
    service_rpc(
        db,
        "freeze_exercise_n1_pattern_snapshot_v1",
        assignment["id"],
        source["id"],
        str(uuid4()),
    )
    _activate_contract(db)
    _enable_coach_review_for_fixture(db, context)
    user_id = one(
        db,
        "SELECT user_id FROM owner_principals WHERE id=%s",
        (context["owner"],),
    )["user_id"]
    latest = one(
        db,
        "SELECT rollout_state FROM mlc3_service_rollout_revisions "
        "ORDER BY revision_number DESC LIMIT 1",
    )["rollout_state"]
    if latest == "generally_available":
        rows(
            db,
            "SELECT halt_mlc3_service_rollout_v1(%s,%s)",
            ("d11-fixture-reset", uuid4().hex * 2),
        )
    capacity_hash = one(
        db,
        "SELECT exercise_json_sha256_v1(%s::jsonb) AS value",
        (Json(CAPACITY),),
    )["value"]
    evidence_hash = uuid4().hex * 2
    risk = one(
        db,
        "SELECT * FROM register_mlc3_activation_risk_decision_v1("
        "%s,%s,%s,%s,%s,%s,clock_timestamp()-interval '1 second',%s,%s)",
        (
            "4ee8cc5f1dda8cf5e727fefdaef12a1a96a85d9fcd01c74e8953564026bf1085",
            "a" * 40,
            "b" * 40,
            "D11 synthetic positive projection fixture.",
            capacity_hash,
            user_id,
            "d11-local-test",
            evidence_hash,
        ),
    )
    one(
        db,
        "SELECT * FROM register_mlc3_general_rollout_v2("
        "%s,%s,%s::jsonb,%s::jsonb,%s,clock_timestamp(),%s)",
        (
            context["policy"],
            risk["id"],
            Json(CAPACITY),
            Json({"language": "en-v1", "safety": "safety-v1"}),
            user_id,
            uuid4().hex * 2,
        ),
    )
    rows(
        db,
        "UPDATE processing_authorization_snapshots SET source_recording_id=%s "
        "WHERE id=%s",
        (context["recording"], context["snapshot"]),
    )
    rows(
        db,
        "UPDATE processing_recording_attempts SET authorization_snapshot_id=%s "
        "WHERE id=%s",
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
        db,
        "ensure_mlc3_service_enrollment_v2",
        context["owner"],
        user_id,
        f"d11-enrollment-{uuid4()}",
    )
    feedback = d2._service_membership(db, context)
    return context, feedback


def _feedback_language_context(db):
    d3._install_full_review_shape(db)
    context, feedback = _positive_projection_context(db)
    d3._authorize_coach(db, context)
    candidate_evidence = one(
        db,
        "SELECT evidence_span_id FROM feedback_v3_membership_items "
        "WHERE membership_id=%s AND candidate_id=%s",
        (feedback["membership"]["id"], feedback["candidate_id"]),
    )["evidence_span_id"]
    rows(
        db,
        "INSERT INTO ml_evidence_spans(id,acquisition_principal_id,speaker_id,"
        "project_id,recording_attempt_id,take_id,object_artifact_id,coordinates) "
        "SELECT %s,acquisition_principal_id,speaker_id,project_id,"
        "recording_attempt_id,take_id,object_artifact_id,coordinates "
        "FROM ml_evidence_spans WHERE id=%s",
        (candidate_evidence, context["evidence"]),
    )
    # The N1 setup assignment is terminal and therefore remains frozen only as
    # a typed exclusion in the canonical batch.
    rows(
        db,
        "INSERT INTO ml_review_assignment_events(review_assignment_id,event_kind,"
        "actor_principal_id,idempotency_key) SELECT id,'cancelled',%s,%s "
        "FROM ml_review_assignments WHERE reviewer_principal_id=%s "
        "AND evidence_span_id<>%s ON CONFLICT DO NOTHING",
        (
            context["reviewer"],
            f"d11-terminal-{uuid4()}",
            context["reviewer"],
            candidate_evidence,
        ),
    )
    context["evidence"] = candidate_evidence
    packet = d3._make_packet(db, context)
    batch = d5._batch(db, context)
    judgment = {"judgment_id": d3._judge(db, context, packet, decision="rating_yes")}
    inline = one(
        db,
        "SELECT prepare_coach_inline_guidance_context_v1(%s,%s,%s,%s) payload",
        (context["project"], context["owner"], context["reviewer"], str(uuid4())),
    )["payload"]
    item = next(
        value
        for value in inline["items"]
        if value["review_assignment_id"] == packet["review_assignment_id"]
    )
    batch = {"id": inline["review_batch_id"]}
    grant = {"id": inline["reveal_grant_id"]}
    return context, feedback, batch, grant, judgment, item


def _assert_service_json_rejected(db, name, arguments, match):
    with db.cursor() as cur:
        cur.execute("SAVEPOINT d11_expected_rejection")
        cur.execute("SET LOCAL ROLE service_role")
        try:
            with pytest.raises(psycopg2.Error, match=match):
                cur.execute(
                    f"SELECT public.{name}({','.join(['%s'] * len(arguments))})",
                    arguments,
                )
        finally:
            cur.execute("ROLLBACK TO SAVEPOINT d11_expected_rejection")
            cur.execute("RELEASE SAVEPOINT d11_expected_rejection")


def test_apply_reapply_forced_rls_and_exact_signatures(db):
    with db.cursor() as cur:
        cur.execute(SQL)
        cur.execute(SQL)
        cur.execute("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname=ANY(%s) ORDER BY relname", (["confident_moment_bundle_attachments","root_phrase_coverage_frames","root_phrase_coverage_items","feedback_language_revision_deliveries","confident_moment_bundle_projections","confident_moment_bundle_projection_items"],))
        rows = cur.fetchall()
        assert len(rows) == 6 and all(row[1:] == (True, True) for row in rows)
        cur.execute("SELECT to_regprocedure(%s) IS NOT NULL", ("public.record_root_phrase_product_action_v2(uuid,uuid,uuid,uuid,integer,text,uuid,uuid,uuid,uuid,uuid,uuid,bigint,uuid,uuid,uuid,text,text)",))
        assert cur.fetchone()[0]
        cur.execute("SELECT to_regprocedure(%s) IS NOT NULL", ("public.require_root_phrase_practice_source_live_v1(uuid,uuid,uuid,uuid,uuid)",))
        assert cur.fetchone()[0]
        cur.execute(
            "SELECT pg_get_function_identity_arguments(%s::regprocedure::oid)",
            ("public.prepare_confident_moment_bundle_v1(uuid,uuid,uuid,uuid,uuid,text)",),
        )
        assert "p_bundle_subject_candidate_id uuid" in cur.fetchone()[0]


def test_legacy_root_writers_delegate_exclusively_to_internal_helper(db):
    with db.cursor() as cur:
        cur.execute(SQL)
        for signature in (
            "public.activate_synthetic_root_phrase_v1(uuid,uuid,boolean,boolean,text)",
            "public.remove_synthetic_root_phrase_v1(uuid,integer,integer,uuid,uuid,text)",
        ):
            cur.execute("SELECT pg_get_functiondef(%s::regprocedure)", (signature,))
            body = cur.fetchone()[0]
            assert "transition_ideal_text_root_state_v1" in body
            assert "UPDATE public.ideal_text_part" not in body
            assert "INSERT INTO public.ideal_text_part_revision" not in body
        # A PUBLIC grant would also make each concrete runtime role executable.
        for role in ("anon", "authenticated", "service_role"):
            cur.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')",
                (
                    role,
                    "public.transition_ideal_text_root_state_v1(uuid,uuid,uuid,uuid,bigint,text,text)",
                ),
            )
            assert cur.fetchone()[0] is False


def test_runtime_roles_have_no_direct_writes_or_rpc_execution(db):
    with db.cursor() as cur:
        cur.execute(SQL)
        tables = (
            "confident_moment_bundle_attachments",
            "root_phrase_coverage_frames",
            "root_phrase_coverage_items",
            "feedback_language_revision_deliveries",
            "feedback_revisions",
            "root_phrase_product_actions",
            "confident_moment_bundle_projections",
            "confident_moment_bundle_projection_items",
        )
        for role in ("anon", "authenticated", "service_role"):
            for table in tables:
                for privilege in (
                    "SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE",
                    "REFERENCES", "TRIGGER",
                ):
                    cur.execute(
                        "SELECT has_table_privilege(%s,'public.'||%s,%s)",
                        (role, table, privilege),
                    )
                    assert cur.fetchone()[0] is False
            cur.execute("SELECT has_function_privilege(%s,'public.prepare_confident_moment_bundle_v1(uuid,uuid,uuid,uuid,uuid,text)','EXECUTE')", (role,))
            assert cur.fetchone()[0] is False
            cur.execute("SELECT has_function_privilege(%s,'public.require_root_phrase_practice_source_live_v1(uuid,uuid,uuid,uuid,uuid)','EXECUTE')", (role,))
            assert cur.fetchone()[0] is False
            cur.execute("SELECT has_function_privilege(%s,'public.project_confident_moment_bundles_v1(uuid,uuid,uuid)','EXECUTE')", (role,))
            assert cur.fetchone()[0] is (role == "service_role")
        cur.execute("SELECT has_function_privilege('anon','public.lock_confident_moment_inventory_v1(uuid,uuid,uuid)','EXECUTE')")
        assert cur.fetchone()[0] is False


def test_d11_projection_tables_are_append_only_rpc_only_and_non_learning(db):
    with db.cursor() as cur:
        cur.execute(SQL)
        for table in (
            "confident_moment_bundle_projections",
            "confident_moment_bundle_projection_items",
        ):
            for role in ("anon", "authenticated", "service_role"):
                cur.execute(
                    "SELECT has_table_privilege(%s,'public.'||%s,'SELECT,INSERT,UPDATE,DELETE')",
                    (role, table),
                )
                assert cur.fetchone()[0] is False
            cur.execute(
                "SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=('public.'||%s)::regclass",
                (table,),
            )
            assert cur.fetchone() == (True, True)
            cur.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgrelid=('public.'||%s)::regclass AND NOT tgisinternal AND tgname LIKE '%%append_only'",
                (table,),
            )
            assert cur.fetchone()[0] == 1


def test_structural_false_defaults_append_only_and_exact_foreign_key(db):
    with db.cursor() as cur:
        cur.execute(SQL)
        cur.execute(
            "SELECT table_name,column_name,column_default FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=ANY(%s) "
            "AND column_name IN ('serves_user','dataset_eligible')",
            (
                [
                    "confident_moment_bundle_attachments",
                    "root_phrase_coverage_frames",
                    "root_phrase_coverage_items",
                    "feedback_language_revision_deliveries",
                    "confident_moment_bundle_projections",
                    "confident_moment_bundle_projection_items",
                ],
            ),
        )
        defaults = cur.fetchall()
        assert len(defaults) == 12
        assert all(row[2] == "false" for row in defaults)
        cur.execute(
            "SELECT count(*) FROM pg_trigger WHERE tgrelid=ANY(ARRAY["
            "'public.confident_moment_bundle_attachments'::regclass,"
            "'public.root_phrase_coverage_frames'::regclass,"
            "'public.root_phrase_coverage_items'::regclass,"
            "'public.feedback_language_revision_deliveries'::regclass]) "
            "AND NOT tgisinternal AND tgname LIKE '%append_only'"
        )
        assert cur.fetchone()[0] == 4
        cur.execute(
            "SELECT count(*) FROM pg_trigger "
            "WHERE tgrelid='public.feedback_revisions'::regclass "
            "AND NOT tgisinternal AND tgname='feedback_revisions_append_only'"
        )
        assert cur.fetchone()[0] == 1
        cur.execute(
            "SELECT count(*) FROM pg_indexes WHERE schemaname='public' "
            "AND indexname IN "
            "('feedback_language_coach_revision_original_idx',"
            "'feedback_language_coach_revision_supersedes_idx')"
        )
        assert cur.fetchone()[0] == 2
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid='public.confident_moment_bundle_attachments'::regclass "
            "AND pg_get_constraintdef(oid) LIKE "
            "'FOREIGN KEY (canonical_feedback_presentation_id, attached_candidate_id)%'"
        )
        assert cur.fetchone() is not None
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid='public.root_phrase_product_actions'::regclass "
            "AND conname='root_phrase_product_action_v2_source_matrix_check'"
        )
        source_matrix = cur.fetchone()[0]
        assert "source_target_speaker_binding_id" in source_matrix
        assert "practice_target_speaker_binding_id" in source_matrix
        assert "practice_guard_sha256" in source_matrix


def test_failed_statement_leaves_no_partial_row(db):
    with db.cursor() as cur:
        cur.execute(SQL)
        cur.execute("BEGIN")
        cur.execute("SAVEPOINT negative")
        with pytest.raises(psycopg2.Error):
            cur.execute("INSERT INTO public.root_phrase_coverage_frames(id) VALUES(gen_random_uuid())")
        cur.execute("ROLLBACK TO SAVEPOINT negative")
        cur.execute("SELECT count(*) FROM public.root_phrase_coverage_frames")
        assert cur.fetchone()[0] == 0


def test_d6_source_matrix_and_internal_practice_guard_fail_before_writes(db):
    with db.cursor() as cur:
        cur.execute(SQL)
        cur.execute("BEGIN")
        cur.execute("SELECT count(*) FROM public.root_phrase_product_actions")
        before = cur.fetchone()[0]
        cur.execute("SAVEPOINT invalid_matrix")
        with pytest.raises(psycopg2.Error, match="ROOTING_PHRASE_SOURCE_COMBINATION_INVALID"):
            cur.execute(
                "SELECT public.record_root_phrase_product_action_v2("
                "gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),"
                "gen_random_uuid(),0,'activate_automatic_root',NULL,NULL,NULL,"
                "NULL,NULL,NULL,NULL,NULL,NULL,NULL,"
                "'rooting-coverage-30-80-100-v1','invalid-matrix')"
            )
        cur.execute("ROLLBACK TO SAVEPOINT invalid_matrix")
        cur.execute("SAVEPOINT invalid_practice")
        with pytest.raises(psycopg2.Error, match="ROOTING_PHRASE_PRACTICE_SOURCE_INVALID"):
            cur.execute(
                "SELECT public.require_root_phrase_practice_source_live_v1("
                "gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),NULL,NULL)"
            )
        cur.execute("ROLLBACK TO SAVEPOINT invalid_practice")
        cur.execute("SELECT count(*) FROM public.root_phrase_product_actions")
        assert cur.fetchone()[0] == before


def test_d6_runtime_role_cannot_invoke_root_writers(db):
    with db.cursor() as cur:
        cur.execute(SQL)
        cur.execute("BEGIN")
        cur.execute("SAVEPOINT runtime_denial")
        cur.execute("SET LOCAL ROLE service_role")
        with pytest.raises(psycopg2.Error, match="permission denied"):
            cur.execute(
                "SELECT public.record_root_phrase_product_action_v2("
                "gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),"
                "gen_random_uuid(),0,'remove_current_root',NULL,NULL,NULL,NULL,"
                "NULL,NULL,NULL,NULL,NULL,NULL,"
                "'rooting-coverage-30-80-100-v1','runtime-denied')"
            )
        cur.execute("ROLLBACK TO SAVEPOINT runtime_denial")


def test_d11_exact_writer_and_trigger_registry_is_installed(db):
    with db.cursor() as cur:
        cur.execute(SQL)
        for signature, marker in (
            (
                "public.freeze_synthetic_feedback_v3_membership_v1(uuid,uuid,uuid,uuid,uuid,text,jsonb,text,text)",
                "D11 writer: synthetic membership",
            ),
            (
                "public.freeze_feedback_v3_service_membership_v1(uuid,uuid,uuid,uuid,uuid,text,jsonb,text)",
                "D11 writer: service membership",
            ),
            (
                "public.publish_ideal_text_document_snapshot_v1(text,text,uuid,uuid,uuid,integer,bigint,text,jsonb,jsonb)",
                "D11 writer: document snapshot",
            ),
            (
                "public.ack_feedback_v3_service_render_v1(uuid,uuid,uuid,uuid,uuid,uuid,text,timestamptz,text,text)",
                "D11 writer: canonical render",
            ),
            (
                "public.accept_phase1_processing_authorization_v1(uuid,text,text,text,text,text,text,boolean,text,text,text,timestamptz,text)",
                "D11 writer: authorization receipt",
            ),
            (
                "public.mark_phase1_storage_object_purged_v1(uuid,text,uuid,text,text,text,text)",
                "D11 writer: object purge",
            ),
            (
                "public.finalize_phase1_purge_v3(uuid,text)",
                "D11 writer: purge finalize",
            ),
        ):
            cur.execute("SELECT pg_get_functiondef(%s::regprocedure)", (signature,))
            assert marker in cur.fetchone()[0]
        cur.execute(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND "
            "tgname=ANY(%s) ORDER BY tgname",
            (
                [
                    "coach_ideal_text_advances_document_generation",
                    "user_ideal_edit_advances_document_generation",
                    "ideal_text_part_advances_document_generation",
                    "ready_take_advances_ideal_text_document_generation",
                    "data_purge_requests_mlc3_service_serialization",
                    "processing_audio_deletion_mlc3_serialization",
                    "processing_audio_object_mlc3_serialization",
                    "feedback_v3_membership_complete",
                ],
            ),
        )
        assert len(cur.fetchall()) == 8
        for signature in (
            "public.activate_synthetic_root_phrase_v1(uuid,uuid,boolean,boolean,text)",
            "public.remove_synthetic_root_phrase_v1(uuid,integer,integer,uuid,uuid,text)",
        ):
            cur.execute("SELECT pg_get_functiondef(%s::regprocedure)", (signature,))
            body = cur.fetchone()[0]
            assert "D11 legacy root writer: global inventory before root block" in body
            assert body.index("lock_confident_moment_inventory_v1") < body.index(
                "'root-block:'"
            )


def test_d11_positive_projection_is_complete_hashed_and_exactly_replayed(db):
    with db.cursor() as cur:
        cur.execute(SQL)
    context, feedback = _positive_projection_context(db)
    with db.cursor() as cur:
        cur.execute(
            "SELECT public.prepare_confident_moment_bundle_v1("
            "%s,%s,%s,%s,%s,%s)",
            (
                context["owner"],
                context["project"],
                context["take"],
                feedback["membership"]["id"],
                feedback["candidate_id"],
                f"d11-prepare-{uuid4()}",
            ),
        )
    first = service_json_rpc(
        db,
        "project_confident_moment_bundles_v1",
        context["owner"],
        context["project"],
        context["take"],
    )
    replay = service_json_rpc(
        db,
        "project_confident_moment_bundles_v1",
        context["owner"],
        context["project"],
        context["take"],
    )
    assert first == replay
    assert first["bundle_projection"]["bundles"]
    assert first["bundle_projection"]["response_sha256"]
    assert first["confident_moment_summary"]["summary_sha256"]
    encoded = str(first)
    for forbidden in (
        "candidate_score",
        "rank_evidence",
        "coach_judgment",
        "qualification_state",
        "authorization_receipt_id",
    ):
        assert forbidden not in encoded
    assert all(
        bundle["exercise"] is None
        for bundle in first["bundle_projection"]["bundles"]
    )
    with db.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM confident_moment_bundle_projection_items item "
            "JOIN confident_moment_bundle_projections projection "
            "ON projection.id=item.projection_id "
            "WHERE projection.acquisition_principal_id=%s",
            (context["owner"],),
        )
        assert cur.fetchone()[0] == 1


def test_d11_rollout_revocation_during_projection_fails_without_partial_rows(db):
    with db.cursor() as cur:
        cur.execute(SQL)
    context, feedback = _positive_projection_context(db)
    with db.cursor() as cur:
        cur.execute(
            "SELECT public.prepare_confident_moment_bundle_v1("
            "%s,%s,%s,%s,%s,%s)",
            (
                context["owner"],
                context["project"],
                context["take"],
                feedback["membership"]["id"],
                feedback["candidate_id"],
                f"d11-race-prepare-{uuid4()}",
            ),
        )
    db.commit()
    writer = psycopg2.connect(db.dsn)
    writer.autocommit = False
    reader = psycopg2.connect(db.dsn)
    reader.autocommit = False
    try:
        with writer.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended("
                "'mlc3-rollout-policy-v2',0))"
            )
            cur.execute(
                "SELECT halt_mlc3_service_rollout_v1(%s,%s)",
                ("d11-authority-race", uuid4().hex * 2),
            )

        def read_projection():
            with reader.cursor() as cur:
                cur.execute(
                    "SELECT project_confident_moment_bundles_v1(%s,%s,%s)",
                    (context["owner"], context["project"], context["take"]),
                )

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(read_projection)
            time.sleep(0.15)
            assert not future.done()
            writer.commit()
            with pytest.raises(psycopg2.Error):
                future.result(timeout=5)
        reader.rollback()
        with db.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM confident_moment_bundle_projections "
                "WHERE acquisition_principal_id=%s",
                (context["owner"],),
            )
            assert cur.fetchone()[0] == 0
    finally:
        writer.rollback()
        reader.rollback()
        writer.close()
        reader.close()


def test_d11_revision_and_delivery_exact_replay_successor_and_stale_rejection(db):
    with db.cursor() as cur:
        cur.execute(SQL)
    context, feedback, batch, grant, judgment, item = _feedback_language_context(db)
    output_hash = one(
        db,
        "SELECT feedback_candidate_output_sha256_v1(%s) value",
        (feedback["candidate_id"],),
    )["value"]
    revision_key = f"d11-revision-{uuid4()}"
    revision_args = (
        context["reviewer"], batch["id"], grant["id"],
        item["reveal_access_id"], item["review_assignment_id"],
        judgment["judgment_id"], feedback["membership"]["id"],
        feedback["candidate_id"], output_hash, "comment",
        "confidence_explanation", "Keep this delivery clear.", None,
        revision_key,
    )
    first = service_json_rpc(db, "record_feedback_language_coach_revision_v2", *revision_args)
    replay = service_json_rpc(db, "record_feedback_language_coach_revision_v2", *revision_args)
    assert replay == first
    before = one(db, "SELECT count(*) n FROM feedback_revisions")["n"]
    _assert_service_json_rejected(
        db, "record_feedback_language_coach_revision_v2",
        (*revision_args[:11], "Changed payload.", None, revision_key),
        "FEEDBACK_LANGUAGE_REPLAY_CONFLICT",
    )
    assert one(db, "SELECT count(*) n FROM feedback_revisions")["n"] == before
    successor_args = (*revision_args[:11], "A newer clear comment.", first["id"], f"d11-revision-{uuid4()}")
    successor = service_json_rpc(
        db, "record_feedback_language_coach_revision_v2", *successor_args
    )
    assert successor["supersedes_id"] == first["id"]
    _assert_service_json_rejected(
        db, "record_feedback_language_coach_revision_v2", revision_args,
        "FEEDBACK_LANGUAGE_STALE_REVISION",
    )
    assert one(db, "SELECT count(*) n FROM feedback_revisions")["n"] == before + 1

    delivery_key = f"d11-delivery-{uuid4()}"
    delivery_args = (
        successor["id"], context["owner"], context["take"],
        feedback["candidate_id"], None, "schedule", delivery_key,
    )
    delivery = service_json_rpc(db, "transition_feedback_language_delivery_v2", *delivery_args)
    delivery_replay = service_json_rpc(
        db, "transition_feedback_language_delivery_v2", *delivery_args
    )
    assert delivery_replay == delivery
    delivery_before = one(
        db, "SELECT count(*) n FROM feedback_language_revision_deliveries"
    )["n"]
    _assert_service_json_rejected(
        db, "transition_feedback_language_delivery_v2",
        (successor["id"], context["owner"], context["take"],
         feedback["candidate_id"], None, "invalidate", delivery_key),
        "FEEDBACK_LANGUAGE_REPLAY_CONFLICT",
    )
    assert one(
        db, "SELECT count(*) n FROM feedback_language_revision_deliveries"
    )["n"] == delivery_before
    delivery_successor = service_json_rpc(
        db, "transition_feedback_language_delivery_v2",
        successor["id"], context["owner"], context["take"],
        feedback["candidate_id"], delivery["id"], "invalidate",
        f"d11-delivery-{uuid4()}",
    )
    assert delivery_successor["supersedes_delivery_id"] == delivery["id"]
    _assert_service_json_rejected(
        db, "transition_feedback_language_delivery_v2", delivery_args,
        "FEEDBACK_LANGUAGE_DELIVERY_STALE",
    )
    assert one(
        db, "SELECT count(*) n FROM feedback_language_revision_deliveries"
    )["n"] == delivery_before + 1


def _render_projection_context(db):
    _install_released_render_ack(db)
    with db.cursor() as cur:
        cur.execute(SQL)
    context, feedback, batch, grant, judgment, item = _feedback_language_context(db)
    one(
        db,
        "SELECT prepare_confident_moment_bundle_v1(%s,%s,%s,%s,%s,%s) payload",
        (
            context["owner"], context["project"], context["take"],
            feedback["membership"]["id"], feedback["candidate_id"],
            f"render-prepare-{uuid4()}",
        ),
    )
    output_hash = one(
        db, "SELECT feedback_candidate_output_sha256_v1(%s) value",
        (feedback["candidate_id"],),
    )["value"]
    revision = service_json_rpc(
        db, "record_feedback_language_coach_revision_v2",
        context["reviewer"], batch["id"], grant["id"], item["reveal_access_id"],
        item["review_assignment_id"], judgment["judgment_id"],
        feedback["membership"]["id"], feedback["candidate_id"], output_hash,
        "comment", "confidence_explanation", "Keep this delivery clear.", None,
        f"render-revision-{uuid4()}",
    )
    delivery = service_json_rpc(
        db, "transition_feedback_language_delivery_v2",
        revision["id"], context["owner"], context["take"],
        feedback["candidate_id"], None, "schedule", f"render-delivery-{uuid4()}",
    )
    event_id, presentation_id, token = str(uuid4()), str(uuid4()), str(uuid4())
    visible_hash = uuid4().hex * 2
    rows(db, "INSERT INTO ml_semantic_artifacts(id) VALUES(%s)", (revision["id"],))
    rows(
        db,
        "INSERT INTO ml_canonical_events(id,learning_surface_id,feedback_family_id,payload_type) "
        "VALUES(%s,'coach_comment_generation',NULL,'coach_comment_event')",
        (event_id,),
    )
    rows(
        db,
        "INSERT INTO ml_presentations(id,canonical_event_id,learning_surface_id,artifact_id,"
        "actor_principal_id,actor_role,delivery_mode,evaluation_only,visible_payload_sha256,"
        "acknowledgement_token,idempotency_key) VALUES(%s,%s,'coach_comment_generation',%s,%s,"
        "'owner','canary',false,%s,%s,%s)",
        (presentation_id, event_id, revision["id"], context["owner"], visible_hash,
         token, f"render-presentation-{uuid4()}"),
    )
    db.commit()
    return context, feedback, revision, delivery, presentation_id


def test_coach_revision_render_currentness_and_projection_unread_leaf(db):
    _install_released_render_ack(db)
    with db.cursor() as cur:
        cur.execute(SQL)
    context, feedback, batch, grant, judgment, item = _feedback_language_context(db)
    one(
        db,
        "SELECT prepare_confident_moment_bundle_v1(%s,%s,%s,%s,%s,%s) payload",
        (
            context["owner"], context["project"], context["take"],
            feedback["membership"]["id"], feedback["candidate_id"],
            f"render-prepare-{uuid4()}",
        ),
    )
    output_hash = one(
        db,
        "SELECT feedback_candidate_output_sha256_v1(%s) value",
        (feedback["candidate_id"],),
    )["value"]
    revision = service_json_rpc(
        db, "record_feedback_language_coach_revision_v2",
        context["reviewer"], batch["id"], grant["id"],
        item["reveal_access_id"], item["review_assignment_id"],
        judgment["judgment_id"], feedback["membership"]["id"],
        feedback["candidate_id"], output_hash, "comment",
        "confidence_explanation", "Keep this delivery clear.", None,
        f"render-revision-{uuid4()}",
    )
    delivery_a = service_json_rpc(
        db, "transition_feedback_language_delivery_v2",
        revision["id"], context["owner"], context["take"],
        feedback["candidate_id"], None, "schedule", f"render-delivery-{uuid4()}",
    )
    delivery_b = service_json_rpc(
        db, "transition_feedback_language_delivery_v2",
        revision["id"], context["owner"], context["take"],
        feedback["candidate_id"], delivery_a["id"], "schedule",
        f"render-delivery-{uuid4()}",
    )
    event_id, presentation_id, token = str(uuid4()), str(uuid4()), str(uuid4())
    visible_hash = uuid4().hex * 2
    rows(db, "INSERT INTO ml_semantic_artifacts(id) VALUES(%s)", (revision["id"],))
    rows(
        db,
        "INSERT INTO ml_canonical_events(id,learning_surface_id,feedback_family_id,payload_type) "
        "VALUES(%s,'coach_comment_generation',NULL,'coach_comment_event')",
        (event_id,),
    )
    rows(
        db,
        "INSERT INTO ml_presentations(id,canonical_event_id,learning_surface_id,artifact_id,"
        "actor_principal_id,actor_role,delivery_mode,evaluation_only,visible_payload_sha256,"
        "acknowledgement_token,idempotency_key) VALUES(%s,%s,'coach_comment_generation',%s,%s,"
        "'owner','canary',false,%s,%s,%s)",
        (
            presentation_id, event_id, revision["id"], context["owner"],
            visible_hash, token, f"render-presentation-{uuid4()}",
        ),
    )
    before_count = one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"]
    _assert_service_json_rejected(
        db, "ack_feedback_language_revision_render_v1",
        (
            context["owner"], delivery_a["id"], presentation_id, str(uuid4()),
            f"render-stale-{uuid4()}",
        ),
        "no rows|FEEDBACK_LANGUAGE",
    )
    assert one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"] == before_count

    unread_projection = service_json_rpc(
        db, "project_confident_moment_bundles_v1",
        context["owner"], context["project"], context["take"],
    )
    assert unread_projection["bundle_projection"]["bundles"][0]["coach_update"]["unread"] is True
    render_instance, render_key = str(uuid4()), f"render-current-{uuid4()}"
    render_args = (
        context["owner"], delivery_b["id"], presentation_id, render_instance,
        render_key,
    )
    wording_before = one(
        db,
        "SELECT count(*) n,min(revision_sha256) revision_hash FROM feedback_revisions "
        "WHERE id=%s",
        (revision["id"],),
    )
    rendered = service_json_rpc(
        db, "ack_feedback_language_revision_render_v1", *render_args
    )
    assert service_json_rpc(
        db, "ack_feedback_language_revision_render_v1", *render_args
    ) == rendered
    assert one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"] == before_count + 1
    assert one(
        db,
        "SELECT count(*) n,min(revision_sha256) revision_hash FROM feedback_revisions "
        "WHERE id=%s",
        (revision["id"],),
    ) == wording_before
    read_projection = service_json_rpc(
        db, "project_confident_moment_bundles_v1",
        context["owner"], context["project"], context["take"],
    )
    assert read_projection["bundle_projection"]["bundles"][0]["coach_update"]["unread"] is False
    assert read_projection["bundle_projection"]["response_sha256"] != unread_projection["bundle_projection"]["response_sha256"]
    assert one(
        db,
        "SELECT rendered_exposure_id=%s AND unread=false ok "
        "FROM confident_moment_bundle_projection_items WHERE projection_id=("
        "SELECT id FROM confident_moment_bundle_projections WHERE response_sha256=%s)",
        (rendered["id"], read_projection["bundle_projection"]["response_sha256"]),
    )["ok"] is True

    invalidated = service_json_rpc(
        db, "transition_feedback_language_delivery_v2",
        revision["id"], context["owner"], context["take"],
        feedback["candidate_id"], delivery_b["id"], "invalidate",
        f"render-delivery-{uuid4()}",
    )
    assert invalidated["delivery_state"] == "invalidated"
    _assert_service_json_rejected(
        db, "ack_feedback_language_revision_render_v1",
        (
            context["owner"], delivery_b["id"], presentation_id, str(uuid4()),
            f"render-invalidated-{uuid4()}",
        ),
        "no rows|FEEDBACK_LANGUAGE",
    )
    assert one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"] == before_count + 1


@pytest.mark.parametrize("first_committer", ["projection", "render"])
def test_projection_and_render_serialize_in_both_commit_orders(db, first_committer):
    context, _feedback, _revision, delivery, presentation_id = (
        _render_projection_context(db)
    )
    prior = service_json_rpc(
        db, "project_confident_moment_bundles_v1",
        context["owner"], context["project"], context["take"],
    )
    assert prior["bundle_projection"]["bundles"][0]["coach_update"]["unread"] is True
    db.commit()
    first = psycopg2.connect(db.dsn)
    second = psycopg2.connect(db.dsn)
    first.autocommit = False
    second.autocommit = False
    render_args = (
        context["owner"], delivery["id"], presentation_id, str(uuid4()),
        f"render-race-{uuid4()}",
    )

    def render(connection):
        with connection.cursor() as cur:
            cur.execute("SET ROLE service_role")
            cur.execute(
                "SELECT public.ack_feedback_language_revision_render_v1(%s,%s,%s,%s,%s)",
                render_args,
            )
            result = cur.fetchone()[0]
            cur.execute("RESET ROLE")
        connection.commit()
        return result

    def project(connection):
        result = service_json_rpc(
            connection, "project_confident_moment_bundles_v1",
            context["owner"], context["project"], context["take"],
        )
        connection.commit()
        return result

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            if first_committer == "projection":
                first_result = service_json_rpc(
                    first, "project_confident_moment_bundles_v1",
                    context["owner"], context["project"], context["take"],
                )
                future = pool.submit(render, second)
                time.sleep(0.15)
                assert not future.done()
                first.commit()
                future.result(timeout=10)
                assert first_result == prior
            else:
                with first.cursor() as cur:
                    cur.execute("SET ROLE service_role")
                    cur.execute(
                        "SELECT public.ack_feedback_language_revision_render_v1(%s,%s,%s,%s,%s)",
                        render_args,
                    )
                    cur.fetchone()
                    cur.execute("RESET ROLE")
                future = pool.submit(project, second)
                time.sleep(0.15)
                assert not future.done()
                first.commit()
                post = future.result(timeout=10)
                assert post["bundle_projection"]["bundles"][0]["coach_update"]["unread"] is False
        final = service_json_rpc(
            db, "project_confident_moment_bundles_v1",
            context["owner"], context["project"], context["take"],
        )
        assert final["bundle_projection"]["bundles"][0]["coach_update"]["unread"] is False
        assert final["bundle_projection"]["response_sha256"] != prior["bundle_projection"]["response_sha256"]
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()


def test_d11_legacy_root_writer_cannot_invert_projection_global_lock_order(db):
    with db.cursor() as cur:
        cur.execute(SQL)
    context = make_context(db)
    # This exact legacy writer operates on historical pre-D4 memberships.
    # Bypass only the later D4 row-promotion trigger while constructing that
    # historical fixture; the function under test and every live leaf guard
    # remain installed and enabled.
    for table in (
        "feedback_v3_memberships",
        "feedback_v3_membership_items",
        "feedback_v3_owner_responses",
    ):
        rows(db, f"ALTER TABLE {table} DISABLE TRIGGER a_mlc3_rollout_lineage_v2")
    try:
        v3 = _v3_context(db, context)
        owner_user, _, qualification = _direct_qualification(db, context, v3)
    finally:
        for table in (
            "feedback_v3_memberships",
            "feedback_v3_membership_items",
            "feedback_v3_owner_responses",
        ):
            rows(db, f"ALTER TABLE {table} ENABLE TRIGGER a_mlc3_rollout_lineage_v2")
    db.commit()
    projection_order = psycopg2.connect(db.dsn)
    projection_order.autocommit = False
    legacy = psycopg2.connect(db.dsn)
    legacy.autocommit = False
    try:
        with projection_order.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended("
                "'mlc3-rollout-policy-v2',0))"
            )

        def activate_legacy():
            with legacy.cursor() as cur:
                cur.execute("SET application_name='d11-legacy-root-order'")
                cur.execute(
                    "SELECT activate_synthetic_root_phrase_v1(%s,%s,true,false,%s)",
                    (qualification["id"], owner_user, f"d11-order-{uuid4()}"),
                )
                return cur.fetchone()[0]

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(activate_legacy)
            deadline = time.monotonic() + 5
            while True:
                with db.cursor() as cur:
                    cur.execute(
                        "SELECT wait_event FROM pg_stat_activity "
                        "WHERE application_name='d11-legacy-root-order'"
                    )
                    waited = cur.fetchone()
                if waited and waited[0] == "advisory":
                    break
                if time.monotonic() >= deadline:
                    raise AssertionError("legacy writer never waited on global lock")
                time.sleep(0.01)
            with projection_order.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout='250ms'")
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    (f"root-block:{context['project']}:0:0",),
                )
            projection_order.rollback()
            assert future.result(timeout=5)["root_action_id"]
            legacy.commit()
    finally:
        projection_order.rollback()
        legacy.rollback()
        projection_order.close()
        legacy.close()
