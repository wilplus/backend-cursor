"""Executable checks run only against a disposable production-shaped clone."""
from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extras import Json

from tests import test_coach_guidance_delivery_d3_postgres as d3
from tests import test_mlc3_coach_inline_authoring_d5_postgres as d5
from tests import test_mlc3_first_client_service_postgres as d2
from tests.test_mlc3_dark_assignments_postgres import (
    assign,
    make_context,
)
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

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="disposable rehearsal only")
SQL = (Path(__file__).resolve().parents[1] / "migrations/add_confident_moment_coaching_bundle_v1.sql").read_text()
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


def _add_selected_feedback_item(
    db, feedback, family: str, position: int, generated_output=None,
):
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
            Json(generated_output or (
                {"proposed_text": "A clearer fixture sentence."}
                if family == "rewrite_clarity"
                else {"comment": f"{family} fixture output"}
            )),
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


def test_d13_bundle_item_render_binds_path_and_returns_closed_receipt(db):
    _install_released_render_ack(db)
    with db.cursor() as cur:
        cur.execute(SQL)
    context, feedback, _batch, _grant, _judgment, _item = (
        _feedback_language_context(db)
    )
    prepared = one(
        db,
        "SELECT prepare_confident_moment_bundle_v1(%s,%s,%s,%s,%s,%s) payload",
        (
            context["owner"],
            context["project"],
            context["take"],
            feedback["membership"]["id"],
            feedback["candidate_id"],
            f"d13-item-prepare-{uuid4()}",
        ),
    )["payload"]
    attachment = prepared["attachments"][0]
    render_instance_id = str(uuid4())
    idempotency_key = f"d13-item-render-{uuid4()}"
    args = (
        context["owner"],
        prepared["bundle_id"],
        attachment["id"],
        attachment["canonical_feedback_presentation_id"],
        render_instance_id,
        idempotency_key,
    )
    receipt = service_json_rpc(
        db, "ack_confident_moment_bundle_item_render_v3", *args
    )
    assert set(receipt) == {
        "render_contract_version",
        "bundle_id",
        "bundle_attachment_id",
        "feedback_exposure_id",
        "render_instance_id",
        "render_receipt_id",
        "dataset_eligible",
    }
    assert receipt["render_contract_version"] == (
        "confident-moment-bundle-item-render-v3"
    )
    assert receipt["bundle_id"] == prepared["bundle_id"]
    assert receipt["bundle_attachment_id"] == attachment["id"]
    assert receipt["feedback_exposure_id"] == attachment[
        "canonical_feedback_presentation_id"
    ]
    assert receipt["render_receipt_id"] != receipt["feedback_exposure_id"]
    assert receipt["render_instance_id"] == render_instance_id
    assert receipt["dataset_eligible"] is False
    assert service_json_rpc(
        db, "ack_confident_moment_bundle_item_render_v3", *args
    ) == receipt

    before = one(db, "SELECT count(*) n FROM feedback_v3_service_render_receipts")[
        "n"
    ]
    _assert_service_json_rejected(
        db,
        "ack_confident_moment_bundle_item_render_v3",
        (
            context["owner"],
            str(uuid4()),
            attachment["id"],
            attachment["canonical_feedback_presentation_id"],
            str(uuid4()),
            f"d13-cross-bundle-{uuid4()}",
        ),
        "no rows|CONFIDENT_MOMENT_ATTACHMENT_INVALID",
    )
    assert one(
        db, "SELECT count(*) n FROM feedback_v3_service_render_receipts"
    )["n"] == before


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
            cur.execute("SELECT has_function_privilege(%s,'public.ack_feedback_language_revision_render_v3(uuid,uuid,uuid,uuid,uuid,uuid,uuid,text)','EXECUTE')", (role,))
            assert cur.fetchone()[0] is (role == "service_role")
            cur.execute("SELECT has_function_privilege(%s,'public.ack_confident_moment_bundle_item_render_v3(uuid,uuid,uuid,uuid,uuid,text)','EXECUTE')", (role,))
            assert cur.fetchone()[0] is (role == "service_role")
            cur.execute("SELECT to_regprocedure('public.ack_feedback_language_revision_render_v1(uuid,uuid,uuid,uuid,text)') IS NULL")
            assert cur.fetchone()[0] is True
            cur.execute("SELECT to_regprocedure('public.ack_feedback_language_revision_render_v2(uuid,uuid,uuid,uuid,uuid,uuid,text)') IS NULL")
            assert cur.fetchone()[0] is True
            cur.execute("SELECT to_regprocedure('public.ack_confident_moment_bundle_item_render_v1(uuid,uuid,uuid,uuid,text)') IS NULL")
            assert cur.fetchone()[0] is True
            cur.execute("SELECT to_regprocedure('public.ack_confident_moment_bundle_item_render_v2(uuid,uuid,uuid,uuid,uuid,text)') IS NULL")
            assert cur.fetchone()[0] is True
            cur.execute(
                "SELECT has_function_privilege(%s,"
                "'public.validate_confident_moment_projection_item_v1()',"
                "'EXECUTE')",
                (role,),
            )
            assert cur.fetchone()[0] is False
        cur.execute("SELECT has_function_privilege('anon','public.lock_confident_moment_inventory_v1(uuid,uuid,uuid)','EXECUTE')")
        assert cur.fetchone()[0] is False
