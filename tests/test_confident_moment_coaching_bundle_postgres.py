"""Executable checks run only against a disposable production-shaped clone."""
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
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
    wait_for_lock,
)
from tests.test_mlc3_general_user_service_d4_postgres import (
    CAPACITY,
    _activate_contract,
    _enable_coach_review_for_fixture,
    _general_offer_context,
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


def _coach_projection_item(projection, revision_id):
    return next(
        item
        for bundle in projection["bundle_projection"]["bundles"]
        for item in bundle["feedback_language_items"]
        if item["coach_update"]
        and item["coach_update"]["current_revision_id"] == revision_id
    )


def _render_v3_args(db, owner, revision, delivery, presentation_id):
    attachment = one(
        db,
        "SELECT id,bundle_subject_candidate_id FROM confident_moment_bundle_attachments "
        "WHERE feedback_membership_id=%s AND attached_candidate_id=%s",
        (revision["feedback_membership_id"], revision["feedback_candidate_id"]),
    )
    return (
        owner,
        attachment["bundle_subject_candidate_id"],
        attachment["id"],
        revision["id"],
        delivery["id"],
        presentation_id,
        str(uuid4()),
        f"render-v2-{uuid4()}",
    )


def test_apply_reapply_forced_rls_and_exact_signatures(db):
    with db.cursor() as cur:
        cur.execute(SQL)
        cur.execute(SQL)
        cur.execute("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname=ANY(%s) ORDER BY relname", (["confident_moment_bundle_attachments","root_phrase_coverage_frames","root_phrase_coverage_items","feedback_language_revision_deliveries","confident_moment_bundle_projections","confident_moment_bundle_projection_items"],))
        rows = cur.fetchall()
        assert len(rows) == 6 and all(row[1:] == (True, True) for row in rows)
        cur.execute("SELECT to_regprocedure(%s) IS NOT NULL", ("public.record_root_phrase_product_action_v2(uuid,uuid,uuid,uuid,integer,text,uuid,uuid,uuid,uuid,uuid,uuid,bigint,uuid,uuid,uuid,uuid,text,text)",))
        assert cur.fetchone()[0]
        cur.execute("SELECT to_regprocedure(%s) IS NOT NULL", ("public.require_root_phrase_practice_source_live_v1(uuid,uuid,uuid,uuid,uuid)",))
        assert cur.fetchone()[0]
        cur.execute(
            "SELECT pg_get_function_identity_arguments(%s::regprocedure::oid)",
            ("public.prepare_confident_moment_bundle_v1(uuid,uuid,uuid,uuid,uuid,text)",),
        )
        assert "p_bundle_subject_candidate_id uuid" in cur.fetchone()[0]


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


def test_d15_bundle_item_render_obeys_natural_before_idempotency_lock_order(db):
    """The D11 shared graph must precede the operation-local replay lock."""
    _install_released_render_ack(db)
    with db.cursor() as cur:
        cur.execute(SQL)
        cur.execute(
            "SELECT pg_get_functiondef("
            "'public.ack_confident_moment_bundle_item_render_v3"
            "(uuid,uuid,uuid,uuid,uuid,text)'::regprocedure)"
        )
        body = cur.fetchone()[0]
    positions = [
        body.index("lock_confident_moment_inventory_v1"),
        body.index("feedback-v3-membership-current:"),
        body.index("confident-moment-bundle-subject:"),
        body.index("confident-moment-render:"),
    ]
    assert positions == sorted(positions)


def test_d15_concurrent_exact_item_render_replay_is_deadlock_free(db):
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
            context["owner"], context["project"], context["take"],
            feedback["membership"]["id"], feedback["candidate_id"],
            f"d15-concurrent-prepare-{uuid4()}",
        ),
    )["payload"]
    attachment = prepared["attachments"][0]
    # D15/application allow natural input identities to alias.  Only the
    # generated receipt is forbidden from aliasing the feedback exposure.
    args = (
        context["owner"], prepared["bundle_id"], attachment["id"],
        attachment["canonical_feedback_presentation_id"],
        prepared["bundle_id"], f"d15-concurrent-render-{uuid4()}",
    )
    db.commit()

    def render_once():
        connection = psycopg2.connect(db.dsn)
        connection.autocommit = False
        try:
            result = service_json_rpc(
                connection, "ack_confident_moment_bundle_item_render_v3", *args
            )
            connection.commit()
            return result
        finally:
            connection.rollback()
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(render_once)
        second = pool.submit(render_once)
        receipts = [first.result(timeout=10), second.result(timeout=10)]
    assert receipts[0] == receipts[1]
    assert receipts[0]["render_instance_id"] == prepared["bundle_id"]
    assert receipts[0]["render_receipt_id"] != receipts[0]["feedback_exposure_id"]
    assert one(
        db,
        "SELECT count(*) n FROM feedback_v3_service_render_receipts "
        "WHERE idempotency_key=%s",
        (args[-1],),
    )["n"] == 1


@pytest.mark.parametrize("invalidation", ["document_head", "source_deletion"])
def test_d13_bundle_item_exact_replay_revalidates_live_source(db, invalidation):
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
            context["owner"], context["project"], context["take"],
            feedback["membership"]["id"], feedback["candidate_id"],
            f"d13-live-prepare-{uuid4()}",
        ),
    )["payload"]
    attachment = prepared["attachments"][0]
    args = (
        context["owner"], prepared["bundle_id"], attachment["id"],
        attachment["canonical_feedback_presentation_id"], str(uuid4()),
        f"d13-live-render-{uuid4()}",
    )
    receipt = service_json_rpc(
        db, "ack_confident_moment_bundle_item_render_v3", *args
    )
    db.commit()
    if invalidation == "source_deletion":
        _delete_source_audio(db, context["owner"])
    else:
        old_snapshot = one(
            db,
            "SELECT snapshot.* FROM ideal_text_document_snapshots snapshot "
            "JOIN ideal_text_document_heads head ON head.snapshot_id=snapshot.id "
            "WHERE snapshot.id=%s",
            (feedback["membership"]["document_snapshot_id"],),
        )
        successor_id = str(uuid4())
        rows(
            db,
            "INSERT INTO ideal_text_document_snapshots("
            "id,arc_id,actor_id,acquisition_principal_id,project_id,"
            "source_take_session_id,version,source_generation,"
            "source_fingerprint_sha256,payload_sha256,payload,enrichment_seed) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)",
            (
                successor_id, old_snapshot["arc_id"], old_snapshot["actor_id"],
                old_snapshot["acquisition_principal_id"],
                old_snapshot["project_id"], old_snapshot["source_take_session_id"],
                old_snapshot["version"] + 1, old_snapshot["source_generation"],
                uuid4().hex * 2, old_snapshot["payload_sha256"],
                Json(old_snapshot["payload"]), Json(old_snapshot["enrichment_seed"]),
            ),
        )
        rows(
            db,
            "UPDATE ideal_text_document_heads SET snapshot_id=%s,"
            "updated_at=clock_timestamp() WHERE snapshot_id=%s",
            (successor_id, old_snapshot["id"]),
        )
    db.commit()
    before = one(db, "SELECT count(*) n FROM feedback_v3_service_render_receipts")[
        "n"
    ]
    _assert_service_json_rejected(
        db,
        "ack_confident_moment_bundle_item_render_v3",
        args,
        "FEEDBACK_V3_SERVICE_SOURCE_STALE|MLC3_DUAL_PURPOSE_AUTHORITY_REQUIRED|CONFIDENT_MOMENT_ATTACHMENT_INVALID",
    )
    assert one(
        db, "SELECT count(*) n FROM feedback_v3_service_render_receipts"
    )["n"] == before
    assert one(
        db,
        "SELECT id,feedback_exposure_id FROM feedback_v3_service_render_receipts "
        "WHERE id=%s",
        (receipt["render_receipt_id"],),
    )["feedback_exposure_id"] == receipt["feedback_exposure_id"]


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
        with pytest.raises(
            psycopg2.Error,
            match='null value in column "acquisition_principal_id"',
        ):
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
                "NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,"
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
                "NULL,NULL,NULL,NULL,NULL,NULL,NULL,"
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
    assert first["bundle_projection"]["contract_version"] == (
        "confident-moment-coaching-bundle-v2"
    )
    assert first["bundle_projection"]["feedback_language_shape_version"] == (
            "feedback-language-items-v2"
    )
    for bundle in first["bundle_projection"]["bundles"]:
        assert {"comment", "rephrase", "coach_update"}.isdisjoint(bundle)
        assert all(
            item["coach_update"] is None
            for item in bundle["feedback_language_items"]
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
                cur.execute("SET application_name='d11-projection-revocation'")
                cur.execute(
                    "SELECT project_confident_moment_bundles_v1(%s,%s,%s)",
                    (context["owner"], context["project"], context["take"]),
                )

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(read_projection)
            wait_for_lock(db, "d11-projection-revocation", "advisory")
            assert not future.done()
            writer.commit()
            with pytest.raises(psycopg2.Error, match="MLC3_ROLLOUT_NOT_ACTIVE"):
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


def test_d12_rewrite_observation_without_replacement_is_actionable_comment(db):
    with db.cursor() as cur:
        cur.execute(SQL)
    context, feedback = _positive_projection_context(db)
    candidate_id = _add_selected_feedback_item(
        db,
        feedback,
        "rewrite_clarity",
        2,
        {"observation": "The solution arrives after a long problem setup."},
    )
    one(
        db,
        "SELECT prepare_confident_moment_bundle_v1(%s,%s,%s,%s,%s,%s) payload",
        (
            context["owner"], context["project"], context["take"],
            feedback["membership"]["id"], feedback["candidate_id"],
            f"d12-observation-{uuid4()}",
        ),
    )
    projection = service_json_rpc(
        db, "project_confident_moment_bundles_v1",
        context["owner"], context["project"], context["take"],
    )
    item = next(
        item
        for item in projection["bundle_projection"]["bundles"][0][
            "feedback_language_items"
        ]
        if item["attached_candidate_id"] == candidate_id
    )
    assert item["resolution_state"] == "machine_fallback"
    assert item["exclusion_reason"] is None
    assert item["output"] == {
        "output_kind": "comment",
        "comment_purpose": "actionable_observation",
        "text": "The solution arrives after a long problem setup.",
        "origin": "machine",
    }
    assert item["coach_update"] is None


def test_d12_no_anchor_schedule_project_and_render_uses_exact_bundle_subject(db):
    _install_released_render_ack(db)
    with db.cursor() as cur:
        cur.execute(SQL)
    context, feedback, batch, grant, judgment, reveal_item = (
        _feedback_language_context(db, ("rewrite_clarity",))
    )
    rewrite_id = feedback["mixed_candidate_ids"]["rewrite_clarity"]
    rows(
        db,
        "ALTER TABLE feedback_v3_membership_items DISABLE TRIGGER "
        "feedback_v3_membership_items_append_only",
    )
    try:
        rows(
            db,
            "UPDATE feedback_v3_membership_items SET slide_index=slide_index+1 "
            "WHERE membership_id=%s AND candidate_id=%s",
            (feedback["membership"]["id"], rewrite_id),
        )
    finally:
        rows(
            db,
            "ALTER TABLE feedback_v3_membership_items ENABLE TRIGGER "
            "feedback_v3_membership_items_append_only",
        )
    prepared = one(
        db,
        "SELECT prepare_confident_moment_bundle_v1(%s,%s,%s,%s,%s,%s) payload",
        (
            context["owner"], context["project"], context["take"],
            feedback["membership"]["id"], rewrite_id,
            f"d12-no-anchor-prepare-{uuid4()}",
        ),
    )["payload"]
    assert prepared["bundle_subject_kind"] == "no_anchor_paragraph_trigger"
    attachment_id = prepared["attachments"][0]["id"]
    output_hash = one(
        db, "SELECT feedback_candidate_output_sha256_v1(%s) value", (rewrite_id,),
    )["value"]
    revision = service_json_rpc(
        db, "record_feedback_language_coach_revision_v2",
        context["reviewer"], batch["id"], grant["id"],
        reveal_item["reveal_access_id"], reveal_item["review_assignment_id"],
        judgment["judgment_id"], feedback["membership"]["id"], rewrite_id,
        output_hash, "comment", "actionable_observation",
        "State the solution before expanding the detail.", None,
        f"d12-no-anchor-revision-{uuid4()}",
    )
    before_delivery = one(
        db, "SELECT count(*) n FROM feedback_language_revision_deliveries"
    )["n"]
    _assert_service_json_rejected(
        db, "transition_feedback_language_delivery_v2",
        (
            revision["id"], context["owner"], context["take"],
            feedback["candidate_id"], None, "schedule",
            f"d12-no-anchor-foreign-{uuid4()}",
        ),
        "CONFIDENT_MOMENT_ANCHOR_INVALID",
    )
    assert one(
        db, "SELECT count(*) n FROM feedback_language_revision_deliveries"
    )["n"] == before_delivery
    delivery = service_json_rpc(
        db, "transition_feedback_language_delivery_v2",
        revision["id"], context["owner"], context["take"], rewrite_id, None,
        "schedule", f"d12-no-anchor-delivery-{uuid4()}",
    )
    assert delivery["anchor_candidate_id"] == rewrite_id
    event_id, presentation_id = str(uuid4()), str(uuid4())
    visible_hash = uuid4().hex * 2
    rows(
        db,
        "INSERT INTO ml_canonical_events(id,learning_surface_id,feedback_family_id,"
        "payload_type) VALUES(%s,'coach_comment_generation',NULL,'coach_comment_event')",
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
            Json({"text": "State the solution before expanding the detail."}),
            revision["revision_sha256"],
        ),
    )
    rows(
        db,
        "INSERT INTO ml_presentations(id,canonical_event_id,learning_surface_id,"
        "artifact_id,actor_principal_id,actor_role,delivery_mode,evaluation_only,"
        "visible_payload_sha256,acknowledgement_token,idempotency_key) VALUES"
        "(%s,%s,'coach_comment_generation',%s,%s,'owner','canary',false,%s,%s,%s)",
        (
            presentation_id, event_id, revision["id"], context["owner"],
            visible_hash, str(uuid4()), f"d12-no-anchor-presentation-{uuid4()}",
        ),
    )
    unread_projection = service_json_rpc(
        db, "project_confident_moment_bundles_v1",
        context["owner"], context["project"], context["take"],
    )
    coach_item = _coach_projection_item(unread_projection, revision["id"])
    assert coach_item["bundle_attachment_id"] == attachment_id
    assert coach_item["coach_update"]["unread"] is True
    service_json_rpc(
        db, "ack_feedback_language_revision_render_v3",
        context["owner"], prepared["bundle_id"], attachment_id,
        revision["id"], delivery["id"],
        presentation_id, str(uuid4()), f"d12-no-anchor-render-{uuid4()}",
    )
    rendered_projection = service_json_rpc(
        db, "project_confident_moment_bundles_v1",
        context["owner"], context["project"], context["take"],
    )
    assert _coach_projection_item(rendered_projection, revision["id"])[
        "coach_update"
    ]["unread"] is False


def test_d11_revision_and_delivery_exact_replay_successor_and_stale_rejection(db):
    with db.cursor() as cur:
        cur.execute(SQL)
    context, feedback, batch, grant, judgment, item = _feedback_language_context(db)
    one(
        db,
        "SELECT prepare_confident_moment_bundle_v1(%s,%s,%s,%s,%s,%s) payload",
        (
            context["owner"], context["project"], context["take"],
            feedback["membership"]["id"], feedback["candidate_id"],
            f"d11-replay-prepare-{uuid4()}",
        ),
    )
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


def _second_coach_comment_chain(db, context, feedback, candidate_id):
    reviewer_id, reviewer_user_id = str(uuid4()), str(uuid4())
    rows(
        db, "INSERT INTO owner_principals(id,user_id) VALUES(%s,%s)",
        (reviewer_id, reviewer_user_id),
    )
    second = {**context, "reviewer": reviewer_id}
    d3._authorize_coach(db, second)
    packet = d3._make_packet(db, second)
    owner_user_id = one(
        db, "SELECT user_id FROM owner_principals WHERE id=%s", (context["owner"],),
    )["user_id"]
    service_rpc(
        db, "ensure_mlc3_service_enrollment_v2",
        context["owner"], owner_user_id, f"d12-second-coach-enrollment-{uuid4()}",
    )
    d5._batch(db, second)
    judgment_id = d3._judge(db, second, packet, decision="rating_yes")
    inline = one(
        db,
        "SELECT prepare_coach_inline_guidance_context_v1(%s,%s,%s,%s) payload",
        (second["project"], second["owner"], reviewer_id, str(uuid4())),
    )["payload"]
    item = next(
        value for value in inline["items"]
        if value["review_assignment_id"] == packet["review_assignment_id"]
    )
    output_hash = one(
        db, "SELECT feedback_candidate_output_sha256_v1(%s) value", (candidate_id,),
    )["value"]
    revision = service_json_rpc(
        db, "record_feedback_language_coach_revision_v2",
        reviewer_id, inline["review_batch_id"], inline["reveal_grant_id"],
        item["reveal_access_id"], item["review_assignment_id"], judgment_id,
        feedback["membership"]["id"], candidate_id, output_hash, "comment",
        "positive_praise", "This is a strong, memorable formulation.", None,
        f"d12-second-coach-revision-{uuid4()}",
    )
    delivery = service_json_rpc(
        db, "transition_feedback_language_delivery_v2",
        revision["id"], context["owner"], context["take"],
        feedback["candidate_id"], None,
        "schedule", f"d12-second-coach-delivery-{uuid4()}",
    )
    event_id, presentation_id = str(uuid4()), str(uuid4())
    visible_hash = uuid4().hex * 2
    rows(
        db,
        "INSERT INTO ml_canonical_events(id,learning_surface_id,feedback_family_id,"
        "payload_type) VALUES(%s,'praise_generation','great_formulation',"
        "'praise_generation_event')",
        (event_id,),
    )
    rows(
        db,
        "INSERT INTO ml_semantic_artifacts(id,canonical_event_id,learning_surface_id,"
        "pipeline_stage_id,feedback_family_id,evidence_span_id,artifact_type,"
        "semantic_version,content,content_sha256) VALUES(%s,%s,'praise_generation',"
        "'generate','great_formulation',NULL,'generated_praise',"
        "'feedback-language-coach-revision-v1',"
        "%s::jsonb,%s)",
        (
            revision["id"], event_id,
            Json({"text": "This is a strong, memorable formulation."}),
            revision["revision_sha256"],
        ),
    )
    rows(
        db,
        "INSERT INTO ml_presentations(id,canonical_event_id,learning_surface_id,"
        "artifact_id,actor_principal_id,actor_role,delivery_mode,evaluation_only,"
        "visible_payload_sha256,acknowledgement_token,idempotency_key) VALUES"
        "(%s,%s,'praise_generation',%s,%s,'owner','canary',false,%s,%s,%s)",
        (
            presentation_id, event_id, revision["id"], context["owner"],
            visible_hash, str(uuid4()), f"d12-second-coach-presentation-{uuid4()}",
        ),
    )
    db.commit()
    return reviewer_id, revision, delivery, presentation_id


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
    attachment = one(
        db,
        "SELECT id,bundle_subject_candidate_id FROM confident_moment_bundle_attachments "
        "WHERE feedback_membership_id=%s AND attached_candidate_id=%s",
        (revision["feedback_membership_id"], revision["feedback_candidate_id"]),
    )
    attachment_id = attachment["id"]
    if rendered:
        service_json_rpc(
            db,
            "ack_feedback_language_revision_render_v3",
            context["owner"], attachment["bundle_subject_candidate_id"],
            attachment_id, revision["id"], delivery["id"],
            presentation_id, str(uuid4()),
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
    assert {"comment", "rephrase", "coach_update"}.isdisjoint(bundle)
    items = bundle["feedback_language_items"]
    assert len({item["canonical_feedback_exposure_id"] for item in items}) == len(items)
    for projected_item in items:
        exact = one(
            db,
            "SELECT exposure.feedback_family,exposure.id "
            "FROM confident_moment_bundle_attachments attachment "
            "JOIN feedback_exposures exposure "
            "ON exposure.id=attachment.canonical_feedback_presentation_id "
            "AND exposure.candidate_id=attachment.attached_candidate_id "
            "WHERE attachment.id=%s",
            (projected_item["bundle_attachment_id"],),
        )
        assert projected_item["feedback_family"] == exact["feedback_family"]
        assert projected_item["canonical_feedback_exposure_id"] == exact["id"]
    assert [item["canonical_position"] for item in items] == sorted(
        item["canonical_position"] for item in items
    )
    coach_output = next(
        item for item in items
        if item["output"] and item["output"]["origin"] == "coach"
    )
    assert coach_output["output"] == {
        "output_kind": "comment",
        "comment_purpose": "confidence_explanation",
        "text": "Keep this delivery clear.",
        "origin": "coach",
    }
    assert coach_output["bundle_attachment_id"] == attachment_id
    assert coach_output["coach_update"] == {
        "current_revision_id": revision["id"],
        "revision_sha256": revision["revision_sha256"],
        "revision_delivery_id": delivery["id"],
        "delivery_subject_sha256": delivery["delivery_subject_sha256"],
        "presentation_id": presentation_id,
        "rendered_exposure_id": coach_output["coach_update"]["rendered_exposure_id"],
        "unread": not rendered,
    }
    machine_rephrase = next(
        item for item in items
        if item["output"] and item["output"]["output_kind"] == "rephrase"
    )
    assert machine_rephrase["output"] == {
        "output_kind": "rephrase",
        "comment_purpose": None,
        "text": "A clearer fixture sentence.",
        "origin": "machine",
    }
    praise = next(
        item for item in items
        if item["output"] and item["output"].get("comment_purpose") == "positive_praise"
    )
    assert praise["output"]["origin"] == "machine"
    assert machine_rephrase["coach_update"] is None
    assert praise["coach_update"] is None
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


@pytest.mark.parametrize("reverse_render_order", [False, True])
def test_d12_two_coaches_two_comments_are_independent_per_attachment(
    db, reverse_render_order,
):
    context, feedback, first_revision, first_delivery, first_presentation = (
        _render_projection_context(db, mixed_first=False)
    )
    praise_candidate_id = feedback["mixed_candidate_ids"]["great_formulation"]
    second_reviewer, second_revision, second_delivery, second_presentation = (
        _second_coach_comment_chain(db, context, feedback, praise_candidate_id)
    )
    assert second_reviewer != context["reviewer"]
    initial = service_json_rpc(
        db, "project_confident_moment_bundles_v1",
        context["owner"], context["project"], context["take"],
    )
    bundle = initial["bundle_projection"]["bundles"][0]
    coach_items = [
        item for item in bundle["feedback_language_items"]
        if item["resolution_state"] == "coach_revision"
    ]
    assert len(coach_items) == 2
    assert {item["output"]["comment_purpose"] for item in coach_items} == {
        "confidence_explanation", "positive_praise",
    }
    assert {item["coach_update"]["current_revision_id"] for item in coach_items} == {
        first_revision["id"], second_revision["id"],
    }
    assert all(item["coach_update"]["unread"] for item in coach_items)
    assert initial["confident_moment_summary"]["items"][0][
        "has_unread_coach_update"
    ] is True

    chains = [
        (first_revision, first_delivery, first_presentation),
        (second_revision, second_delivery, second_presentation),
    ]
    if reverse_render_order:
        chains.reverse()
    first_chain, second_chain = chains
    service_json_rpc(
        db, "ack_feedback_language_revision_render_v3",
        *_render_v3_args(db, context["owner"], *first_chain),
    )
    midway = service_json_rpc(
        db, "project_confident_moment_bundles_v1",
        context["owner"], context["project"], context["take"],
    )
    first_item = _coach_projection_item(midway, first_chain[0]["id"])
    second_item = _coach_projection_item(midway, second_chain[0]["id"])
    assert first_item["coach_update"]["unread"] is False
    assert second_item["coach_update"]["unread"] is True
    assert midway["confident_moment_summary"]["items"][0][
        "has_unread_coach_update"
    ] is True

    service_json_rpc(
        db, "ack_feedback_language_revision_render_v3",
        *_render_v3_args(db, context["owner"], *second_chain),
    )
    final = service_json_rpc(
        db, "project_confident_moment_bundles_v1",
        context["owner"], context["project"], context["take"],
    )
    assert all(
        not item["coach_update"]["unread"]
        for item in final["bundle_projection"]["bundles"][0][
            "feedback_language_items"
        ]
        if item["coach_update"]
    )
    assert final["confident_moment_summary"]["items"][0][
        "has_unread_coach_update"
    ] is False


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
            "attached_candidate_id,feedback_family,canonical_feedback_exposure_id,"
            "anchor_candidate_id,resolution_state,exclusion_reason,"
            "revision_id,delivery_id,presentation_id,rendered_exposure_id,unread,"
            "candidate_output_sha256,output_sha256,canonical_position,exercise_present,"
            "item_sha256) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
            "%s,%s,%s,%s,%s)",
            (
                clone_id, source["acquisition_principal_id"],
                source["other_attachment_id"], source["bundle_subject_candidate_id"],
                source["attached_candidate_id"], source["feedback_family"],
                source["canonical_feedback_exposure_id"],
                source["anchor_candidate_id"],
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
        db, "ack_feedback_language_revision_render_v3",
        _render_v3_args(db, context["owner"], revision, delivery_a, presentation_id),
        "no rows|FEEDBACK_LANGUAGE",
    )
    assert one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"] == before_count

    unread_projection = service_json_rpc(
        db, "project_confident_moment_bundles_v1",
        context["owner"], context["project"], context["take"],
    )
    assert _coach_projection_item(unread_projection, revision["id"])[
        "coach_update"
    ]["unread"] is True
    render_args = _render_v3_args(
        db, context["owner"], revision, delivery_b, presentation_id
    )
    cross_bundle_args = list(render_args)
    cross_bundle_args[1] = str(uuid4())
    _assert_service_json_rejected(
        db,
        "ack_feedback_language_revision_render_v3",
        tuple(cross_bundle_args),
        "no rows|CONFIDENT_MOMENT_ATTACHMENT_INVALID",
    )
    assert one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"] == (
        before_count
    )
    wording_before = one(
        db,
        "SELECT count(*) n,min(revision_sha256) revision_hash FROM feedback_revisions "
        "WHERE id=%s",
        (revision["id"],),
    )
    rendered = service_json_rpc(
        db, "ack_feedback_language_revision_render_v3", *render_args
    )
    assert set(rendered) == {
        "render_contract_version",
        "bundle_id",
        "bundle_attachment_id",
        "current_revision_id",
        "revision_delivery_id",
        "presentation_id",
        "render_instance_id",
        "rendered_exposure_id",
        "dataset_eligible",
    }
    assert rendered["render_contract_version"] == (
        "feedback-language-revision-render-v3"
    )
    assert rendered["bundle_id"] == render_args[1]
    assert rendered["bundle_attachment_id"] == render_args[2]
    assert rendered["current_revision_id"] == revision["id"]
    assert rendered["revision_delivery_id"] == delivery_b["id"]
    assert rendered["presentation_id"] == presentation_id
    assert rendered["render_instance_id"] == render_args[6]
    assert rendered["dataset_eligible"] is False
    assert service_json_rpc(
        db, "ack_feedback_language_revision_render_v3", *render_args
    ) == rendered
    changed_key_args = list(render_args)
    changed_key_args[-1] = f"d13-changed-replay-key-{uuid4()}"
    _assert_service_json_rejected(
        db,
        "ack_feedback_language_revision_render_v3",
        tuple(changed_key_args),
        "FEEDBACK_LANGUAGE_REPLAY_CONFLICT",
    )
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
    assert _coach_projection_item(read_projection, revision["id"])[
        "coach_update"
    ]["unread"] is False
    assert read_projection["bundle_projection"]["response_sha256"] != unread_projection["bundle_projection"]["response_sha256"]
    assert one(
        db,
        "SELECT rendered_exposure_id=%s AND unread=false ok "
        "FROM confident_moment_bundle_projection_items WHERE projection_id=("
        "SELECT id FROM confident_moment_bundle_projections WHERE response_sha256=%s)",
        (
            rendered["rendered_exposure_id"],
            read_projection["bundle_projection"]["response_sha256"],
        ),
    )["ok"] is True

    invalidated = service_json_rpc(
        db, "transition_feedback_language_delivery_v2",
        revision["id"], context["owner"], context["take"],
        feedback["candidate_id"], delivery_b["id"], "invalidate",
        f"render-delivery-{uuid4()}",
    )
    assert invalidated["delivery_state"] == "invalidated"
    _assert_service_json_rejected(
        db, "ack_feedback_language_revision_render_v3",
        _render_v3_args(db, context["owner"], revision, delivery_b, presentation_id),
        "no rows|FEEDBACK_LANGUAGE",
    )
    assert one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"] == before_count + 1


def test_d12_ack_rejects_cross_attachment_binding_without_exposure(db):
    context, feedback, revision, delivery, presentation_id = (
        _render_projection_context(db, mixed_first=False)
    )
    foreign_attachment = one(
        db,
        "SELECT id FROM confident_moment_bundle_attachments "
        "WHERE feedback_membership_id=%s AND attached_candidate_id<>%s "
        "ORDER BY canonical_position LIMIT 1",
        (feedback["membership"]["id"], feedback["candidate_id"]),
    )["id"]
    before = one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"]
    cross_bound_args = list(
        _render_v3_args(
            db, context["owner"], revision, delivery, presentation_id
        )
    )
    cross_bound_args[2] = foreign_attachment
    _assert_service_json_rejected(
        db,
        "ack_feedback_language_revision_render_v3",
        tuple(cross_bound_args),
        "no rows|FEEDBACK_LANGUAGE",
    )
    assert one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"] == before


def test_d12_ack_rejects_duplicate_canonical_presentations_before_exposure(db):
    context, _feedback, revision, delivery, presentation_id = (
        _render_projection_context(db)
    )
    rows(
        db,
        "INSERT INTO ml_presentations(id,canonical_event_id,learning_surface_id,"
        "artifact_id,actor_principal_id,actor_role,delivery_mode,evaluation_only,"
        "visible_payload_sha256,acknowledgement_token,idempotency_key) "
        "SELECT %s,canonical_event_id,learning_surface_id,artifact_id,"
        "actor_principal_id,actor_role,delivery_mode,evaluation_only,"
        "visible_payload_sha256,%s,%s FROM ml_presentations WHERE id=%s",
        (
            str(uuid4()), str(uuid4()), f"d12-duplicate-presentation-{uuid4()}",
            presentation_id,
        ),
    )
    before = one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"]
    _assert_service_json_rejected(
        db, "ack_feedback_language_revision_render_v3",
        _render_v3_args(db, context["owner"], revision, delivery, presentation_id),
        "FEEDBACK_LANGUAGE_RENDER_PRESENTATION_CARDINALITY_INVALID",
    )
    assert one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"] == before


def _adversarially_rebind_delivery_anchor(db, delivery_id, membership_id, candidate_id):
    foreign_anchor = one(
        db,
        "SELECT id AS attached_candidate_id FROM feedback_candidates "
        "WHERE id<>%s ORDER BY id LIMIT 1",
        (candidate_id,),
    )["attached_candidate_id"]
    rows(db, "ALTER TABLE feedback_language_revision_deliveries DISABLE TRIGGER "
             "feedback_language_revision_deliveries_append_only")
    try:
        rows(
            db,
            "UPDATE feedback_language_revision_deliveries SET anchor_candidate_id=%s "
            "WHERE id=%s",
            (foreign_anchor, delivery_id),
        )
    finally:
        rows(db, "ALTER TABLE feedback_language_revision_deliveries ENABLE TRIGGER "
                 "feedback_language_revision_deliveries_append_only")


def test_d12_projection_rejects_foreign_delivery_anchor_without_partial_state(db):
    context, feedback, revision, delivery, _presentation_id = (
        _render_projection_context(db)
    )
    _adversarially_rebind_delivery_anchor(
        db, delivery["id"], feedback["membership"]["id"], revision["feedback_candidate_id"],
    )
    before = one(db, "SELECT count(*) n FROM confident_moment_bundle_projections")["n"]
    _assert_service_json_rejected(
        db, "project_confident_moment_bundles_v1",
        (context["owner"], context["project"], context["take"]),
        "CONFIDENT_MOMENT_PROJECTION_INVALID",
    )
    assert one(db, "SELECT count(*) n FROM confident_moment_bundle_projections")["n"] == before


def test_d12_ack_rejects_foreign_delivery_anchor_without_exposure(db):
    context, feedback, revision, delivery, presentation_id = (
        _render_projection_context(db)
    )
    _adversarially_rebind_delivery_anchor(
        db, delivery["id"], feedback["membership"]["id"], revision["feedback_candidate_id"],
    )
    before = one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"]
    _assert_service_json_rejected(
        db, "ack_feedback_language_revision_render_v3",
        _render_v3_args(db, context["owner"], revision, delivery, presentation_id),
        "FEEDBACK_LANGUAGE_DELIVERY_LINEAGE_INVALID",
    )
    assert one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"] == before


def test_d12_projection_item_trigger_rejects_foreign_delivery_anchor(db):
    context, feedback, revision, delivery, _presentation_id = (
        _render_projection_context(db)
    )
    projected = service_json_rpc(
        db, "project_confident_moment_bundles_v1",
        context["owner"], context["project"], context["take"],
    )
    source_projection_id = one(
        db,
        "SELECT id FROM confident_moment_bundle_projections WHERE response_sha256=%s",
        (projected["bundle_projection"]["response_sha256"],),
    )["id"]
    rows(db, "SET CONSTRAINTS ALL IMMEDIATE")
    rows(db, "SET CONSTRAINTS ALL DEFERRED")
    _adversarially_rebind_delivery_anchor(
        db, delivery["id"], feedback["membership"]["id"], revision["feedback_candidate_id"],
    )
    replacement_projection_id = str(uuid4())
    rows(
        db,
        "INSERT INTO confident_moment_bundle_projections("
        "id,acquisition_principal_id,project_id,take_id,feedback_membership_id,"
        "document_snapshot_id,document_snapshot_sha256,projection_policy_version,"
        "projection_code_version,stabilized_inventory_sha256,response_sha256,"
        "idempotency_key) SELECT %s,acquisition_principal_id,project_id,take_id,"
        "feedback_membership_id,document_snapshot_id,document_snapshot_sha256,"
        "projection_policy_version,projection_code_version,%s,%s,%s FROM "
        "confident_moment_bundle_projections WHERE id=%s",
        (
            replacement_projection_id, uuid4().hex * 2, uuid4().hex * 2,
            f"d12-cross-anchor-projection-{uuid4()}", source_projection_id,
        ),
    )
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO confident_moment_bundle_projection_items("
            "projection_id,acquisition_principal_id,bundle_attachment_id,"
            "bundle_subject_candidate_id,attached_candidate_id,feedback_family,"
            "canonical_feedback_exposure_id,anchor_candidate_id,"
            "resolution_state,exclusion_reason,revision_id,delivery_id,presentation_id,"
            "rendered_exposure_id,unread,candidate_output_sha256,output_sha256,"
            "canonical_position,exercise_present,item_sha256) SELECT %s,"
            "acquisition_principal_id,bundle_attachment_id,bundle_subject_candidate_id,"
            "attached_candidate_id,feedback_family,canonical_feedback_exposure_id,"
            "anchor_candidate_id,resolution_state,exclusion_reason,"
            "revision_id,delivery_id,presentation_id,rendered_exposure_id,unread,"
            "candidate_output_sha256,output_sha256,canonical_position,exercise_present,"
            "item_sha256 FROM confident_moment_bundle_projection_items "
            "WHERE projection_id=%s AND revision_id=%s",
            (replacement_projection_id, source_projection_id, revision["id"]),
        )
        with pytest.raises(
            psycopg2.Error, match="CONFIDENT_MOMENT_PROJECTION_ITEM_LINEAGE_INVALID"
        ):
            cur.execute("SET CONSTRAINTS confident_moment_projection_item_lineage_v1 IMMEDIATE")
    db.rollback()


def test_d12_projection_rejects_multiple_rendered_exposure_heads(db):
    context, _feedback, revision, delivery, presentation_id = (
        _render_projection_context(db)
    )
    service_json_rpc(
        db, "ack_feedback_language_revision_render_v3",
        *_render_v3_args(db, context["owner"], revision, delivery, presentation_id),
    )
    rows(
        db,
        "INSERT INTO ml_rendered_exposures(presentation_id,actor_principal_id,"
        "render_instance_id,client_rendered_at,client_version,payload_sha256,"
        "idempotency_key) SELECT id,actor_principal_id,%s,clock_timestamp(),"
        "'d12-adversarial',visible_payload_sha256,%s FROM ml_presentations WHERE id=%s",
        (str(uuid4()), f"d12-second-exposure-{uuid4()}", presentation_id),
    )
    before = one(db, "SELECT count(*) n FROM confident_moment_bundle_projections")["n"]
    _assert_service_json_rejected(
        db,
        "project_confident_moment_bundles_v1",
        (context["owner"], context["project"], context["take"]),
        "CONFIDENT_MOMENT_PROJECTION_INVALID",
    )
    assert one(
        db, "SELECT count(*) n FROM confident_moment_bundle_projections"
    )["n"] == before


@pytest.mark.parametrize("first_committer", ["projection", "render"])
def test_projection_and_render_serialize_in_both_commit_orders(db, first_committer):
    context, _feedback, revision, delivery, presentation_id = (
        _render_projection_context(db)
    )
    prior = service_json_rpc(
        db, "project_confident_moment_bundles_v1",
        context["owner"], context["project"], context["take"],
    )
    assert _coach_projection_item(prior, revision["id"])["coach_update"]["unread"] is True
    db.commit()
    first = psycopg2.connect(db.dsn)
    second = psycopg2.connect(db.dsn)
    first.autocommit = False
    second.autocommit = False
    render_args = _render_v3_args(
        db, context["owner"], revision, delivery, presentation_id
    )

    def render(connection):
        with connection.cursor() as cur:
            cur.execute("SET application_name='d11-projection-render-worker'")
            cur.execute("SET ROLE service_role")
            cur.execute(
                "SELECT public.ack_feedback_language_revision_render_v3(%s,%s,%s,%s,%s,%s,%s,%s)",
                render_args,
            )
            result = cur.fetchone()[0]
            cur.execute("RESET ROLE")
        connection.commit()
        return result

    def project(connection):
        with connection.cursor() as cur:
            cur.execute("SET application_name='d11-projection-render-worker'")
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
                wait_for_lock(db, "d11-projection-render-worker", "advisory")
                assert not future.done()
                first.commit()
                future.result(timeout=10)
                assert first_result == prior
            else:
                with first.cursor() as cur:
                    cur.execute("SET ROLE service_role")
                    cur.execute(
                        "SELECT public.ack_feedback_language_revision_render_v3(%s,%s,%s,%s,%s,%s,%s,%s)",
                        render_args,
                    )
                    cur.fetchone()
                    cur.execute("RESET ROLE")
                future = pool.submit(project, second)
                wait_for_lock(db, "d11-projection-render-worker", "advisory")
                assert not future.done()
                first.commit()
                post = future.result(timeout=10)
                assert _coach_projection_item(post, revision["id"])[
                    "coach_update"
                ]["unread"] is False
        final = service_json_rpc(
            db, "project_confident_moment_bundles_v1",
            context["owner"], context["project"], context["take"],
        )
        assert _coach_projection_item(final, revision["id"])[
            "coach_update"
        ]["unread"] is False
        assert final["bundle_projection"]["response_sha256"] != prior["bundle_projection"]["response_sha256"]
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()
        # This test intentionally commits both immutable projection versions to
        # prove the race ordering. Remove only its disposable fixture records so
        # a later test's newly selected rollout does not make reapply correctly
        # reject this now-historical enrollment.
        db.rollback()
        rows(
            db,
            "ALTER TABLE confident_moment_bundle_projection_items DISABLE TRIGGER "
            "confident_moment_bundle_projection_items_append_only",
        )
        rows(
            db,
            "ALTER TABLE confident_moment_bundle_projections DISABLE TRIGGER "
            "confident_moment_bundle_projections_append_only",
        )
        try:
            rows(
                db,
                "DELETE FROM confident_moment_bundle_projection_items "
                "WHERE acquisition_principal_id=%s",
                (context["owner"],),
            )
            rows(
                db,
                "DELETE FROM confident_moment_bundle_projections "
                "WHERE acquisition_principal_id=%s",
                (context["owner"],),
            )
        finally:
            rows(
                db,
                "ALTER TABLE confident_moment_bundle_projection_items ENABLE TRIGGER "
                "confident_moment_bundle_projection_items_append_only",
            )
            rows(
                db,
                "ALTER TABLE confident_moment_bundle_projections ENABLE TRIGGER "
                "confident_moment_bundle_projections_append_only",
            )
        db.commit()


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
            wait_for_lock(db, "d11-legacy-root-order", "advisory")
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


@pytest.mark.parametrize("withdrawal", ["reviewer_access", "source_deletion"])
def test_invalidated_delivery_still_requires_live_coach_source_authority(
    db, withdrawal
):
    context, feedback, revision, delivery, _presentation_id = (
        _render_projection_context(db)
    )
    invalidated = service_json_rpc(
        db, "transition_feedback_language_delivery_v2",
        revision["id"], context["owner"], context["take"],
        feedback["candidate_id"], delivery["id"], "invalidate",
        f"d12-invalidated-authority-{uuid4()}",
    )
    assert invalidated["delivery_state"] == "invalidated"
    if withdrawal == "reviewer_access":
        _withdraw_reviewer_access(db, context["reviewer"])
    else:
        _delete_source_audio(db, context["owner"])
    db.commit()
    before = one(db, "SELECT count(*) n FROM confident_moment_bundle_projections")["n"]
    _assert_service_json_rejected(
        db, "project_confident_moment_bundles_v1",
        (context["owner"], context["project"], context["take"]),
        "COACH_GUIDANCE_REVIEWER_ACCESS_REQUIRED|MLC3_DUAL_PURPOSE_AUTHORITY_REQUIRED|CONFIDENT_MOMENT_PROJECTION_INVALID",
    )
    assert one(db, "SELECT count(*) n FROM confident_moment_bundle_projections")["n"] == before


def _ack_render(connection, args):
    with connection.cursor() as cur:
        cur.execute("SET ROLE service_role")
        cur.execute(
            "SELECT public.ack_feedback_language_revision_render_v3(%s,%s,%s,%s,%s,%s,%s,%s)",
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
    context, _feedback, revision, delivery, presentation_id = (
        _render_projection_context(db)
    )
    db.commit()
    before = one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"]
    render_args = _render_v3_args(
        db, context["owner"], revision, delivery, presentation_id
    )
    first = psycopg2.connect(db.dsn)
    second = psycopg2.connect(db.dsn)
    first.autocommit = False
    second.autocommit = False

    def withdraw(connection):
        with connection.cursor() as cur:
            cur.execute("SET application_name='d11-render-authority-withdrawal'")
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
        expected_error = (
            "COACH_GUIDANCE_REVIEWER_ACCESS_REQUIRED"
            if withdrawal == "reviewer_access"
            else "MLC3_DUAL_PURPOSE_AUTHORITY_REQUIRED"
        )
        if first_committer == "withdrawal":
            withdraw(first)
            with pytest.raises(psycopg2.Error, match=expected_error):
                render(second)
            second.rollback()
            assert one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"] == before
        else:
            with ThreadPoolExecutor(max_workers=1) as pool:
                _ack_render(first, render_args)
                if withdrawal == "reviewer_access":
                    # Hold the exact reviewer leaf so the opposing writer's
                    # commit order is observed, not inferred from a sleep.
                    with first.cursor() as cur:
                        cur.execute(
                            "SELECT coach.id FROM coach_users coach "
                            "JOIN auth.users auth_user ON lower(auth_user.email)="
                            "lower(coach.email) JOIN owner_principals principal "
                            "ON principal.user_id=auth_user.id "
                            "WHERE principal.id=%s FOR UPDATE OF coach",
                            (context["reviewer"],),
                        )
                future = pool.submit(withdraw, second)
                wait_for_lock(
                    db,
                    "d11-render-authority-withdrawal",
                    "transactionid" if withdrawal == "reviewer_access" else "advisory",
                )
                first.commit()
                future.result(timeout=10)
            assert one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"] == before + 1
            with pytest.raises(psycopg2.Error, match=expected_error):
                _ack_render(
                    db,
                    _render_v3_args(
                        db, context["owner"], revision, delivery, presentation_id
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
    context, _feedback, revision, delivery, presentation_id = (
        _render_projection_context(db)
    )
    before = one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"]
    render_args = _render_v3_args(
        db, context["owner"], revision, delivery, presentation_id
    )
    first_result = _ack_render(db, render_args)
    assert _ack_render(db, render_args) == first_result
    assert one(db, "SELECT count(*) n FROM ml_rendered_exposures")["n"] == before + 1


def test_ack_render_rejects_a_delivery_whose_lineage_is_not_exact_v2(db):
    """A legacy or forked delivery head can never authorise an exposure."""
    context, _feedback, revision, delivery, presentation_id = (
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
        "ack_feedback_language_revision_render_v3",
        _render_v3_args(
            db, context["owner"], revision,
            {**delivery, "id": legacy_delivery_id}, presentation_id,
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
        "confident_moment_projection_item_exclusion_reason_check",
        "confident_moment_projection_item_coach_presentation_check",
    } <= installed
    assert {
        "presentation_id", "rendered_exposure_id", "unread",
        "feedback_family", "canonical_feedback_exposure_id",
    } <= (
        _projection_item_columns(db)
    )

    # Every forbidden shape must be rejected by the database itself.
    forbidden = [
        # machine_fallback carrying another attachment's coach render state
        ("machine_fallback", None, None, None, True),
        # excluded carrying an unread coach flag
        ("excluded", "machine_output_invalid", None, None, True),
        # arbitrary free text is not an allowed product exclusion
        ("excluded", "unreviewed_free_text", None, None, False),
        # coach_revision without its own revision identity
        ("coach_revision", None, None, None, False),
    ]
    # The migration file commits itself, so each probe runs in its own
    # transaction and is rolled back after the expected rejection.
    for state, exclusion, revision_id, delivery_id, unread in forbidden:
        with db.cursor() as cur:
            with pytest.raises(psycopg2.Error) as failure:
                cur.execute(
                    "INSERT INTO public.confident_moment_bundle_projection_items("
                    "projection_id,acquisition_principal_id,bundle_attachment_id,"
                    "bundle_subject_candidate_id,attached_candidate_id,"
                    "feedback_family,canonical_feedback_exposure_id,"
                    "resolution_state,exclusion_reason,revision_id,delivery_id,"
                    "candidate_output_sha256,output_sha256,canonical_position,"
                    "item_sha256,unread) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s)",
                    (
                        str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4()),
                        str(uuid4()), "confident_voice", str(uuid4()), state,
                        exclusion, revision_id, delivery_id,
                        "a" * 64, "a" * 64, "b" * 64, unread,
                    ),
                )
            assert failure.value.diag.constraint_name in {
                "confident_moment_projection_item_state_shape_check",
                "confident_moment_projection_item_render_shape_check",
                "confident_moment_projection_item_exclusion_reason_check",
                "confident_moment_projection_item_coach_presentation_check",
            }
            db.rollback()


def test_coach_projection_item_requires_exact_nonnull_presentation(db):
    context, _feedback, revision, _delivery, _presentation_id = (
        _render_projection_context(db)
    )
    projected = service_json_rpc(
        db, "project_confident_moment_bundles_v1",
        context["owner"], context["project"], context["take"],
    )
    source_projection_id = one(
        db,
        "SELECT id FROM confident_moment_bundle_projections WHERE response_sha256=%s",
        (projected["bundle_projection"]["response_sha256"],),
    )["id"]
    replacement_projection_id = str(uuid4())
    rows(
        db,
        "INSERT INTO confident_moment_bundle_projections("
        "id,acquisition_principal_id,project_id,take_id,feedback_membership_id,"
        "document_snapshot_id,document_snapshot_sha256,projection_policy_version,"
        "projection_code_version,stabilized_inventory_sha256,response_sha256,"
        "idempotency_key) SELECT %s,acquisition_principal_id,project_id,take_id,"
        "feedback_membership_id,document_snapshot_id,document_snapshot_sha256,"
        "projection_policy_version,projection_code_version,%s,%s,%s FROM "
        "confident_moment_bundle_projections WHERE id=%s",
        (
            replacement_projection_id, uuid4().hex * 2, uuid4().hex * 2,
            f"d12-null-presentation-projection-{uuid4()}", source_projection_id,
        ),
    )
    with db.cursor() as cur:
        with pytest.raises(psycopg2.Error) as failure:
            cur.execute(
                "INSERT INTO confident_moment_bundle_projection_items("
                "projection_id,acquisition_principal_id,bundle_attachment_id,"
                "bundle_subject_candidate_id,attached_candidate_id,feedback_family,"
                "canonical_feedback_exposure_id,anchor_candidate_id,"
                "resolution_state,exclusion_reason,revision_id,delivery_id,"
                "presentation_id,rendered_exposure_id,unread,candidate_output_sha256,"
                "output_sha256,canonical_position,exercise_present,item_sha256) "
                "SELECT %s,acquisition_principal_id,bundle_attachment_id,"
                "bundle_subject_candidate_id,attached_candidate_id,feedback_family,"
                "canonical_feedback_exposure_id,anchor_candidate_id,"
                "resolution_state,exclusion_reason,revision_id,delivery_id,NULL,"
                "rendered_exposure_id,unread,candidate_output_sha256,output_sha256,"
                "canonical_position,exercise_present,item_sha256 FROM "
                "confident_moment_bundle_projection_items WHERE projection_id=%s "
                "AND revision_id=%s",
                (replacement_projection_id, source_projection_id, revision["id"]),
            )
        assert failure.value.diag.constraint_name == (
            "confident_moment_projection_item_coach_presentation_check"
        )
    db.rollback()


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
        "item_output:=NULL",
        "item_coach_update:=NULL",
        "revision_sha256:=NULL",
        "delivery_subject_sha256:=NULL",
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
    # D12 retains only an existential bundle summary fold. All identity remains
    # inside the attachment-scoped array entry.
    assert "feedback_language_items:='[]'::jsonb" in source
    assert "bundle_unread" in source
    assert "'feedback_language_items',feedback_language_items" in source
    assert "'coach_update',CASE WHEN resolution='coach_revision'" in source
    assert "'output',CASE WHEN resolution='excluded' THEN NULL" in source
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
               "public.ack_feedback_language_revision_render_v3",
               "public.ack_confident_moment_bundle_item_render_v3",
               "public.read_feedback_v3_candidate_source_snapshot_v1",
               "public.record_confident_moment_bundle_family_response_v1",
               "public.record_confident_moment_bundle_root_action_v1",
               "public.compare_and_set_user_ideal_edit_v1",
               "public.apply_confident_moment_bundle_text_update_v1",
               "public.freeze_confident_moment_coach_authorability_inventory_v1",
                   "public.publish_confident_moment_coach_feedback_language_v1",
                   "public.materialize_feedback_language_delivery_job_v1",
                   "public.project_confident_moment_coach_authoring_context_v2",
                   "public.begin_feedback_language_delivery_scan_run_v1",
                   "public.mark_feedback_language_delivery_scan_started_v1",
                   "public.abandon_feedback_language_delivery_scan_run_v1",
                   "public.scan_due_feedback_language_delivery_jobs_v1",
                   "public.arm_feedback_language_delivery_jobs_for_take_v1",
                   "public.read_ideal_text_document_core_v2",
                       "public.get_mlc3_general_service_monitor_v2",
                       "public.halt_mlc3_for_stalled_delivery_scan_v1",
                       "public.resolve_confident_moment_source_playback_authority_v1",
                       "public.resolve_confident_moment_exercise_offer_v1",
                       "public.authorize_confident_moment_source_playback_emit_v1"}
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
    body = _function_body("ack_feedback_language_revision_render_v3")
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
    body = _function_body("ack_feedback_language_revision_render_v3")
    assert body.count("require_feedback_language_coach_source_live_v1(") == 2
    assert "revision.candidate_output_sha256,'FEEDBACK_LANGUAGE" not in body
    assert body.count(
        "public.feedback_candidate_output_sha256_v1(revision.feedback_candidate_id)"
    ) == 2


def test_d12_projection_uses_only_attachment_scoped_feedback_language_items(db):
    """D12 retires the lossy Bundle-level wording/currentness fold."""
    body = _function_body("project_confident_moment_bundles_v1")
    assert "'contract_version','confident-moment-coaching-bundle-v2'" in body
    assert "'feedback_language_shape_version','feedback-language-items-v2'" in body
    assert "'feedback_language_items',feedback_language_items" in body
    assert "'comment',comment_payload" not in body
    assert "'rephrase',rephrase_payload" not in body
    assert "bundle_coach_revision_id" not in body


def test_d20_d25_new_tables_are_forced_rls_append_only_and_rpc_only(db):
    _install_released_render_ack(db)
    with db.cursor() as cur:
        cur.execute(SQL)
    tables = (
        "ideal_text_user_edit_cas_operations",
        "confident_moment_bundle_text_update_bindings",
        "confident_moment_coach_authorability_inventories",
        "confident_moment_coach_authorability_items",
        "confident_moment_blind_assignment_bindings",
        "confident_moment_coach_wording_authority_bindings",
        "feedback_language_delivery_materialization_jobs",
        "feedback_language_delivery_materialization_job_events",
    )
    for table in tables:
        state = one(db, "SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=('public.'||%s)::regclass", (table,))
        assert state == {"relrowsecurity": True, "relforcerowsecurity": True}
        for role in ("anon", "authenticated", "service_role"):
            for privilege in ("INSERT", "UPDATE", "DELETE"):
                assert one(db, "SELECT has_table_privilege(%s,'public.'||%s,%s) granted", (role, table, privilege))["granted"] is False


def test_d21_owner_lane_guard_allows_notebook_only_but_rejects_direct_owner_edit(db):
    _install_released_render_ack(db)
    with db.cursor() as cur:
        cur.execute(SQL)
        arc = "guard-" + str(uuid4())
        user = str(uuid4())
        cur.execute("INSERT INTO user_arc_ideal_notes(arc_id,user_id,text) VALUES(%s,%s,%s)", (arc, user, "notebook"))
        cur.execute("UPDATE user_arc_ideal_notes SET text=%s WHERE arc_id=%s AND user_id=%s", ("notebook updated", arc, user))
        with pytest.raises(psycopg2.Error, match="IDEAL_TEXT_OWNER_LANE_RPC_REQUIRED"):
            cur.execute("UPDATE user_arc_ideal_notes SET user_text=%s,user_text_version=1,user_text_revision=1 WHERE arc_id=%s AND user_id=%s", ("owner", arc, user))
        db.rollback()


def test_d14_d25_exact_rpc_signatures_and_trigger_are_installed(db):
    _install_released_render_ack(db)
    with db.cursor() as cur:
        cur.execute(SQL)
    signatures = (
        "public.read_feedback_v3_candidate_source_snapshot_v1(uuid,uuid,uuid)",
        "public.record_confident_moment_bundle_family_response_v1(uuid,uuid,uuid,uuid,uuid,text,text)",
        "public.record_confident_moment_bundle_root_action_v1(uuid,uuid,uuid,text,uuid,uuid,uuid,uuid,bigint,uuid,uuid,uuid,uuid,text,text)",
        "public.compare_and_set_user_ideal_edit_v1(uuid,text,integer,bigint,text,text,jsonb,text)",
        "public.apply_confident_moment_bundle_text_update_v1(uuid,uuid,uuid,uuid,uuid,uuid,uuid,integer,bigint,bigint,text,jsonb,text)",
        "public.freeze_confident_moment_coach_authorability_inventory_v1(uuid,uuid,uuid,uuid,uuid,text)",
        "public.publish_confident_moment_coach_feedback_language_v1(uuid,uuid,uuid,uuid,uuid,uuid,uuid,text,text,text,uuid,uuid,text)",
        "public.materialize_feedback_language_delivery_job_v1(uuid,text)",
        "public.project_confident_moment_coach_authoring_context_v1(uuid,uuid,uuid,text)",
        "public.project_confident_moment_coach_authoring_context_v2(uuid,uuid,text)",
    )
    for signature in signatures:
        assert one(db, "SELECT to_regprocedure(%s) IS NOT NULL present", (signature,))["present"]
    trigger = one(db, "SELECT p.proname function_name FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid WHERE t.tgrelid='public.user_arc_ideal_notes'::regclass AND t.tgname='user_arc_ideal_notes_user_text_cas_guard' AND NOT t.tgisinternal")
    assert trigger["function_name"] == "guard_user_ideal_edit_cas_v1"


def test_d26_database_derived_coach_context_is_sole_runtime_wrapper(db):
    _install_released_render_ack(db)
    with db.cursor() as cur:
        cur.execute(SQL)
    v1 = "public.project_confident_moment_coach_authoring_context_v1(uuid,uuid,uuid,text)"
    v2 = "public.project_confident_moment_coach_authoring_context_v2(uuid,uuid,text)"
    assert one(db, "SELECT has_function_privilege('service_role',%s,'EXECUTE') allowed", (v1,))["allowed"] is False
    assert one(db, "SELECT has_function_privilege('service_role',%s,'EXECUTE') allowed", (v2,))["allowed"] is True
    for role in ("anon", "authenticated"):
        assert one(db, "SELECT has_function_privilege(%s,%s,'EXECUTE') allowed", (role, v2))["allowed"] is False
    assert one(db, "SELECT NOT EXISTS(SELECT 1 FROM pg_proc p, LATERAL aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) acl WHERE p.oid=%s::regprocedure AND acl.grantee=0 AND acl.privilege_type='EXECUTE') allowed", (v2,))["allowed"] is True


def test_d19_d24_owner_text_and_part_storage_is_forced_rls_rpc_write_only(db):
    _install_released_render_ack(db)
    with db.cursor() as cur:
        cur.execute(SQL)
    for table in ("user_arc_ideal_notes", "ideal_text_part", "ideal_text_part_revision"):
        state = one(db, "SELECT relrowsecurity rls,relforcerowsecurity force FROM pg_class WHERE oid=%s::regclass", (f"public.{table}",))
        assert state == {"rls": True, "force": True}
        for role in ("anon", "authenticated", "service_role"):
            for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                assert one(db, "SELECT has_table_privilege(%s,%s,%s) writable", (role, f"public.{table}", privilege))["writable"] is False


def test_d17_d18_context_is_embedded_per_exact_revealed_item(db):
    _install_released_render_ack(db)
    with db.cursor() as cur:
        cur.execute(SQL)
    body = one(db, "SELECT pg_get_functiondef(%s::regprocedure) body", (
        "public.project_confident_moment_coach_authoring_context_v1(uuid,uuid,uuid,text)",
    ))["body"]
    assert "bundle_authoring_context" in body
    assert "source_review_attachment_id" in body
    assert "authorized_targets" in body
    assert "target_binding.review_assignment_id=source_binding.review_assignment_id" in body
    assert "expected_current_revision_id" in body
    assert "expected_current_delivery_id" in body
    assert "confident_moment_authoring_targets" not in body


def test_d22_d23_structural_cas_is_atomic_versioned_and_exactly_replayable(db):
    """Bootstrap and every unlocked structural action share one CAS unit."""
    context, _feedback = _positive_projection_context(db)
    owner_user_id = one(
        db, "SELECT user_id FROM owner_principals WHERE id=%s", (context["owner"],)
    )["user_id"]
    arc_id = context["project"]
    first, second, third = str(uuid4()), str(uuid4()), str(uuid4())

    def invoke(expected_revision, expected_hash, expected, desired, text, key):
        return one(
            db,
            "SELECT compare_and_set_user_ideal_edit_v1("
            "%s,%s,1,%s,%s,%s,%s::jsonb,%s) result",
            (
                owner_user_id,
                arc_id,
                expected_revision,
                expected_hash,
                text,
                Json({"expected_parts": expected, "desired_parts": desired}),
                key,
            ),
        )["result"]

    desired_v1 = [
        {"position": 0, "part_id": first, "text": "First"},
        {"position": 1, "part_id": second, "text": "Second"},
    ]
    key_v1 = f"owner-bootstrap-{uuid4()}"
    v1 = invoke(None, None, [], desired_v1, "First\n\nSecond", key_v1)
    assert [entry["action"] for entry in v1["part_revisions"]] == [
        "owner_part_created",
        "owner_part_created",
    ]
    assert invoke(None, None, [], desired_v1, "First\n\nSecond", key_v1) == v1

    expected_v1 = rows(
        db,
        "SELECT p.ord position,p.id part_id,exercise_text_sha256_v1(p.text) "
        "text_sha256,(p.locked_at IS NOT NULL) locked,"
        "(SELECT r.id::text FROM ideal_text_part_revision r WHERE r.part_id=p.id "
        "ORDER BY r.id DESC LIMIT 1) current_part_revision_id "
        "FROM ideal_text_part p WHERE p.arc_id=%s AND p.user_id=%s "
        "ORDER BY p.ord",
        (arc_id, str(owner_user_id)),
    )
    expected_v1 = [dict(item) for item in expected_v1]
    desired_v2 = [
        {"position": 0, "part_id": second, "text": "Second updated"},
        {"position": 1, "part_id": third, "text": "Third"},
    ]
    key_v2 = f"owner-structure-{uuid4()}"
    v2 = invoke(
        1,
        v1["result_user_text_sha256"],
        expected_v1,
        desired_v2,
        "Second updated\n\nThird",
        key_v2,
    )
    assert {entry["action"] for entry in v2["part_revisions"]} == {
        "owner_part_removed",
        "owner_part_text_updated_and_reordered",
        "owner_part_created",
    }
    assert one(db, "SELECT count(*) n FROM ideal_text_part WHERE id=%s", (first,))["n"] == 0
    assert one(
        db,
        "SELECT action FROM ideal_text_part_revision WHERE part_id=%s "
        "ORDER BY id DESC LIMIT 1",
        (first,),
    )["action"] == "owner_part_removed"
    assert invoke(
        1,
        v1["result_user_text_sha256"],
        expected_v1,
        desired_v2,
        "Second updated\n\nThird",
        key_v2,
    ) == v2

    expected_v2 = [
        dict(item)
        for item in rows(
            db,
            "SELECT p.ord position,p.id part_id,exercise_text_sha256_v1(p.text) "
            "text_sha256,(p.locked_at IS NOT NULL) locked,"
            "(SELECT r.id::text FROM ideal_text_part_revision r WHERE r.part_id=p.id "
            "ORDER BY r.id DESC LIMIT 1) current_part_revision_id "
            "FROM ideal_text_part p WHERE p.arc_id=%s AND p.user_id=%s ORDER BY p.ord",
            (arc_id, str(owner_user_id)),
        )
    ]
    desired_v3 = [
        {"position": 0, "part_id": second, "text": "Second updated"},
        {"position": 1, "part_id": third, "text": "Third legacy"},
    ]
    legacy = invoke(
        2,
        v2["result_user_text_sha256"],
        expected_v2,
        desired_v3,
        "Second updated\n\nThird legacy",
        None,
    )
    assert invoke(
        2,
        v2["result_user_text_sha256"],
        expected_v2,
        desired_v3,
        "Second updated\n\nThird legacy",
        None,
    ) == legacy
    expected_v3 = [
        dict(item)
        for item in rows(
            db,
            "SELECT p.ord position,p.id part_id,exercise_text_sha256_v1(p.text) "
            "text_sha256,(p.locked_at IS NOT NULL) locked,"
            "(SELECT r.id::text FROM ideal_text_part_revision r WHERE r.part_id=p.id "
            "ORDER BY r.id DESC LIMIT 1) current_part_revision_id "
            "FROM ideal_text_part p WHERE p.arc_id=%s AND p.user_id=%s ORDER BY p.ord",
            (arc_id, str(owner_user_id)),
        )
    ]
    desired_v4 = [
        {"position": 0, "part_id": second, "text": "Second updated"},
        {"position": 1, "part_id": third, "text": "Third current"},
    ]
    v4 = invoke(
        3,
        legacy["result_user_text_sha256"],
        expected_v3,
        desired_v4,
        "Second updated\n\nThird current",
        f"intervening-{uuid4()}",
    )
    rows(db, "SAVEPOINT legacy_replay")
    with pytest.raises(psycopg2.Error, match="IDEAL_TEXT_LEGACY_REPLAY_CONFLICT"):
        invoke(
            2,
            v2["result_user_text_sha256"],
            expected_v2,
            desired_v3,
            "Second updated\n\nThird legacy",
            None,
        )
    rows(db, "ROLLBACK TO SAVEPOINT legacy_replay")

    # A protected part cannot be edited or displaced; the whole operation
    # rolls back without appending an owner-edit operation or part revision.
    rows(db, "UPDATE ideal_text_part SET root_phrase=text WHERE id=%s", (second,))
    expected_v2 = rows(
        db,
        "SELECT p.ord position,p.id part_id,exercise_text_sha256_v1(p.text) "
        "text_sha256,(p.locked_at IS NOT NULL) locked,"
        "(SELECT r.id::text FROM ideal_text_part_revision r WHERE r.part_id=p.id "
        "ORDER BY r.id DESC LIMIT 1) current_part_revision_id "
        "FROM ideal_text_part p WHERE p.arc_id=%s AND p.user_id=%s ORDER BY p.ord",
        (arc_id, str(owner_user_id)),
    )
    before = one(db, "SELECT count(*) n FROM ideal_text_user_edit_cas_operations")["n"]
    before_revisions = one(
        db, "SELECT count(*) n FROM ideal_text_part_revision WHERE part_id=%s", (second,)
    )["n"]
    rows(db, "SAVEPOINT protected_edit")
    with pytest.raises(psycopg2.Error, match="IDEAL_TEXT_PART_REQUIRES_UNLOCK"):
        invoke(
            4,
            v4["result_user_text_sha256"],
            [dict(item) for item in expected_v2],
            [
                {"position": 0, "part_id": second, "text": "Changed again"},
                {"position": 1, "part_id": third, "text": "Third current"},
            ],
            "Changed again\n\nThird current",
            f"protected-{uuid4()}",
        )
    rows(db, "ROLLBACK TO SAVEPOINT protected_edit")
    assert one(db, "SELECT count(*) n FROM ideal_text_user_edit_cas_operations")["n"] == before
    assert one(
        db, "SELECT count(*) n FROM ideal_text_part_revision WHERE part_id=%s", (second,)
    )["n"] == before_revisions


def test_d23_legacy_parts_are_server_normalized_and_missing_parts_cannot_resegment(db):
    """Old clients use the same locked CAS, never a restored direct writer."""
    context, _feedback = _positive_projection_context(db)
    owner_user_id = one(
        db, "SELECT user_id FROM owner_principals WHERE id=%s", (context["owner"],)
    )["user_id"]
    part_id = str(uuid4())
    legacy_parts = [{"id": part_id, "ord": 0, "text": "One exact paragraph"}]
    created = one(
        db,
        "SELECT compare_and_set_user_ideal_edit_v1(%s,%s,1,NULL,NULL,%s,%s::jsonb,NULL) result",
        (owner_user_id, context["project"], "One exact paragraph", Json(legacy_parts)),
    )["result"]
    assert created["saved"] is True
    assert created["part_revisions"][0]["action"] == "owner_part_created"
    assert one(
        db,
        "SELECT compare_and_set_user_ideal_edit_v1(%s,%s,1,NULL,NULL,%s,NULL,NULL) result",
        (owner_user_id, context["project"], "One exact paragraph"),
    )["result"] == created
    rows(db, "SAVEPOINT legacy_without_parts")
    with pytest.raises(psycopg2.Error, match="IDEAL_TEXT_CAS_REQUIRED"):
        one(
            db,
            "SELECT compare_and_set_user_ideal_edit_v1(%s,%s,1,NULL,NULL,%s,NULL,NULL)",
            (owner_user_id, context["project"], "A different paragraph"),
        )
    rows(db, "ROLLBACK TO SAVEPOINT legacy_without_parts")


def test_d29_d37_scheduler_schema_permissions_and_retired_identity(db):
    with db.cursor() as cur:
        cur.execute(SQL)
    for table in (
        "feedback_language_delivery_job_claim_attempts",
        "feedback_language_delivery_job_claim_heads",
        "feedback_language_delivery_job_due_heads",
        "feedback_language_delivery_scan_runs",
        "feedback_language_delivery_stalled_scan_halt_receipts",
        "feedback_language_delivery_take_arm_operations",
    ):
        state = one(db, "SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=('public.'||%s)::regclass", (table,))
        assert state == {"relrowsecurity": True, "relforcerowsecurity": True}
        for role in ("anon", "authenticated", "service_role"):
            assert one(db, "SELECT has_table_privilege(%s,'public.'||%s,'INSERT,UPDATE,DELETE') granted", (role, table))["granted"] is False
    assert one(db, "SELECT to_regprocedure('public.claim_due_feedback_language_delivery_jobs_v1(uuid,text,integer,integer,integer)') IS NULL gone")["gone"] is True
    signature = "scan_due_feedback_language_delivery_jobs_v1(uuid,text,integer,integer,integer)"
    assert one(db, "SELECT has_function_privilege('service_role',%s,'EXECUTE') granted", (signature,))["granted"] is True
    for role in ("anon", "authenticated"):
        assert one(db, "SELECT has_function_privilege(%s,%s,'EXECUTE') granted", (role, signature))["granted"] is False


def _pending_delivery_job_context(db):
    """Create one canonical no-target coach revision and its durable job."""
    _install_released_render_ack(db)
    with db.cursor() as cur:
        cur.execute(SQL)
    context, feedback, batch, grant, judgment, item = _feedback_language_context(db)
    prepared = one(
        db,
        "SELECT prepare_confident_moment_bundle_v1(%s,%s,%s,%s,%s,%s) payload",
        (context["owner"], context["project"], context["take"],
         feedback["membership"]["id"], feedback["candidate_id"],
         f"scheduler-prepare-{uuid4()}"),
    )["payload"]
    service_json_rpc(
        db, "freeze_confident_moment_coach_authorability_inventory_v1",
        context["owner"], context["project"], context["take"],
        feedback["membership"]["id"], feedback["document_id"],
        f"scheduler-authorability-{uuid4()}",
    )
    render = service_rpc(
        db, "ack_feedback_v3_service_render_v1", context["owner"],
        feedback["owner_user"], feedback["membership"]["id"],
        feedback["candidate_id"], feedback["exposure_id"], str(uuid4()),
        feedback["membership"]["content_identity_sha256"],
        one(db, "SELECT clock_timestamp() value")["value"],
        "postgres-rehearsal", f"scheduler-render-{uuid4()}",
    )
    service_json_rpc(
        db, "record_feedback_v3_service_response_v1", context["project"],
        context["take"], context["owner"], feedback["owner_user"],
        feedback["membership"]["id"], feedback["candidate_id"],
        feedback["exposure_id"], render["id"], "confident_yes",
        f"scheduler-response-{uuid4()}",
    )
    output_hash = one(
        db, "SELECT feedback_candidate_output_sha256_v1(%s) value",
        (feedback["candidate_id"],),
    )["value"]
    assert one(
        db, "SELECT count(*) n FROM confident_moment_blind_assignment_bindings "
        "WHERE bundle_attachment_id=%s AND review_batch_id=%s AND review_assignment_id=%s",
        (prepared["attachments"][0]["id"], batch["id"], item["review_assignment_id"]),
    )["n"] == 1
    published = service_json_rpc(
        db, "publish_confident_moment_coach_feedback_language_v1",
        context["reviewer"], prepared["bundle_id"],
        prepared["attachments"][0]["id"], batch["id"], grant["id"],
        item["reveal_access_id"], item["review_assignment_id"],
        "comment", "confidence_explanation", "Keep this delivery clear.",
        None, None, f"scheduler-publish-{uuid4()}",
    )
    job = one(
        db, "SELECT * FROM feedback_language_delivery_materialization_jobs "
        "WHERE revision_id=%s", (published["revision_id"],),
    )
    return context, feedback, prepared, published, job, (
        batch, grant, judgment, item, output_hash,
    )


def _insert_next_take(db, context):
    take_id = str(uuid4())
    rows(
        db,
        "INSERT INTO v2_sessions(id,user_id,owner_principal_id,project_id,arc_id,"
        "take_index,recording_kind,analysis_state) SELECT %s,user_id,owner_principal_id,"
        "project_id,arc_id,take_index+1,recording_kind,'ready' FROM v2_sessions WHERE id=%s",
        (take_id, context["take"]),
    )
    return take_id


def _claim_one_delivery_job(db, job_id):
    worker, run = "c" * 64, str(uuid4())
    one(db, "SELECT begin_feedback_language_delivery_scan_run_v1(%s,%s,%s)",
        (run, worker, f"delivery-scan-begin-v1:{run}:{worker}"))
    one(db, "SELECT mark_feedback_language_delivery_scan_started_v1(%s,%s,%s)",
        (run, worker, f"delivery-scan-start-v1:{run}:{worker}"))
    result = one(
        db, "SELECT scan_due_feedback_language_delivery_jobs_v1(%s,%s,3,60,1000) result",
        (run, worker),
    )["result"]
    assert result["jobs"] == [{"job_id": job_id}]
    assert result["contention_nowait_count"] == 0
    return result


def test_d43_scanner_authority_withdrawal_closes_stale_and_replays_without_delivery(db):
    context, _feedback, _prepared, _published, job, _authority = (
        _pending_delivery_job_context(db)
    )
    _insert_next_take(db, context)
    before = one(db, "SELECT count(*) n FROM feedback_language_revision_deliveries")["n"]
    rows(
        db,
        "SELECT halt_mlc3_service_rollout_v1(%s,%s)",
        ("d43-authority-withdrawal", uuid4().hex * 2),
    )
    worker, run = "d" * 64, str(uuid4())
    one(db, "SELECT begin_feedback_language_delivery_scan_run_v1(%s,%s,%s)",
        (run, worker, f"delivery-scan-begin-v1:{run}:{worker}"))
    one(db, "SELECT mark_feedback_language_delivery_scan_started_v1(%s,%s,%s)",
        (run, worker, f"delivery-scan-start-v1:{run}:{worker}"))
    scanned = one(
        db, "SELECT scan_due_feedback_language_delivery_jobs_v1(%s,%s,3,60,1000) result",
        (run, worker),
    )["result"]
    assert scanned["jobs"] == []
    assert scanned["item_results"] == [
        {"result": "closed_stale", "cause_code": "authority_withdrawn"}
    ]
    assert one(
        db,
        "SELECT job_state FROM feedback_language_delivery_materialization_jobs WHERE id=%s",
        (job["id"],),
    )["job_state"] == "closed_stale"
    assert one(
        db,
        "SELECT event_kind,cause_code FROM feedback_language_delivery_materialization_job_events "
        "WHERE job_id=%s",
        (job["id"],),
    ) == {"event_kind": "closed_stale", "cause_code": "authority_withdrawn"}
    assert one(db, "SELECT count(*) n FROM feedback_language_revision_deliveries")["n"] == before
    key = f"materialize:{job['id']}"
    replay = service_json_rpc(
        db, "materialize_feedback_language_delivery_job_v1", str(job["id"]), key,
    )
    assert replay == {
        "job_id": str(job["id"]), "job_state": "closed_stale",
        "delivery_id": None, "cause_code": "authority_withdrawn",
        "dataset_eligible": False,
    }
    assert service_json_rpc(
        db, "materialize_feedback_language_delivery_job_v1", str(job["id"]), key,
    ) == replay
    assert one(db, "SELECT count(*) n FROM feedback_language_revision_deliveries")["n"] == before


def test_d46_phase3_emit_authorization_is_exact_stateless_and_hash_bound(db):
    context, feedback = _positive_projection_context(db)
    prepared = one(
        db,
        "SELECT prepare_confident_moment_bundle_v1(%s,%s,%s,%s,%s,%s) payload",
        (context["owner"], context["project"], context["take"],
         feedback["membership"]["id"], feedback["candidate_id"],
         f"d46-prepare-{uuid4()}"),
    )["payload"]
    attachment_id = prepared["attachments"][0]["id"]
    before = one(
        db,
        "SELECT (SELECT count(*) FROM ml_rendered_exposures) exposures,"
        "(SELECT count(*) FROM feedback_v3_owner_responses) responses,"
        "(SELECT count(*) FROM exercise_service_offers) offers",
    )
    phase1 = service_json_rpc(
        db, "resolve_confident_moment_source_playback_authority_v1",
        context["owner"], prepared["bundle_id"], attachment_id,
    )
    request_id = str(uuid4())
    phase3 = service_json_rpc(
        db, "authorize_confident_moment_source_playback_emit_v1",
        context["owner"], prepared["bundle_id"], attachment_id,
        phase1["authority_sha256"], phase1["exact_bytes_sha256"], request_id,
    )
    assert set(phase3) == {
        "contract_version", "playback_request_id", "acquisition_principal_id",
        "bundle_id", "bundle_attachment_id", "authority_sha256",
        "buffered_bytes_sha256", "authorized_at", "emit_authorized",
        "emit_authorization_sha256", "dataset_eligible",
    }
    assert phase3["contract_version"] == "confident-moment-source-playback-emit-v1"
    assert phase3["playback_request_id"] == request_id
    assert phase3["emit_authorized"] is True
    assert phase3["dataset_eligible"] is False
    assert one(
        db,
        "SELECT exercise_json_sha256_v1((%s::jsonb)-'emit_authorization_sha256') value",
        (Json(phase3),),
    )["value"] == phase3["emit_authorization_sha256"]
    assert one(
        db,
        "SELECT (SELECT count(*) FROM ml_rendered_exposures) exposures,"
        "(SELECT count(*) FROM feedback_v3_owner_responses) responses,"
        "(SELECT count(*) FROM exercise_service_offers) offers",
    ) == before
    for expected, buffered, error in (
        (uuid4().hex * 2, phase1["exact_bytes_sha256"], "CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED"),
        (phase1["authority_sha256"], uuid4().hex * 2, "CONFIDENT_MOMENT_SOURCE_MEDIA_POLICY_INVALID"),
    ):
        _assert_service_json_rejected(
            db, "authorize_confident_moment_source_playback_emit_v1",
            (context["owner"], prepared["bundle_id"], attachment_id,
             expected, buffered, str(uuid4())), error,
        )


@pytest.mark.parametrize("first_committer", ["deletion", "phase3"])
def test_d46_phase3_serializes_source_deletion_in_both_orders(
    db, first_committer
):
    """D44/D46: only a current, fully locked phase-3 decision authorizes emit."""
    context, feedback = _positive_projection_context(db)
    prepared = one(
        db,
        "SELECT prepare_confident_moment_bundle_v1(%s,%s,%s,%s,%s,%s) payload",
        (context["owner"], context["project"], context["take"],
         feedback["membership"]["id"], feedback["candidate_id"],
         f"d46-race-prepare-{uuid4()}"),
    )["payload"]
    attachment_id = prepared["attachments"][0]["id"]
    phase1 = service_json_rpc(
        db, "resolve_confident_moment_source_playback_authority_v1",
        context["owner"], prepared["bundle_id"], attachment_id,
    )
    arguments = (
        context["owner"], prepared["bundle_id"], attachment_id,
        phase1["authority_sha256"], phase1["exact_bytes_sha256"], str(uuid4()),
    )
    db.commit()
    phase3_connection = psycopg2.connect(db.dsn)
    deletion_connection = psycopg2.connect(db.dsn)
    phase3_connection.autocommit = False
    deletion_connection.autocommit = False

    def authorize(connection):
        return service_json_rpc(
            connection,
            "authorize_confident_moment_source_playback_emit_v1",
            *arguments,
        )

    def delete(connection):
        rows(connection, "SET application_name='d46-phase3-source-deletion'")
        _delete_source_audio(connection, context["owner"])
        connection.commit()

    try:
        if first_committer == "deletion":
            delete(deletion_connection)
            _assert_service_json_rejected(
                phase3_connection,
                "authorize_confident_moment_source_playback_emit_v1",
                arguments,
                "CONFIDENT_MOMENT_SOURCE_MEDIA_POLICY_INVALID",
            )
        else:
            receipt = authorize(phase3_connection)
            assert receipt["emit_authorized"] is True
            assert receipt["dataset_eligible"] is False
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(delete, deletion_connection)
                wait_for_lock(db, "d46-phase3-source-deletion", "advisory")
                phase3_connection.commit()
                future.result(timeout=10)
            _assert_service_json_rejected(
                db, "authorize_confident_moment_source_playback_emit_v1",
                arguments,
                "CONFIDENT_MOMENT_SOURCE_MEDIA_POLICY_INVALID",
            )
    finally:
        phase3_connection.rollback()
        deletion_connection.rollback()
        phase3_connection.close()
        deletion_connection.close()


def _d48_available_correlation_context(db):
    latest = one(
        db,
        "SELECT rollout_state FROM mlc3_service_rollout_revisions "
        "ORDER BY revision_number DESC LIMIT 1",
    )["rollout_state"]
    if latest == "generally_available":
        rows(
            db,
            "SELECT halt_mlc3_service_rollout_v1(%s,%s)",
            ("d48-fixture-reset", uuid4().hex * 2),
        )
    fixture_triggers = (
        ("ml_machine_predictions", "ml_machine_predictions_append_only"),
        ("processing_authorization_snapshots", "processing_authorization_snapshots_immutable"),
        ("processing_recording_attempts", "processing_recording_attempts_immutable"),
        ("processing_audio_objects", "processing_audio_objects_immutable"),
    )
    for table, trigger in fixture_triggers:
        rows(db, f"ALTER TABLE {table} DISABLE TRIGGER {trigger}")
    fixture_completed = False
    try:
        context, user_id, _rollout, feedback, response, prepared_offer = (
            _general_offer_context(db)
        )
        fixture_completed = True
    finally:
        if not fixture_completed:
            db.rollback()
        for table, trigger in fixture_triggers:
            rows(db, f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")
        db.commit()
    target = service_json_rpc(
        db, "record_mlc3_feedback_self_speaker_target_v1",
        context["owner"], user_id, feedback["membership"]["id"],
        feedback["candidate_id"], f"d48-source-target-{uuid4()}",
    )
    offer = service_rpc(
        db, "freeze_exercise_service_offer_v2", context["owner"],
        response["id"], prepared_offer["n1_candidate_set_id"],
        prepared_offer["authorization_check_id"], f"d48-offer-{uuid4()}",
    )
    attachment_id = str(uuid4())
    rows(
        db,
        "INSERT INTO confident_moment_bundle_attachments("
        "id,acquisition_principal_id,project_id,take_id,feedback_membership_id,"
        "bundle_subject_kind,bundle_subject_candidate_id,bundle_subject_evidence_span_id,"
        "attached_candidate_id,attached_evidence_span_id,anchor_candidate_id,"
        "anchor_evidence_span_id,paragraph_id,document_snapshot_id,"
        "canonical_feedback_presentation_id,canonical_position,attachment_policy_version,"
        "presentation_identity_sha256,attachment_input_sha256,idempotency_key) "
        "SELECT %s,%s,%s,%s,%s,'confidence_anchor',c.id,c.evidence_span_id,c.id,"
        "c.evidence_span_id,c.id,c.evidence_span_id,mi.source_ideal_part_id,%s,%s,1,"
        "'confident-moment-attachment-v1',%s,%s,%s FROM feedback_candidates c "
        "JOIN feedback_v3_membership_items mi ON mi.membership_id=%s "
        "AND mi.candidate_id=c.id WHERE c.id=%s",
        (attachment_id, context["owner"], context["project"], context["take"],
         feedback["membership"]["id"], feedback["document_id"],
         feedback["exposure_id"], uuid4().hex * 2, uuid4().hex * 2,
         f"d48-fixture-{uuid4()}", feedback["membership"]["id"],
         feedback["candidate_id"]),
    )
    diagnostic = rows(
        db,
        "SELECT l.recording_attempt_id,l.processing_audio_object_id,l.snippet_id,"
        "r.id AS revision_id,r.speaker_count_status,r.speaker_identity_status,"
        "b.id AS binding_id,b.clip_id,b.practice_attempt_id,b.binding_state "
        "FROM exercise_service_offers o JOIN exercise_audio_lineages l "
        "ON l.id=o.source_audio_lineage_id LEFT JOIN mlc3_speaker_acquisition_revisions r "
        "ON r.recording_attempt_id=l.recording_attempt_id AND r.audio_object_id=l.processing_audio_object_id "
        "LEFT JOIN mlc3_target_speaker_bindings b ON b.acquisition_revision_id=r.id "
        "WHERE o.id=%s",
        (offer["id"],),
    )
    assert (
        len(diagnostic) == 1
        and diagnostic[0]["binding_id"]
        and diagnostic[0]["speaker_identity_status"] == "resolved"
        and diagnostic[0]["clip_id"] == diagnostic[0]["snippet_id"]
        and diagnostic[0]["practice_attempt_id"] is None
        and diagnostic[0]["binding_state"] == "active"
    ), (target, offer, diagnostic)
    result = service_json_rpc(
        db, "resolve_confident_moment_exercise_offer_v1", context["owner"],
        feedback["candidate_id"], attachment_id,
    )
    assert set(result) == {
        "contract_version", "status", "bundle_id", "bundle_attachment_id",
        "offer_id", "feedback_response_binding_id", "n1_candidate_set_id",
        "authorization_check_id", "source_acquisition_receipt_id",
        "source_target_speaker_binding_id", "correlation_sha256",
        "dataset_eligible",
    }
    assert result["status"] == "available"
    assert result["offer_id"] == str(offer["id"])
    assert result["source_target_speaker_binding_id"] == target["target_binding_id"]
    assert result["dataset_eligible"] is False

    return {
        "context": context,
        "user_id": user_id,
        "feedback": feedback,
        "prepared_offer": prepared_offer,
        "offer": offer,
        "attachment_id": attachment_id,
        "correlation": result,
    }


def test_d48_binding_ownership_and_correlation_races_fail_closed(db, monkeypatch):
    flow = _d48_available_correlation_context(db)
    context = flow["context"]
    feedback = flow["feedback"]
    prepared_offer = flow["prepared_offer"]
    offer = flow["offer"]

    practice = service_rpc(
        db, "create_exercise_practice_service_session_v1", offer["id"],
        context["owner"], prepared_offer["source_acquisition_receipt_id"],
        f"d48-practice-{uuid4()}",
    )
    legacy_rpc = d2.rpc

    def rollout_rpc(connection, name, *arguments):
        if name == "reserve_exercise_practice_service_upload_v1":
            name = "reserve_exercise_practice_service_upload_v2"
        return legacy_rpc(connection, name, *arguments)

    monkeypatch.setattr(d2, "rpc", rollout_rpc)
    attempt, _selection, _media = d2._attach_valid_practice(db, context, practice)
    confirmed = service_json_rpc(
        db, "confirm_mlc3_practice_speaker_and_pair_v1", context["owner"],
        flow["user_id"], attempt["id"], f"d48-practice-speaker-{uuid4()}",
    )
    practice_binding_id = confirmed["speaker_target"]["target_binding_id"]
    source_binding_id = flow["correlation"]["source_target_speaker_binding_id"]
    source_speaker_id = one(
        db, "SELECT speaker_id FROM mlc3_target_speaker_bindings WHERE id=%s",
        (source_binding_id,),
    )["speaker_id"]

    foreign = make_context(db)
    foreign_assertion_id = str(uuid4())
    foreign_revision_id = str(uuid4())
    foreign_binding_id = str(uuid4())
    span = one(
        db, "SELECT start_offset_ms,duration_ms FROM snippets WHERE id=%s",
        (foreign["snippet"],),
    )
    start_ms = span["start_offset_ms"]
    duration = span["duration_ms"]
    rows(
        db,
        "INSERT INTO mlc3_self_speaker_assertions("
        "id,acquisition_principal_id,owner_user_id,recording_attempt_id,"
        "audio_object_id,authorization_receipt_id,authorization_policy_id,"
        "assertion_value,target_start_ms,target_duration_ms,policy_version,"
        "idempotency_key,assertion_sha256) SELECT %s,%s,user_id,%s,%s,%s,%s,"
        "'this_is_my_voice',%s,%s,'mlc3-self-speaker-assertion-v1',%s,%s "
        "FROM owner_principals WHERE id=%s",
        (foreign_assertion_id, foreign["owner"], foreign["take"],
         foreign["object"], foreign["receipt"], foreign["policy"],
         start_ms, duration, f"d48-foreign-assertion-{uuid4()}",
         uuid4().hex * 2, foreign["owner"]),
    )
    rows(
        db,
        "INSERT INTO mlc3_speaker_acquisition_revisions("
        "id,acquisition_principal_id,recording_attempt_id,audio_object_id,"
        "revision_number,speaker_count_status,speaker_identity_status,speaker_id,"
        "count_policy_version,identity_policy_version,evidence_source,audio_sha256,"
        "binding_sha256) SELECT %s,%s,%s,%s,1,'single','resolved',%s,"
        "'speaker-count-self-v1','speaker-identity-self-v1','self_speaker',"
        "exact_bytes_sha256,%s FROM processing_audio_objects WHERE id=%s",
        (foreign_revision_id, foreign["owner"], foreign["take"],
         foreign["object"], source_speaker_id, uuid4().hex * 2,
         foreign["object"]),
    )
    rows(
        db,
        "INSERT INTO mlc3_target_speaker_bindings("
        "id,acquisition_principal_id,recording_attempt_id,audio_object_id,"
        "acquisition_revision_id,speaker_id,self_speaker_assertion_id,"
        "revision_number,binding_state,clip_id,target_start_ms,target_duration_ms,"
        "transcript_span,transcript_sha256,audio_sha256,segmentation_policy_version,"
        "segmentation_run_version,target_binding_sha256) SELECT %s,%s,%s,%s,%s,%s,%s,"
        "1,'active',%s,%s,%s,%s::jsonb,%s,exact_bytes_sha256,"
        "'self-speaker-full-clip-v1','self-speaker-full-clip-v1',%s "
        "FROM processing_audio_objects WHERE id=%s",
        (foreign_binding_id, foreign["owner"], foreign["take"], foreign["object"],
         foreign_revision_id, source_speaker_id, foreign_assertion_id,
         foreign["snippet"], start_ms, duration,
         Json({"start_ms": start_ms, "end_ms": start_ms + duration}),
         uuid4().hex * 2, uuid4().hex * 2, foreign["object"]),
    )

    item = one(
        db, "SELECT source_ideal_part_id,evidence_span_id FROM feedback_v3_membership_items "
        "WHERE membership_id=%s AND candidate_id=%s",
        (feedback["membership"]["id"], feedback["candidate_id"]),
    )
    candidate = one(
        db, "SELECT generated_output->>'quote' phrase FROM feedback_candidates WHERE id=%s",
        (feedback["candidate_id"],),
    )
    phrase = candidate["phrase"]
    owner_user_id = one(
        db, "SELECT user_id FROM owner_principals WHERE id=%s",
        (context["owner"],),
    )["user_id"]
    rows(
        db, "ALTER TABLE ideal_text_part DISABLE TRIGGER "
        "ideal_text_part_advances_document_generation",
    )
    try:
        rows(
            db, "INSERT INTO ideal_text_part(id,arc_id,user_id,ord,text) "
            "VALUES(%s,%s,%s,0,%s)",
            (item["source_ideal_part_id"], context["project"], owner_user_id, phrase),
        )
    finally:
        rows(
            db, "ALTER TABLE ideal_text_part ENABLE TRIGGER "
            "ideal_text_part_advances_document_generation",
        )
    rows(
        db, "INSERT INTO ideal_text_part_revision(arc_id,user_id,part_id,action,text) "
        "VALUES(%s,%s,%s,'user_edit',%s)",
        (context["project"], owner_user_id, item["source_ideal_part_id"], phrase),
    )
    content = one(
        db, "SELECT (register_synthetic_root_content_version_v1("
        "%s,%s,%s,%s,%s,0,%s,'unchanged_manager',%s)).*",
        (feedback["membership"]["id"], feedback["candidate_id"],
         item["source_ideal_part_id"], prepared_offer["authorization_check_id"],
         phrase, len(phrase), f"d48-root-content-{uuid4()}"),
    )
    before = one(
        db, "SELECT (SELECT count(*) FROM root_phrase_product_actions) actions,"
        "(SELECT count(*) FROM exercise_pair_judgments) judgments,"
        "(SELECT count(*) FROM ml_judgments) ml_judgments",
    )
    key = f"d48-foreign-root-action-{uuid4()}"
    rows(db, "SAVEPOINT d48_foreign_binding")
    with pytest.raises(psycopg2.Error, match="CONFIDENT_MOMENT_PROJECTION_INVALID"):
        one(
            db, "SELECT record_root_phrase_product_action_v2("
            "%s,%s,%s,%s,%s,'save_owner_selected_root',NULL,%s,%s,NULL,NULL,"
            "%s,%s,NULL,%s,%s,NULL,'rooting-coverage-30-80-100-v1',%s)",
            (context["owner"], context["project"], context["take"],
             item["source_ideal_part_id"], content["block_key"],
             feedback["candidate_id"], item["evidence_span_id"], attempt["id"],
             content["source_part_revision_id"], foreign_binding_id,
             practice_binding_id, key),
        )
    rows(db, "ROLLBACK TO SAVEPOINT d48_foreign_binding")
    assert one(
        db, "SELECT (SELECT count(*) FROM root_phrase_product_actions) actions,"
        "(SELECT count(*) FROM exercise_pair_judgments) judgments,"
        "(SELECT count(*) FROM ml_judgments) ml_judgments",
    ) == before
    valid_arguments = (
        context["owner"], context["project"], context["take"],
        item["source_ideal_part_id"], content["block_key"],
        feedback["candidate_id"], item["evidence_span_id"], attempt["id"],
        content["source_part_revision_id"], source_binding_id,
        practice_binding_id, f"d48-valid-root-action-{uuid4()}",
    )
    valid_action = one(
        db, "SELECT record_root_phrase_product_action_v2("
        "%s,%s,%s,%s,%s,'save_owner_selected_root',NULL,%s,%s,NULL,NULL,"
        "%s,%s,NULL,%s,%s,NULL,'rooting-coverage-30-80-100-v1',%s) result",
        valid_arguments,
    )["result"]
    assert valid_action["source_target_speaker_binding_id"] == source_binding_id
    assert valid_action["practice_target_speaker_binding_id"] == practice_binding_id
    assert valid_action["practice_guard_sha256"]
    assert one(
        db, "SELECT record_root_phrase_product_action_v2("
        "%s,%s,%s,%s,%s,'save_owner_selected_root',NULL,%s,%s,NULL,NULL,"
        "%s,%s,NULL,%s,%s,NULL,'rooting-coverage-30-80-100-v1',%s) result",
        valid_arguments,
    )["result"] == valid_action
    after_valid = one(
        db, "SELECT (SELECT count(*) FROM root_phrase_product_actions) actions,"
        "(SELECT count(*) FROM exercise_pair_judgments) judgments,"
        "(SELECT count(*) FROM ml_judgments) ml_judgments",
    )
    assert after_valid == {
        "actions": before["actions"] + 1,
        "judgments": before["judgments"],
        "ml_judgments": before["ml_judgments"],
    }
    db.commit()
    holder = psycopg2.connect(db.dsn)
    waiter = psycopg2.connect(db.dsn)
    holder.autocommit = False
    waiter.autocommit = True
    try:
        _d48_append_unresolved_source_revision(
            holder, flow["correlation"]["source_target_speaker_binding_id"],
            uuid4().hex * 2,
        )
        with pytest.raises(
            psycopg2.Error,
            match="CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED",
        ):
            service_json_rpc(
                waiter, "resolve_confident_moment_exercise_offer_v1",
                flow["context"]["owner"], flow["feedback"]["candidate_id"],
                flow["attachment_id"],
            )
        holder.rollback()
    finally:
        holder.rollback()
        waiter.close()
        holder.close()

    reader = psycopg2.connect(db.dsn)
    writer = psycopg2.connect(db.dsn)
    reader.autocommit = False
    writer.autocommit = False
    application = "d48_binding_writer_" + uuid4().hex
    try:
        result = service_json_rpc(
            reader, "resolve_confident_moment_exercise_offer_v1",
            flow["context"]["owner"], flow["feedback"]["candidate_id"],
            flow["attachment_id"],
        )
        assert result["source_target_speaker_binding_id"] == (
            flow["correlation"]["source_target_speaker_binding_id"]
        )
        rows(writer, "SET application_name=%s", (application,))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                _d48_append_unresolved_source_revision, writer,
                flow["correlation"]["source_target_speaker_binding_id"],
                uuid4().hex * 2,
            )
            wait_for_lock(db, application, "advisory")
            reader.commit()
            future.result(timeout=5)
            writer.commit()
        _assert_service_json_rejected(
            db, "resolve_confident_moment_exercise_offer_v1",
            (flow["context"]["owner"], flow["feedback"]["candidate_id"],
             flow["attachment_id"]),
            "CONFIDENT_MOMENT_TARGET_SPEAKER_INVALID",
        )
    finally:
        reader.rollback()
        writer.rollback()
        writer.close()
        reader.close()


def _d48_append_unresolved_source_revision(connection, source_binding_id, digest):
    rows(
        connection,
        "SELECT pg_advisory_xact_lock(hashtextextended("
        "'mlc3-speaker-attempt:'||recording_attempt_id::text,0)) "
        "FROM mlc3_target_speaker_bindings WHERE id=%s",
        (source_binding_id,),
    )
    rows(
        connection,
        "INSERT INTO mlc3_speaker_acquisition_revisions("
        "acquisition_principal_id,recording_attempt_id,audio_object_id,"
        "revision_number,supersedes_revision_id,speaker_count_status,"
        "speaker_identity_status,speaker_id,count_policy_version,"
        "identity_policy_version,evidence_source,audio_sha256,binding_sha256) "
        "SELECT r.acquisition_principal_id,r.recording_attempt_id,r.audio_object_id,"
        "r.revision_number+1,r.id,'single','unresolved',NULL,r.count_policy_version,"
        "r.identity_policy_version,'unresolved',r.audio_sha256,%s "
        "FROM mlc3_target_speaker_bindings b JOIN mlc3_speaker_acquisition_revisions r "
        "ON r.id=b.acquisition_revision_id WHERE b.id=%s",
        (digest, source_binding_id),
    )
def test_d28_materializer_completed_and_terminal_replay_are_exact(db):
    context, _feedback, _prepared, _published, job, _authority = (
        _pending_delivery_job_context(db)
    )
    _insert_next_take(db, context)
    _claim_one_delivery_job(db, str(job["id"]))
    key = f"materialize:{job['id']}"
    result = service_json_rpc(
        db, "materialize_feedback_language_delivery_job_v1", str(job["id"]), key,
    )
    assert result["job_state"] == "completed"
    assert result["cause_code"] == "delivery_materialized"
    assert result["delivery_id"] is not None
    assert service_json_rpc(
        db, "materialize_feedback_language_delivery_job_v1", str(job["id"]), key,
    ) == result
    rows(db, "SAVEPOINT changed_materializer_key")
    with db.cursor() as cursor:
        cursor.execute("SET ROLE service_role")
        with pytest.raises(
            Exception,
            match="CONFIDENT_MOMENT_DELIVERY_MATERIALIZE_REPLAY_MISMATCH",
        ):
            cursor.execute(
                "SELECT materialize_feedback_language_delivery_job_v1(%s,%s)",
                (str(job["id"]), f"materialize:{uuid4()}"),
            )
        cursor.execute("ROLLBACK TO SAVEPOINT changed_materializer_key")
        cursor.execute("RESET ROLE")
    assert one(db, "SELECT job_state,attempt_count FROM feedback_language_delivery_materialization_jobs WHERE id=%s", (job["id"],)) == {
        "job_state": "completed", "attempt_count": 1,
    }
    event = one(
        db,
        "SELECT e.*,exercise_json_sha256_v1(jsonb_build_object("
        "'id',e.id,'job_id',e.job_id,'event_kind',e.event_kind,"
        "'delivery_id',e.delivery_id,'attempt_number',e.attempt_number,"
        "'claim_attempt_id',e.claim_attempt_id,'contract_version',e.contract_version,"
        "'cause_code',e.cause_code,'idempotency_key',e.idempotency_key,"
        "'created_at',e.created_at,'serves_user',e.serves_user,"
        "'dataset_eligible',e.dataset_eligible)) expected_sha256 "
        "FROM feedback_language_delivery_materialization_job_events e "
        "WHERE e.job_id=%s AND e.event_kind='completed'",
        (job["id"],),
    )
    assert event["event_sha256"] == event["expected_sha256"]


def test_d28_materializer_expired_claim_is_one_retryable_event_without_delivery(db):
    context, _feedback, _prepared, _published, job, _authority = (
        _pending_delivery_job_context(db)
    )
    _insert_next_take(db, context)
    _claim_one_delivery_job(db, str(job["id"]))
    rows(db, "UPDATE feedback_language_delivery_job_claim_heads SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE job_id=%s", (job["id"],))
    before = one(db, "SELECT count(*) n FROM feedback_language_revision_deliveries")["n"]
    result = service_json_rpc(
        db, "materialize_feedback_language_delivery_job_v1", str(job["id"]),
        f"materialize:{job['id']}",
    )
    assert result["job_state"] == "failed_retryable"
    assert result["cause_code"] == "enqueue_lease_expired"
    assert result["delivery_id"] is None
    assert one(db, "SELECT count(*) n FROM feedback_language_revision_deliveries")["n"] == before
    assert one(db, "SELECT scheduling_state FROM feedback_language_delivery_job_due_heads WHERE job_id=%s", (job["id"],))["scheduling_state"] == "pending"


def test_d34_scan_run_begin_mark_abandon_exact_replay(db):
    with db.cursor() as cur:
        cur.execute(SQL)
    worker = "a" * 64
    run = uuid4()
    begin_key = f"delivery-scan-begin-v1:{run}:{worker}"
    begun = one(db, "SELECT begin_feedback_language_delivery_scan_run_v1(%s,%s,%s) result", (str(run), worker, begin_key))["result"]
    replay = one(db, "SELECT begin_feedback_language_delivery_scan_run_v1(%s,%s,%s) result", (str(run), worker, begin_key))["result"]
    assert replay == begun
    abandoned = one(db, "SELECT abandon_feedback_language_delivery_scan_run_v1(%s,%s,%s) result", (str(run), worker, f"delivery-scan-abandon-v1:{run}:{worker}"))["result"]
    assert abandoned["result_code"] == "abandoned_before_scan"
    other = uuid4()
    one(db, "SELECT begin_feedback_language_delivery_scan_run_v1(%s,%s,%s) result", (str(other), worker, f"delivery-scan-begin-v1:{other}:{worker}"))
    started = one(db, "SELECT mark_feedback_language_delivery_scan_started_v1(%s,%s,%s) result", (str(other), worker, f"delivery-scan-start-v1:{other}:{worker}"))["result"]
    assert started["scanner_started_at"] is not None
    with pytest.raises(psycopg2.Error, match="CONFIDENT_MOMENT_DELIVERY_SCAN_INVALID"):
        one(db, "SELECT abandon_feedback_language_delivery_scan_run_v1(%s,%s,%s)", (str(other), worker, f"delivery-scan-abandon-v1:{other}:{worker}"))


def test_d36_scanner_rejects_non_literal_limit_before_work(db):
    with db.cursor() as cur:
        cur.execute(SQL)
    worker = "b" * 64
    for limit in (0, 1, 2, 4, 25):
        run = uuid4()
        one(db, "SELECT begin_feedback_language_delivery_scan_run_v1(%s,%s,%s)", (str(run), worker, f"delivery-scan-begin-v1:{run}:{worker}"))
        one(db, "SELECT mark_feedback_language_delivery_scan_started_v1(%s,%s,%s)", (str(run), worker, f"delivery-scan-start-v1:{run}:{worker}"))
        with pytest.raises(psycopg2.Error, match="CONFIDENT_MOMENT_DELIVERY_SCAN_INVALID"):
            one(db, "SELECT scan_due_feedback_language_delivery_jobs_v1(%s,%s,%s,60,1000)", (str(run), worker, limit))


def test_d49_owner_binding_and_speaker_resolver_security_closure(db):
    with db.cursor() as cur:
        cur.execute(SQL)
        cur.execute(
            "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
            "WHERE oid='public.confident_moment_owner_decision_bindings'::regclass"
        )
        assert cur.fetchone() == (True, True)
        cur.execute(
            "SELECT p.proname FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid "
            "WHERE t.tgrelid='public.confident_moment_owner_decision_bindings'::regclass "
            "AND t.tgname='confident_moment_owner_decision_bindings_append_only' "
            "AND NOT t.tgisinternal AND t.tgenabled IN ('O','A')"
        )
        assert cur.fetchone() == ("reject_confident_moment_mutation_v1",)
        cur.execute(
            "SELECT to_regprocedure(%s) IS NOT NULL",
            (
                "public.resolve_confident_moment_target_speaker_binding_v1"
                "(uuid,uuid,uuid,text,uuid,uuid)",
            ),
        )
        assert cur.fetchone()[0]
        for role in ("anon", "authenticated", "service_role"):
            cur.execute(
                "SELECT has_table_privilege(%s,%s,%s)",
                (role, "public.confident_moment_owner_decision_bindings", "INSERT"),
            )
            assert cur.fetchone()[0] is False
            cur.execute(
                "SELECT has_function_privilege(%s,%s,%s)",
                (
                    role,
                    "public.resolve_confident_moment_target_speaker_binding_v1"
                    "(uuid,uuid,uuid,text,uuid,uuid)",
                    "EXECUTE",
                ),
            )
            assert cur.fetchone()[0] is False


def test_d49_bundle_response_persists_one_exact_binding_and_replays(db):
    _install_released_render_ack(db)
    with db.cursor() as cur:
        cur.execute(SQL)
    context, feedback = _positive_projection_context(db)
    prepared = one(
        db,
        "SELECT prepare_confident_moment_bundle_v1(%s,%s,%s,%s,%s,%s) payload",
        (
            context["owner"], context["project"], context["take"],
            feedback["membership"]["id"], feedback["candidate_id"],
            f"d49-prepare-{uuid4()}",
        ),
    )["payload"]
    attachment = prepared["attachments"][0]
    rendered = service_json_rpc(
        db, "ack_confident_moment_bundle_item_render_v3", context["owner"],
        prepared["bundle_id"], attachment["id"],
        attachment["canonical_feedback_presentation_id"], str(uuid4()),
        f"d49-render-{uuid4()}",
    )
    args = (
        context["owner"], prepared["bundle_id"], attachment["id"],
        attachment["canonical_feedback_presentation_id"],
        rendered["render_receipt_id"], "yes", f"d49-response-{uuid4()}",
    )
    first = service_json_rpc(db, "record_confident_moment_bundle_family_response_v1", *args)
    replay = service_json_rpc(db, "record_confident_moment_bundle_family_response_v1", *args)
    assert replay == first
    bound = one(
        db,
        "SELECT feedback_family,interaction_response,canonical_response,"
        "decision_id,owner_response_id,response_binding_id,dataset_eligible "
        "FROM confident_moment_owner_decision_bindings WHERE bundle_attachment_id=%s",
        (attachment["id"],),
    )
    assert bound["feedback_family"] == "confident_voice"
    assert bound["interaction_response"] == "yes"
    assert bound["canonical_response"] == "confident_yes"
    assert bound["decision_id"] == bound["owner_response_id"]
    assert bound["response_binding_id"] == first["response_binding_id"]
    assert bound["dataset_eligible"] is False
    projected = service_json_rpc(
        db, "project_confident_moment_bundles_v1", context["owner"],
        context["project"], context["take"],
    )
    item = projected["bundle_projection"]["bundles"][0]["feedback_language_items"][0]
    assert item["owner_decision"]["response"] == "yes"
    assert item["owner_decision"]["feedback_family"] == item["feedback_family"]


def test_d49_two_clips_on_one_attempt_resolve_by_exact_target_identity(db):
    flow = _d48_available_correlation_context(db)
    original_id = flow["correlation"]["source_target_speaker_binding_id"]
    second_id, second_clip = str(uuid4()), str(uuid4())
    rows(
        db,
        "INSERT INTO mlc3_target_speaker_bindings("
        "id,acquisition_principal_id,recording_attempt_id,audio_object_id,"
        "acquisition_revision_id,speaker_id,self_speaker_assertion_id,"
        "reviewed_segmentation_id,revision_number,supersedes_binding_id,"
        "binding_state,clip_id,practice_attempt_id,target_start_ms,"
        "target_duration_ms,transcript_span,transcript_sha256,audio_sha256,"
        "segmentation_policy_version,segmentation_run_version,target_binding_sha256) "
        "SELECT %s,acquisition_principal_id,recording_attempt_id,audio_object_id,"
        "acquisition_revision_id,speaker_id,self_speaker_assertion_id,"
        "reviewed_segmentation_id,(SELECT max(revision_number)+1 FROM "
        "mlc3_target_speaker_bindings WHERE recording_attempt_id=b.recording_attempt_id),"
        "NULL,'active',%s,NULL,target_start_ms,target_duration_ms,transcript_span,"
        "transcript_sha256,audio_sha256,segmentation_policy_version,"
        "segmentation_run_version,%s FROM mlc3_target_speaker_bindings b WHERE id=%s",
        (second_id, second_clip, uuid4().hex * 2, original_id),
    )
    lineage = one(
        db,
        "SELECT l.recording_attempt_id,l.processing_audio_object_id,l.snippet_id "
        "FROM exercise_audio_lineages l JOIN exercise_service_offers o "
        "ON o.source_audio_lineage_id=l.id WHERE o.id=%s",
        (flow["offer"]["id"],),
    )
    original = one(
        db,
        "SELECT resolve_confident_moment_target_speaker_binding_v1("
        "%s,%s,%s,'source_clip',%s,NULL) result",
        (
            flow["context"]["owner"], lineage["recording_attempt_id"],
            lineage["processing_audio_object_id"], lineage["snippet_id"],
        ),
    )["result"]
    second = one(
        db,
        "SELECT resolve_confident_moment_target_speaker_binding_v1("
        "%s,%s,%s,'source_clip',%s,NULL) result",
        (
            flow["context"]["owner"], lineage["recording_attempt_id"],
            lineage["processing_audio_object_id"], second_clip,
        ),
    )["result"]
    assert original["target_speaker_binding_id"] == original_id
    assert second["target_speaker_binding_id"] == second_id
    assert original["speaker_id"] == second["speaker_id"]
    assert original["result_sha256"] != second["result_sha256"]
