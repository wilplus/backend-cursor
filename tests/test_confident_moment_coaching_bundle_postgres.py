"""Executable checks run only against a disposable production-shaped clone."""
from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extras import Json

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
    # The legacy N1 helper was written for the narrow pre-MLC2 fixture: it
    # enriches raw_output after inserting the prediction.  Production makes
    # that payload final before the append-only trigger is installed.  Keep
    # the production trigger enabled for every operation under test and relax
    # it only around this one disposable fixture-enrichment statement.
    rows(
        db,
        "ALTER TABLE ml_machine_predictions DISABLE TRIGGER "
        "ml_machine_predictions_append_only",
    )
    try:
        source = source_pattern(db, context, "confident")
    finally:
        rows(
            db,
            "ALTER TABLE ml_machine_predictions ENABLE TRIGGER "
            "ml_machine_predictions_append_only",
        )
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
    # The same legacy narrow helper fills three phase-1 leaf columns after its
    # inserts.  Temporarily suspend only the immutable trigger around each
    # fixture completion; the D11 serializer on processing_audio_objects stays
    # enabled, and every immutable trigger is restored before any RPC/race.
    fixture_updates = (
        (
            "processing_authorization_snapshots",
            "processing_authorization_snapshots_immutable",
            "UPDATE processing_authorization_snapshots SET source_recording_id=%s WHERE id=%s",
            (context["recording"], context["snapshot"]),
        ),
        (
            "processing_recording_attempts",
            "processing_recording_attempts_immutable",
            "UPDATE processing_recording_attempts SET authorization_snapshot_id=%s WHERE id=%s",
            (context["snapshot"], context["take"]),
        ),
        (
            "processing_audio_objects",
            "processing_audio_objects_immutable",
            "UPDATE processing_audio_objects SET verified_at=clock_timestamp() WHERE id=%s",
            (context["object"],),
        ),
    )
    for table_name, trigger_name, statement, parameters in fixture_updates:
        rows(db, f"ALTER TABLE {table_name} DISABLE TRIGGER {trigger_name}")
        try:
            rows(db, statement, parameters)
        finally:
            rows(db, f"ALTER TABLE {table_name} ENABLE TRIGGER {trigger_name}")
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


def _add_selected_feedback_item(db, feedback, family: str, position: int):
    """Add a second frozen-shape item before the bundle is prepared.

    The legacy one-item fixture cannot express the production Manager mixed
    inventory.  This helper copies the exact rollout lineage of that immutable
    fixture item; the two service-row preparation triggers are suspended only
    for this setup insert and restored before any production RPC is called.
    """
    candidate_id, exposure_id = str(uuid4()), str(uuid4())
    original = one(
        db,
        "SELECT item.*,candidate.candidate_set_id,candidate.evidence_span_id "
        "candidate_evidence_id,exposure.selector_version,"
        "exposure.manager_rules_version,exposure.threshold_version,"
        "exposure.input_hash FROM feedback_v3_membership_items item "
        "JOIN feedback_candidates candidate ON candidate.id=item.candidate_id "
        "JOIN feedback_exposures exposure ON exposure.candidate_id=item.candidate_id "
        "AND exposure.candidate_set_id=candidate.candidate_set_id "
        "WHERE item.membership_id=%s AND item.candidate_id=%s",
        (feedback["membership"]["id"], feedback["candidate_id"]),
    )
    candidate_key = f"mixed-{family}-{candidate_id}"
    rows(
        db,
        "INSERT INTO feedback_candidates(id,candidate_set_id,evidence_span_id,"
        "feedback_family,lane,candidate_key,generated_output) VALUES"
        "(%s,%s,%s,%s,%s,%s,%s::jsonb)",
        (
            candidate_id, original["candidate_set_id"],
            original["candidate_evidence_id"], family,
            "verbal" if family == "rewrite_clarity" else "vocal",
            candidate_key,
            Json(
                {"proposed_text": "A clearer fixture sentence."}
                if family == "rewrite_clarity"
                else {"comment": f"{family} fixture output"}
            ),
        ),
    )
    rows(
        db,
        "INSERT INTO feedback_exposures(id,candidate_set_id,candidate_id,"
        "feedback_family,lane,is_selected,position_shown,shown_at,selector_version,"
        "manager_rules_version,threshold_version,input_hash) VALUES"
        "(%s,%s,%s,%s,%s,true,%s,NULL,%s,%s,%s,%s)",
        (
            exposure_id, original["candidate_set_id"], candidate_id, family,
            "verbal" if family == "rewrite_clarity" else "vocal", position,
            original["selector_version"], original["manager_rules_version"],
            original["threshold_version"], original["input_hash"],
        ),
    )
    for trigger in (
        "a_mlc3_rollout_lineage_v2",
        "feedback_v3_membership_items_service_mode",
    ):
        rows(db, f"ALTER TABLE feedback_v3_membership_items DISABLE TRIGGER {trigger}")
    try:
        rows(
            db,
            "INSERT INTO feedback_v3_membership_items(membership_id,"
            "acquisition_principal_id,candidate_id,evidence_span_id,candidate_key,"
            "feedback_family,slide_index,block_key,source_ideal_part_id,snippet_id,"
            "eligibility,exclusion_reason,selected,position_shown,item_sha256,"
            "serves_user,dataset_eligible,operation_mode,service_identity_sha256,"
            "rollout_revision_id,enrollment_revision_id,access_resolver_version,"
            "rollout_identity_sha256) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
            "'eligible',NULL,true,%s,%s,true,false,%s,%s,%s,%s,%s,%s)",
            (
                original["membership_id"], original["acquisition_principal_id"],
                candidate_id, original["evidence_span_id"], candidate_key, family,
                original["slide_index"], original["block_key"],
                original["source_ideal_part_id"], original["snippet_id"], position,
                uuid4().hex * 2, original["operation_mode"],
                original["service_identity_sha256"], original["rollout_revision_id"],
                original["enrollment_revision_id"],
                original["access_resolver_version"],
                original["rollout_identity_sha256"],
            ),
        )
    finally:
        for trigger in reversed((
            "a_mlc3_rollout_lineage_v2",
            "feedback_v3_membership_items_service_mode",
        )):
            rows(db, f"ALTER TABLE feedback_v3_membership_items ENABLE TRIGGER {trigger}")
    return candidate_id


def _feedback_language_context(
    db, mixed_families: tuple[str, ...] | None = None, mixed_first: bool = False,
):
    d3._install_full_review_shape(db)
    context, feedback = _positive_projection_context(db)
    if mixed_families:
        if mixed_first:
            rows(
                db,
                "ALTER TABLE feedback_v3_membership_items DISABLE TRIGGER "
                "feedback_v3_membership_items_append_only",
            )
            try:
                rows(
                    db,
                    "UPDATE feedback_v3_membership_items SET position_shown=%s "
                    "WHERE membership_id=%s AND candidate_id=%s",
                    (
                        len(mixed_families) + 1,
                        feedback["membership"]["id"], feedback["candidate_id"],
                    ),
                )
            finally:
                rows(
                    db,
                    "ALTER TABLE feedback_v3_membership_items ENABLE TRIGGER "
                    "feedback_v3_membership_items_append_only",
                )
        feedback["mixed_candidate_ids"] = {}
        for offset, family in enumerate(mixed_families, start=2):
            position = (
                len(mixed_families) - offset + 2 if mixed_first else offset
            )
            feedback["mixed_candidate_ids"][family] = _add_selected_feedback_item(
                db, feedback, family, position,
            )
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
            cur.execute(
                "SELECT has_function_privilege(%s,"
                "'public.validate_confident_moment_projection_item_v1()',"
                "'EXECUTE')",
                (role,),
            )
            assert cur.fetchone()[0] is False
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
                    "confident_moment_projection_item_lineage_v1",
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
        assert len(cur.fetchall()) == 9
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
    assert all(
        "coach_update" in bundle and bundle["coach_update"] is None
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


def _render_projection_context(db, mixed_first: bool | None = None):
    _install_released_render_ack(db)
    with db.cursor() as cur:
        cur.execute(SQL)
    context, feedback, batch, grant, judgment, item = _feedback_language_context(
        db,
        ("rewrite_clarity", "great_formulation")
        if mixed_first is not None else None,
        bool(mixed_first),
    )
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
    rows(
        db,
        "INSERT INTO ml_canonical_events(id,learning_surface_id,feedback_family_id,payload_type) "
        "VALUES(%s,'coach_comment_generation',NULL,'coach_comment_event')",
        (event_id,),
    )
    rows(
        db,
        "INSERT INTO ml_semantic_artifacts(id,canonical_event_id,learning_surface_id,"
        "pipeline_stage_id,feedback_family_id,evidence_span_id,artifact_type,"
        "semantic_version,content,content_sha256) VALUES(%s,%s,"
        "'coach_comment_generation','generate',NULL,NULL,'coach_comment_final',"
        "'feedback-language-coach-revision-v1',%s::jsonb,%s)",
        (revision["id"], event_id, Json({"text": "Keep this delivery clear."}),
         revision["revision_sha256"]),
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


@pytest.mark.parametrize("mixed_first", [False, True])
@pytest.mark.parametrize("rendered", [False, True])
def test_mixed_attachment_projection_has_no_cross_item_state_inheritance(
    db, mixed_first, rendered,
):
    """A coach comment and machine rephrase remain separate in both canonical
    orders, whether the current coach presentation is rendered or unread."""
    context, _feedback, revision, delivery, presentation_id = (
        _render_projection_context(db, mixed_first=mixed_first)
    )
    if rendered:
        service_json_rpc(
            db,
            "ack_feedback_language_revision_render_v1",
            context["owner"], delivery["id"], presentation_id, str(uuid4()),
            f"mixed-render-{uuid4()}",
        )
    projection = service_json_rpc(
        db,
        "project_confident_moment_bundles_v1",
        context["owner"], context["project"], context["take"],
    )
    bundles = projection["bundle_projection"]["bundles"]
    assert len(bundles) == 1
    bundle = bundles[0]
    assert bundle["comment"] == {
        "output_kind": "comment",
        "comment_purpose": "confidence_explanation",
        "text": "Keep this delivery clear.",
        "origin": "coach",
    }
    assert bundle["rephrase"] == {
        "output_kind": "rephrase",
        "comment_purpose": None,
        "text": "A clearer fixture sentence.",
        "origin": "machine",
    }
    assert bundle["coach_update"] == {
        "current_revision_id": revision["id"],
        "unread": not rendered,
    }
    frozen = rows(
        db,
        "SELECT candidate.feedback_family,item.resolution_state,item.revision_id,"
        "item.delivery_id,item.presentation_id,item.rendered_exposure_id,item.unread "
        "FROM confident_moment_bundle_projection_items item "
        "JOIN confident_moment_bundle_projections projection "
        "ON projection.id=item.projection_id "
        "JOIN feedback_candidates candidate ON candidate.id=item.attached_candidate_id "
        "WHERE projection.response_sha256=%s ORDER BY item.canonical_position",
        (projection["bundle_projection"]["response_sha256"],),
    )
    assert len(frozen) == 3
    coach_item = next(row for row in frozen if row["feedback_family"] == "confident_voice")
    machine_item = next(row for row in frozen if row["feedback_family"] == "rewrite_clarity")
    praise_item = next(row for row in frozen if row["feedback_family"] == "great_formulation")
    assert coach_item["resolution_state"] == "coach_revision"
    assert coach_item["revision_id"] == revision["id"]
    assert coach_item["unread"] is (not rendered)
    assert machine_item["resolution_state"] == "machine_fallback"
    assert machine_item["revision_id"] is None
    assert machine_item["delivery_id"] is None
    assert machine_item["presentation_id"] is None
    assert machine_item["rendered_exposure_id"] is None
    assert machine_item["unread"] is False
    assert praise_item["resolution_state"] == "machine_fallback"
    assert praise_item["revision_id"] is None
    assert praise_item["delivery_id"] is None
    assert praise_item["presentation_id"] is None
    assert praise_item["rendered_exposure_id"] is None
    assert praise_item["unread"] is False
    summary = projection["confident_moment_summary"]["items"]
    assert summary[0]["has_unread_coach_update"] is (not rendered)


def test_projection_relational_trigger_rejects_a_valid_but_swapped_attachment(db):
    """The relational guard, rather than an unrelated FK/shape error, rejects
    a coach item whose otherwise-valid currentness chain is bound to the other
    attachment in the same projection."""
    context, _feedback, _revision, _delivery, _presentation = (
        _render_projection_context(db, mixed_first=False)
    )
    projection = service_json_rpc(
        db, "project_confident_moment_bundles_v1",
        context["owner"], context["project"], context["take"],
    )
    source = one(
        db,
        "SELECT item.*,other.bundle_attachment_id other_attachment_id "
        "FROM confident_moment_bundle_projection_items item "
        "JOIN confident_moment_bundle_projections projection "
        "ON projection.id=item.projection_id "
        "JOIN confident_moment_bundle_projection_items other "
        "ON other.projection_id=item.projection_id AND other.id<>item.id "
        "WHERE projection.response_sha256=%s "
        "AND item.resolution_state='coach_revision' LIMIT 1",
        (projection["bundle_projection"]["response_sha256"],),
    )
    clone_id = str(uuid4())
    with db.cursor() as cur:
        cur.execute("SAVEPOINT swapped_projection")
        cur.execute(
            "INSERT INTO confident_moment_bundle_projections(id,"
            "acquisition_principal_id,project_id,take_id,feedback_membership_id,"
            "document_snapshot_id,document_snapshot_sha256,projection_policy_version,"
            "projection_code_version,stabilized_inventory_sha256,response_sha256,"
            "idempotency_key) SELECT %s,acquisition_principal_id,project_id,take_id,"
            "feedback_membership_id,document_snapshot_id,document_snapshot_sha256,"
            "projection_policy_version,projection_code_version,%s,%s,%s "
            "FROM confident_moment_bundle_projections WHERE id=%s",
            (
                clone_id, uuid4().hex * 2, uuid4().hex * 2,
                f"swapped-projection-{uuid4()}", source["projection_id"],
            ),
        )
        cur.execute(
            "INSERT INTO confident_moment_bundle_projection_items(projection_id,"
            "acquisition_principal_id,bundle_attachment_id,bundle_subject_candidate_id,"
            "attached_candidate_id,anchor_candidate_id,resolution_state,exclusion_reason,"
            "revision_id,delivery_id,presentation_id,rendered_exposure_id,unread,"
            "candidate_output_sha256,output_sha256,canonical_position,exercise_present,"
            "item_sha256) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
            "%s,%s,%s)",
            (
                clone_id, source["acquisition_principal_id"],
                source["other_attachment_id"], source["bundle_subject_candidate_id"],
                source["attached_candidate_id"], source["anchor_candidate_id"],
                source["resolution_state"], source["exclusion_reason"],
                source["revision_id"], source["delivery_id"],
                source["presentation_id"], source["rendered_exposure_id"],
                source["unread"], source["candidate_output_sha256"],
                source["output_sha256"], source["canonical_position"], False,
                uuid4().hex * 2,
            ),
        )
        with pytest.raises(
            psycopg2.Error,
            match="CONFIDENT_MOMENT_PROJECTION_ITEM_LINEAGE_INVALID",
        ):
            cur.execute(
                "SET CONSTRAINTS confident_moment_projection_item_lineage_v1 IMMEDIATE"
            )
        cur.execute("ROLLBACK TO SAVEPOINT swapped_projection")
    assert one(
        db,
        "SELECT count(*) n FROM confident_moment_bundle_projections WHERE id=%s",
        (clone_id,),
    )["n"] == 0


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
    rows(
        db,
        "INSERT INTO ml_canonical_events(id,learning_surface_id,feedback_family_id,payload_type) "
        "VALUES(%s,'coach_comment_generation',NULL,'coach_comment_event')",
        (event_id,),
    )
    rows(
        db,
        "INSERT INTO ml_semantic_artifacts(id,canonical_event_id,learning_surface_id,"
        "pipeline_stage_id,feedback_family_id,evidence_span_id,artifact_type,"
        "semantic_version,content,content_sha256) VALUES(%s,%s,"
        "'coach_comment_generation','generate',NULL,NULL,'coach_comment_final',"
        "'feedback-language-coach-revision-v1',%s::jsonb,%s)",
        (
            revision["id"], event_id,
            Json({"text": "Keep this delivery clear."}),
            revision["revision_sha256"],
        ),
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


def _withdraw_reviewer_access(connection, reviewer_principal_id):
    """Deactivate the exact coach behind a reviewer principal."""
    rows(
        connection,
        "UPDATE coach_users SET is_active=false WHERE lower(email) IN ("
        "SELECT lower(auth_user.email) FROM auth.users auth_user "
        "JOIN owner_principals principal ON principal.user_id=auth_user.id "
        "WHERE principal.id=%s)",
        (reviewer_principal_id,),
    )


def _delete_source_audio(connection, owner_principal_id):
    """Record source deletion through the append-only deletion ledger."""
    purge_request_id = str(uuid4())
    rows(
        connection,
        "INSERT INTO data_purge_requests(id,acquisition_principal_id,state,"
        "trigger_kind,idempotency_key,requested_at) VALUES(%s,%s,'requested',"
        "'user_delete',%s,clock_timestamp())",
        (purge_request_id, owner_principal_id, f"render-purge-{uuid4()}"),
    )
    rows(
        connection,
        "INSERT INTO processing_audio_object_deletion_events("
        "audio_object_id,purge_request_id,acquisition_principal_id,storage_provider,"
        "bucket,object_key,exact_bytes_sha256,evidence_sha256) SELECT id,%s,"
        "acquisition_principal_id,storage_provider,bucket,object_key,exact_bytes_sha256,%s "
        "FROM processing_audio_objects WHERE acquisition_principal_id=%s",
        (purge_request_id, uuid4().hex * 2, owner_principal_id),
    )


def _ack_render(connection, args):
    with connection.cursor() as cur:
        cur.execute("SET ROLE service_role")
        cur.execute(
            "SELECT public.ack_feedback_language_revision_render_v1(%s,%s,%s,%s,%s)",
            args,
        )
        result = cur.fetchone()[0]
        cur.execute("RESET ROLE")
    return result


@pytest.mark.parametrize("withdrawal", ["reviewer_access", "source_deletion"])
@pytest.mark.parametrize("first_committer", ["withdrawal", "render"])
def test_ack_render_revalidates_exact_coach_source_authority_in_both_orders(
    db, withdrawal, first_committer
):
    """D11 4.3 / A3 6: the exposure writer must enforce the same exact coach and
    source validity as the secure projection, before and after the write.

    Withdrawal-wins must create zero exposure.  Render-wins may keep only the
    one exposure it fully validated before the withdrawing writer proceeds.
    """
    context, _feedback, _revision, delivery, presentation_id = (
        _render_projection_context(db)
    )
    db.commit()
    before = one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"]
    render_args = (
        context["owner"], delivery["id"], presentation_id, str(uuid4()),
        f"render-authority-{uuid4()}",
    )
    first = psycopg2.connect(db.dsn)
    second = psycopg2.connect(db.dsn)
    first.autocommit = False
    second.autocommit = False

    def withdraw(connection):
        if withdrawal == "reviewer_access":
            _withdraw_reviewer_access(connection, context["reviewer"])
        else:
            _delete_source_audio(connection, context["owner"])
        connection.commit()

    def render(connection):
        result = _ack_render(connection, render_args)
        connection.commit()
        return result

    try:
        if first_committer == "withdrawal":
            withdraw(first)
            with pytest.raises(psycopg2.Error) as failure:
                render(second)
            message = str(failure.value)
            assert any(
                code in message
                for code in ("FEEDBACK_LANGUAGE", "COACH_GUIDANCE", "MLC3_DUAL_PURPOSE")
            )
            second.rollback()
            assert one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"] == before
        else:
            with ThreadPoolExecutor(max_workers=1) as pool:
                _ack_render(first, render_args)
                future = pool.submit(withdraw, second)
                time.sleep(0.15)
                first.commit()
                future.result(timeout=10)
            assert one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"] == before + 1
            with pytest.raises(psycopg2.Error):
                _ack_render(
                    db,
                    (
                        context["owner"], delivery["id"], presentation_id,
                        str(uuid4()), f"render-authority-{uuid4()}",
                    ),
                )
            db.rollback()
        assert one(
            db,
            "SELECT count(*) n FROM feedback_language_revision_deliveries "
            "WHERE id=%s AND delivery_state<>'invalidated'",
            (delivery["id"],),
        )["n"] == 1
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()


def test_ack_render_exact_replay_is_idempotent_while_authority_unchanged(db):
    """Exact unchanged replay stays effectively-once after the added guards."""
    context, _feedback, _revision, delivery, presentation_id = (
        _render_projection_context(db)
    )
    before = one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"]
    render_args = (
        context["owner"], delivery["id"], presentation_id, str(uuid4()),
        f"render-replay-{uuid4()}",
    )
    first_result = _ack_render(db, render_args)
    assert _ack_render(db, render_args) == first_result
    assert one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"] == before + 1


def test_ack_render_rejects_a_delivery_whose_lineage_is_not_exact_v2(db):
    """A legacy or forked delivery head can never authorise an exposure."""
    context, _feedback, _revision, delivery, presentation_id = (
        _render_projection_context(db)
    )
    before = one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"]
    legacy_delivery_id = str(uuid4())
    rows(
        db,
        "INSERT INTO feedback_language_revision_deliveries("
        "id,revision_id,acquisition_principal_id,recipient_principal_id,target_take_id,"
        "anchor_candidate_id,delivery_state,delivery_revision,"
        "authorization_rollout_revision_id,authorization_enrollment_revision_id,"
        "delivery_sha256,idempotency_key,feedback_membership_id,feedback_candidate_id,"
        "reviewer_principal_id,revision_taxonomy_version,candidate_output_version,"
        "candidate_output_sha256,delivery_subject_sha256,delivery_policy_version) "
        "SELECT %s,revision_id,acquisition_principal_id,recipient_principal_id,"
        "target_take_id,anchor_candidate_id,delivery_state,delivery_revision+100,"
        "authorization_rollout_revision_id,authorization_enrollment_revision_id,"
        "delivery_sha256,%s,feedback_membership_id,feedback_candidate_id,"
        "reviewer_principal_id,revision_taxonomy_version,candidate_output_version,"
        "candidate_output_sha256,delivery_subject_sha256,'feedback-language-delivery-v1' "
        "FROM feedback_language_revision_deliveries WHERE id=%s",
        (legacy_delivery_id, f"legacy-delivery-{uuid4()}", delivery["id"]),
    )
    _assert_service_json_rejected(
        db,
        "ack_feedback_language_revision_render_v1",
        (
            context["owner"], legacy_delivery_id, presentation_id, str(uuid4()),
            f"render-lineage-{uuid4()}",
        ),
        "FEEDBACK_LANGUAGE",
    )
    assert one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"] == before


def _projection_item_columns(db):
    return {
        row["column_name"]
        for row in rows(
            db,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' "
            "AND table_name='confident_moment_bundle_projection_items'",
        )
    }


def test_projection_item_structural_constraints_reject_cross_attachment_leakage(db):
    """D11 5: a projection item's resolution state fully determines which
    currentness leaves it may carry.

    These are the structural backstop for the attachment-scope reset: even if
    the projection body regresses, a machine-only or excluded item can never
    persist a revision, delivery, presentation, rendered exposure, unread flag
    or coach output hash belonging to a different attachment.
    """
    _install_released_render_ack(db)
    with db.cursor() as cur:
        cur.execute(SQL)
    installed = {
        row["conname"]
        for row in rows(
            db,
            "SELECT conname FROM pg_constraint WHERE contype='c' AND conrelid="
            "'public.confident_moment_bundle_projection_items'::regclass",
        )
    }
    assert {
        "confident_moment_projection_item_state_shape_check",
        "confident_moment_projection_item_render_shape_check",
        "confident_moment_projection_item_output_shape_check",
    } <= installed
    assert {"presentation_id", "rendered_exposure_id", "unread"} <= (
        _projection_item_columns(db)
    )

    # Every forbidden shape must be rejected by the database itself.
    forbidden = [
        # machine_fallback carrying another attachment's coach render state
        ("machine_fallback", None, None, None, True),
        # excluded carrying an unread coach flag
        ("excluded", "machine_output_invalid", None, None, True),
        # coach_revision without its own revision identity
        ("coach_revision", None, None, None, False),
    ]
    # The migration file commits itself, so each probe runs in its own
    # transaction and is rolled back after the expected rejection.
    for state, exclusion, revision_id, delivery_id, unread in forbidden:
        with db.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO public.confident_moment_bundle_projection_items("
                    "projection_id,acquisition_principal_id,bundle_attachment_id,"
                    "bundle_subject_candidate_id,attached_candidate_id,"
                    "resolution_state,exclusion_reason,revision_id,delivery_id,"
                    "candidate_output_sha256,output_sha256,canonical_position,"
                    "item_sha256,unread) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s)",
                    (
                        str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4()),
                        str(uuid4()), state, exclusion, revision_id, delivery_id,
                        "a" * 64, "a" * 64, "b" * 64, unread,
                    ),
                )
            except psycopg2.Error:
                db.rollback()
            else:  # pragma: no cover - a successful insert is the failure
                db.rollback()
                raise AssertionError(
                    f"projection item shape {state!r} unread={unread} was accepted"
                )


def test_projection_items_never_carry_foreign_attachment_currentness(db):
    """No projection item may carry coach currentness it did not resolve itself.

    This is the executable form of the attachment-scope reset: the invariant is
    checked over every frozen item of a real projection, so a regression that
    lets one attachment's unread / presentation / rendered-exposure identity
    survive into the next attachment fails here.
    """
    context, _feedback, _revision, _delivery, _presentation_id = (
        _render_projection_context(db)
    )
    projection = service_json_rpc(
        db, "project_confident_moment_bundles_v1",
        context["owner"], context["project"], context["take"],
    )
    frozen = rows(
        db,
        "SELECT resolution_state,revision_id,delivery_id,presentation_id,"
        "rendered_exposure_id,unread,candidate_output_sha256,output_sha256,"
        "canonical_position FROM confident_moment_bundle_projection_items "
        "WHERE projection_id=(SELECT id FROM confident_moment_bundle_projections "
        "WHERE response_sha256=%s) ORDER BY canonical_position",
        (projection["bundle_projection"]["response_sha256"],),
    )
    assert frozen
    positions = [row["canonical_position"] for row in frozen]
    assert positions == sorted(set(positions))
    for row in frozen:
        if row["resolution_state"] == "coach_revision":
            assert row["revision_id"] is not None
            assert row["delivery_id"] is not None
            assert row["unread"] == (row["rendered_exposure_id"] is None)
        else:
            # A non-coach item must be completely free of coach currentness.
            assert row["revision_id"] is None
            assert row["presentation_id"] is None
            assert row["rendered_exposure_id"] is None
            assert row["unread"] is False
            assert row["output_sha256"] == row["candidate_output_sha256"]


def test_projection_sql_resets_every_item_scoped_variable_inside_the_loop():
    """Static pin: the attachment-scoped reset must live in the inner loop.

    The regression this guards is a reset placed only before the inner loop,
    which lets a coach-updated attachment leak unread / presentation /
    rendered-exposure identity into the following machine-only attachment.
    """
    source = SQL.split(
        "CREATE OR REPLACE FUNCTION public.project_confident_moment_bundles_v1(", 1
    )[1].split("\n$$;", 1)[0]
    inner_loop = source.split("FOR attachment IN SELECT a.*,candidate.feedback_family", 1)
    assert len(inner_loop) == 2, "inner attachment loop not found"
    inner = inner_loop[1].split("END LOOP;", 1)[0]
    for variable in (
        "resolution:='machine_fallback'",
        "exclusion:=NULL",
        "delivery_id:=NULL",
        "coach_revision_id:=NULL",
        "unread:=false",
        "presentation_count:=NULL",
        "current_presentation_id:=NULL",
        "current_rendered_exposure_id:=NULL",
        "item_comment_payload:=NULL",
        "item_rephrase_payload:=NULL",
        "output_hash:=public.feedback_candidate_output_sha256_v1(",
    ):
        assert variable in inner, f"{variable} is not reset per attachment"
    # Each reset must be unconditional, not buried in a branch: every one of
    # them has to appear before the first IF of the attachment body.
    prologue = inner.split("\n   IF ", 1)[0]
    for variable in ("coach_revision_id:=NULL", "unread:=false",
                     "current_presentation_id:=NULL",
                     "current_rendered_exposure_id:=NULL"):
        assert variable in prologue, f"{variable} is reset conditionally"
    # The bundle-scoped accumulators must be distinct from the item-scoped ones.
    assert "bundle_coach_revision_id" in source
    assert "bundle_unread" in source
    # A coach revision must never clear a sibling attachment's payload slot,
    # and the machine fallback must never overwrite coach-authored text.
    assert "INTO item_comment_payload,item_rephrase_payload,output_hash" in source
    assert "ELSIF NOT rephrase_is_coach THEN rephrase_payload:=" in source
    assert "ELSIF NOT comment_is_coach THEN comment_payload:=" in source
    # has_unread_coach_update must fold existentially, not last-wins.
    assert "bundle_unread:=bundle_unread OR unread;" in source



def _function_body(name):
    """Exact source of one function in the migration, bounded by the next one."""
    tail = SQL.split(f"CREATE OR REPLACE FUNCTION public.{name}", 1)[1]
    return tail.split("\nCREATE OR REPLACE FUNCTION ", 1)[0].split("\nDO $", 1)[0]


def test_every_function_created_by_this_migration_is_execute_revoked(db):
    """D11 3 RPC-only closure, list-driven rather than a hardcoded subset.

    PostgreSQL grants EXECUTE to PUBLIC by default on CREATE FUNCTION, so any
    SECURITY DEFINER helper omitted from the revocation closure becomes a
    definer-rights probe callable by every runtime role. This enumerates the
    migration's own CREATE FUNCTION signatures instead of spot-checking.
    """
    _install_released_render_ack(db)
    with db.cursor() as cur:
        cur.execute(SQL)
    created = set(re.findall(
        r"CREATE OR REPLACE FUNCTION (public\.[a-z0-9_]+)\s*\(", SQL))
    assert created, "no functions extracted from the migration"
    granted = {"public.project_confident_moment_bundles_v1",
               "public.record_feedback_language_coach_revision_v2",
               "public.transition_feedback_language_delivery_v2",
               "public.ack_feedback_language_revision_render_v1"}
    for name in sorted(created):
        for signature in [
            row["sig"] for row in rows(
                db,
                "SELECT p.oid::regprocedure::text sig FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname||'.'||p.proname=%s",
                (name,),
            )
        ]:
            # A PUBLIC grant surfaces through every role, so checking the two
            # runtime roles also proves PUBLIC holds no EXECUTE.
            for role in ("anon", "authenticated"):
                assert one(
                    db,
                    "SELECT has_function_privilege(%s,%s,'EXECUTE') AS granted",
                    (role, signature),
                )["granted"] is False, f"{signature} is EXECUTE-able by {role}"
            expected = name in granted
            assert one(
                db,
                "SELECT has_function_privilege('service_role',%s,'EXECUTE') AS granted",
                (signature,),
            )["granted"] is expected, f"{signature} service_role grant mismatch"


def test_each_canonical_projection_table_is_defined_exactly_once(db):
    """A second, divergent CREATE TABLE for the same name can only mislead."""
    for table in ("confident_moment_bundle_projections",
                  "confident_moment_bundle_projection_items",
                  "confident_moment_bundle_attachments"):
        assert SQL.count(f"CREATE TABLE IF NOT EXISTS public.{table} (") == 1, table


def test_ack_acquires_the_audio_and_purge_serializers_it_depends_on(db):
    """D11 2 / A3 Stage 2: the acknowledgement reads deletion and purge state
    through its coach/source guard, so it must hold orders 60 and 70."""
    body = _function_body("ack_feedback_language_revision_render_v1")
    acquired = re.findall(r"pg_advisory_xact_lock\(hashtextextended\('([a-z0-9-]+)", body)
    for serializer in ("mlc3-rollout-policy-v2", "mlc3-service-principal",
                       "confident-moment-project-inventory",
                       "confident-moment-take-inventory",
                       "feedback-v3-membership-inventory",
                       "mlc3-speaker-attempt", "mlc3-processing-audio-object",
                       "feedback-language-candidate",
                       "feedback-language-delivery-subject",
                       "feedback-language-revision-head"):
        assert serializer in acquired, f"{serializer} not acquired by the ack"
    order = {"mlc3-rollout-policy-v2": 10, "mlc3-service-principal": 20,
             "confident-moment-project-inventory": 30,
             "confident-moment-take-inventory": 40,
             "feedback-v3-membership-inventory": 50,
             "mlc3-speaker-attempt": 60, "mlc3-processing-audio-object": 70,
             "feedback-language-candidate": 110,
             "feedback-language-delivery-subject": 120,
             "feedback-language-revision-head": 130}
    graded = [order[name] for name in acquired if name in order]
    assert graded == sorted(graded), f"lock order inverted: {graded}"


def test_ack_passes_a_live_candidate_output_recomputation_not_its_own_column(db):
    """The guard's candidate-output equality must not be self-satisfying."""
    body = _function_body("ack_feedback_language_revision_render_v1")
    assert body.count("require_feedback_language_coach_source_live_v1(") == 2
    assert "revision.candidate_output_sha256,'FEEDBACK_LANGUAGE" not in body
    assert body.count(
        "public.feedback_candidate_output_sha256_v1(revision.feedback_candidate_id)"
    ) == 2


def test_coach_update_is_present_and_null_without_a_valid_delivery_per_d11(db):
    """D11 4.4: the stable key is present, but no current coach delivery is
    represented honestly as JSON null rather than a synthetic empty update."""
    body = _function_body("project_confident_moment_bundles_v1")
    assert "'coach_update',CASE WHEN bundle_coach_revision_id IS NULL THEN NULL" in body
    assert (
        "'current_revision_id',bundle_coach_revision_id,'unread',bundle_unread"
        in body
    )
