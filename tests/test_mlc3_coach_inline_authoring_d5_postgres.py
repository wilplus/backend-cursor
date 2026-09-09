"""Executable PostgreSQL rejection tests for pending, disabled D5 authoring."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep
from uuid import uuid4

import psycopg2
import pytest

from tests import test_coach_guidance_delivery_d3_postgres as d3
from tests.test_mlc3_dark_assignments_postgres import assign, one, query, rpc
from tests.test_mlc3_n1_source_pattern_postgres import source_pattern

pytestmark = pytest.mark.skipif(
    not __import__("os").environ.get("COACH_GUIDANCE_REHEARSAL_DSN"),
    reason="disposable D5 rehearsal only",
)


@pytest.fixture
def db():
    connection = d3.connect()
    d3._install_full_review_shape(connection)
    yield connection
    connection.close()


@pytest.fixture
def ctx(db):
    return d3.ctx.__wrapped__(db)


def _batch(db, context):
    return rpc(
        db,
        "freeze_synthetic_coach_guidance_batch_v1",
        context["owner"],
        context["project"],
        context["reviewer"],
        str(uuid4()),
    )


def test_source_role_composite_identity_rejects_foreign_principal(db, ctx):
    packet = d3._make_packet(db, ctx)
    batch = _batch(db, ctx)
    valid = (
        batch["id"], ctx["owner"], ctx["reviewer"],
        packet["review_assignment_id"], packet["id"], ctx["lineage"],
        "source_before_exercise", "a" * 64,
    )
    query(
        db,
        "INSERT INTO coach_inline_source_roles VALUES "
        "(%s,%s,%s,%s,%s,%s,%s,%s,clock_timestamp(),false,false)",
        valid,
    )
    foreign = {name: str(uuid4()) for name in ("owner", "user")}
    query(
        db, "INSERT INTO owner_principals(id,user_id) VALUES (%s,%s)",
        (foreign["owner"], foreign["user"]),
    )
    with pytest.raises(psycopg2.Error):
        query(
            db,
            "INSERT INTO coach_inline_source_roles VALUES "
            "(%s,%s,%s,%s,%s,%s,%s,%s,clock_timestamp(),false,false)",
            (
                batch["id"], foreign["owner"], ctx["reviewer"],
                packet["review_assignment_id"], packet["id"],
                ctx["lineage"], "source_before_exercise", "b" * 64,
            ),
        )


def test_blind_audio_resolver_is_assignment_bound_and_fails_after_revocation(db, ctx):
    counts_before = one(
        db,
        "SELECT (SELECT count(*) FROM exercise_practice_sessions) AS practice,"
        "(SELECT count(*) FROM exercise_practice_attempts) AS attempts,"
        "(SELECT count(*) FROM coach_inline_exercise_drafts) AS drafts",
    )
    packet = d3._make_packet(db, ctx)
    assignment_id = packet["review_assignment_id"]
    reviewer_user = one(
        db, "SELECT user_id FROM owner_principals WHERE id=%s", (ctx["reviewer"],)
    )["user_id"]
    resolved = one(
        db,
        "SELECT public.resolve_coach_inline_blind_audio_read_v1(%s,%s,%s) "
        "AS payload",
        (assignment_id, reviewer_user, ctx["reviewer"]),
    )["payload"]
    assert resolved["assignment_id"] == assignment_id
    assert resolved["object_key"]
    assert resolved["blind_packet_id"] == packet["id"]
    assert resolved["start_offset_ms"] == 1250
    assert resolved["duration_ms"] == 2400
    counts = one(
        db,
        "SELECT (SELECT count(*) FROM exercise_practice_sessions) AS practice,"
        "(SELECT count(*) FROM exercise_practice_attempts) AS attempts,"
        "(SELECT count(*) FROM coach_inline_exercise_drafts) AS drafts",
    )
    assert counts == counts_before
    query(
        db,
        "INSERT INTO processing_service_blocks(acquisition_principal_id,effective_at) "
        "VALUES (%s,clock_timestamp())",
        (ctx["owner"],),
    )
    with pytest.raises(
        psycopg2.Error, match="COACH_GUIDANCE_CURRENT_AUTHORITY_REQUIRED"
    ):
        rpc(
            db, "resolve_coach_inline_blind_audio_read_v1",
            assignment_id, reviewer_user, ctx["reviewer"],
        )


def test_rpc_privileges_and_structural_dark_flags(db):
    helper = one(
        db,
        "SELECT has_function_privilege('service_role',"
        "'public.reject_coach_inline_mutation_v1()','EXECUTE') AS service,"
        "has_function_privilege('authenticated',"
        "'public.reject_coach_inline_mutation_v1()','EXECUTE') AS client,"
        "has_function_privilege('anon',"
        "'public.reject_coach_inline_mutation_v1()','EXECUTE') AS anon",
    )
    assert helper == {"service": False, "client": False, "anon": False}
    resolver = one(
        db,
        "SELECT has_function_privilege('service_role',"
        "'public.resolve_coach_inline_blind_audio_read_v1(uuid,uuid,uuid)',"
        "'EXECUTE') AS service,has_function_privilege('authenticated',"
        "'public.resolve_coach_inline_blind_audio_read_v1(uuid,uuid,uuid)',"
        "'EXECUTE') AS client",
    )
    assert resolver == {"service": True, "client": False}
    for table in (
        "coach_inline_source_roles",
        "coach_inline_exercise_drafts",
        "coach_inline_context_assessments",
        "coach_inline_exercise_eligibility_reviews",
    ):
        definitions = query(
            db,
            "SELECT pg_get_constraintdef(oid) AS definition FROM pg_constraint "
            "WHERE conrelid=%s::regclass AND contype='c'",
            (f"public.{table}",),
        )
        joined = " ".join(row["definition"] for row in definitions)
        assert "NOT serves_user" in joined
        assert "NOT dataset_eligible" in joined


def _present_packet(db, ctx, packet):
    canonical_event_id = str(uuid4())
    query(
        db,
        "INSERT INTO ml_canonical_events(id,learning_surface_id,"
        "feedback_family_id,payload_type) VALUES "
        "(%s,'confidence_classification','confident_voice','confidence_event')",
        (canonical_event_id,),
    )
    presentation_id = str(uuid4())
    token = str(uuid4())
    payload_hash = uuid4().hex + uuid4().hex
    query(
        db,
        "INSERT INTO ml_presentations(id,canonical_event_id,learning_surface_id,"
        "review_assignment_id,actor_principal_id,actor_role,delivery_mode,"
        "evaluation_only,visible_payload_sha256,acknowledgement_token,"
        "idempotency_key) VALUES (%s,%s,'confidence_classification',%s,%s,"
        "'coach','canary',false,%s,%s,%s)",
        (
            presentation_id, canonical_event_id,
            packet["review_assignment_id"], ctx["reviewer"], payload_hash,
            token, str(uuid4()),
        ),
    )
    return {
        "review_assignment_id": packet["review_assignment_id"],
        "blind_packet_id": packet["id"],
        "presentation_id": presentation_id,
        "acknowledgement_token": token,
        "visible_payload_sha256": payload_hash,
    }


def _render_visible(db, ctx, visible, *, render_key=None, render_id=None):
    exposure = rpc(
        db, "ack_coach_inline_blind_render_v1",
        visible["review_assignment_id"], visible["blind_packet_id"],
        visible["presentation_id"], visible["acknowledgement_token"],
        ctx["owner"], ctx["reviewer"], render_id or str(uuid4()),
        one(db, "SELECT clock_timestamp() AS t")["t"],
        "d5-postgres-test", visible["visible_payload_sha256"],
        render_key or str(uuid4()),
    )
    return exposure


def _render_visible_and_judge(db, ctx, visible, decision="rating_not_sure"):
    exposure = _render_visible(db, ctx, visible)
    return one(
        db,
        "SELECT public.submit_coach_inline_blind_judgment_v1("
        "%s,%s,%s,%s,%s,%s,%s,%s) AS payload",
        (
            visible["review_assignment_id"], visible["blind_packet_id"],
            ctx["owner"],
            ctx["reviewer"], exposure["id"], decision,
            one(db, "SELECT clock_timestamp() AS t")["t"], str(uuid4()),
        ),
    )["payload"]


def _submit_visible_judgment(
    connection, context, visible, exposure_id, decision, decided_at, key,
):
    return one(
        connection,
        "SELECT public.submit_coach_inline_blind_judgment_v1("
        "%s,%s,%s,%s,%s,%s,%s,%s) AS payload",
        (
            visible["review_assignment_id"], visible["blind_packet_id"],
            context["owner"], context["reviewer"], exposure_id,
            decision, decided_at, key,
        ),
    )["payload"]


def _wait_for_advisory(db, application_name):
    deadline = monotonic() + 5
    while not query(
        db,
        "SELECT 1 FROM pg_stat_activity "
        "WHERE application_name=%s AND wait_event='advisory'",
        (application_name,),
    ):
        if monotonic() >= deadline:
            raise AssertionError(f"{application_name} never reached advisory wait")
        sleep(0.01)


def _render_and_judge(db, ctx, packet, decision="rating_not_sure"):
    return _render_visible_and_judge(
        db, ctx, _present_packet(db, ctx, packet), decision
    )


def test_one_visible_judgment_completes_batch_without_practice_records(db, ctx):
    packet = d3._make_packet(db, ctx)
    before = one(
        db,
        "SELECT (SELECT count(*) FROM exercise_practice_sessions) AS sessions,"
        "(SELECT count(*) FROM exercise_practice_attempts) AS attempts",
    )
    batch = _batch(db, ctx)
    judgment = _render_and_judge(db, ctx, packet, "rating_yes")
    grant = rpc(
        db, "complete_synthetic_coach_guidance_batch_v1",
        batch["id"], ctx["reviewer"], str(uuid4()),
    )
    assert grant["id"]
    assert one(
        db,
        "SELECT count(*) AS n FROM ml_judgments WHERE review_assignment_id=%s",
        (packet["review_assignment_id"],),
    )["n"] == 1
    assert judgment["review_assignment_id"] == packet["review_assignment_id"]
    after = one(
        db,
        "SELECT (SELECT count(*) FROM exercise_practice_sessions) AS sessions,"
        "(SELECT count(*) FROM exercise_practice_attempts) AS attempts",
    )
    assert after == before


def test_visible_render_is_independent_idempotent_and_required_by_judgment(db, ctx):
    first = _present_packet(db, ctx, d3._make_packet(db, ctx))
    second = _present_packet(db, ctx, d3._make_packet(db, ctx, second=True))
    render_key = str(uuid4())
    render_id = str(uuid4())
    first_exposure = _render_visible(
        db, ctx, first, render_key=render_key, render_id=render_id,
    )
    replay = _render_visible(
        db, ctx, first, render_key=render_key, render_id=render_id,
    )
    assert replay["id"] == first_exposure["id"]
    assert one(
        db,
        "SELECT count(*) AS exposures FROM ml_rendered_exposures "
        "WHERE presentation_id=%s",
        (first["presentation_id"],),
    )["exposures"] == 1
    assert one(
        db,
        "SELECT count(*) AS judgments FROM ml_judgments "
        "WHERE review_assignment_id=%s",
        (first["review_assignment_id"],),
    )["judgments"] == 0

    foreign_exposure = _render_visible(db, ctx, second)
    with pytest.raises(psycopg2.Error):
        one(
            db,
            "SELECT public.submit_coach_inline_blind_judgment_v1("
            "%s,%s,%s,%s,%s,%s,%s,%s) AS payload",
            (
                first["review_assignment_id"], first["blind_packet_id"],
                ctx["owner"], ctx["reviewer"], foreign_exposure["id"],
                "rating_yes", one(db, "SELECT clock_timestamp() AS t")["t"],
                str(uuid4()),
            ),
        )
    assert one(
        db,
        "SELECT count(*) AS judgments FROM ml_judgments "
        "WHERE review_assignment_id=%s",
        (first["review_assignment_id"],),
    )["judgments"] == 0

    judgment = one(
        db,
        "SELECT public.submit_coach_inline_blind_judgment_v1("
        "%s,%s,%s,%s,%s,%s,%s,%s) AS payload",
        (
            first["review_assignment_id"], first["blind_packet_id"],
            ctx["owner"], ctx["reviewer"], first_exposure["id"],
            "rating_yes", one(db, "SELECT clock_timestamp() AS t")["t"],
            str(uuid4()),
        ),
    )["payload"]
    assert judgment["review_assignment_id"] == first["review_assignment_id"]
    assert one(
        db,
        "SELECT count(*) AS exposures FROM ml_rendered_exposures "
        "WHERE presentation_id=%s",
        (first["presentation_id"],),
    )["exposures"] == 1


def test_concurrent_exact_judgment_retry_has_one_winner_and_one_replay(db, ctx):
    visible = _present_packet(db, ctx, d3._make_packet(db, ctx))
    exposure = _render_visible(db, ctx, visible)
    decided_at = one(db, "SELECT clock_timestamp() AS t")["t"]
    shared_key = str(uuid4())
    blocker_key = 1_934_771_201
    query(
        db,
        "CREATE OR REPLACE FUNCTION public.d5_test_block_judgment_insert_v1() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        f"PERFORM pg_advisory_xact_lock({blocker_key}); RETURN NEW; END $$",
    )
    query(
        db,
        "CREATE TRIGGER d5_test_block_judgment_insert "
        "BEFORE INSERT ON ml_judgments FOR EACH ROW "
        "EXECUTE FUNCTION public.d5_test_block_judgment_insert_v1()",
    )
    holder = d3.connect()
    holder.autocommit = False
    query(holder, "SELECT pg_advisory_xact_lock(%s)", (blocker_key,))

    def submit(application_name):
        connection = d3.connect()
        try:
            query(connection, "SET application_name=%s", (application_name,))
            return _submit_visible_judgment(
                connection, ctx, visible, exposure["id"], "rating_yes",
                decided_at, shared_key,
            )
        finally:
            connection.close()

    first_application = "d5_judgment_first_" + uuid4().hex
    second_application = "d5_judgment_second_" + uuid4().hex
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(submit, first_application)
            _wait_for_advisory(db, first_application)
            second = workers.submit(submit, second_application)
            _wait_for_advisory(db, second_application)
            holder.commit()
            first_result = first.result(timeout=5)
            second_result = second.result(timeout=5)
    finally:
        holder.rollback()
        holder.close()
        query(
            db,
            "DROP TRIGGER IF EXISTS d5_test_block_judgment_insert "
            "ON ml_judgments",
        )
        query(
            db,
            "DROP FUNCTION IF EXISTS public.d5_test_block_judgment_insert_v1()",
        )

    assert first_result["judgment_id"] == second_result["judgment_id"]
    assert {first_result["replayed"], second_result["replayed"]} == {False, True}
    assert one(
        db,
        "SELECT count(*) AS n FROM ml_judgments "
        "WHERE review_assignment_id=%s",
        (visible["review_assignment_id"],),
    )["n"] == 1
    assert one(
        db,
        "SELECT count(*) AS n FROM ml_review_assignment_events "
        "WHERE review_assignment_id=%s AND event_kind='submitted'",
        (visible["review_assignment_id"],),
    )["n"] == 1


def test_exact_lost_ack_replays_after_reveal_but_new_answers_fail(db, ctx):
    packet = d3._make_packet(db, ctx)
    visible = _present_packet(db, ctx, packet)
    batch = _batch(db, ctx)
    exposure = _render_visible(db, ctx, visible)
    decided_at = one(db, "SELECT clock_timestamp() AS t")["t"]
    key = str(uuid4())
    first = _submit_visible_judgment(
        db, ctx, visible, exposure["id"], "rating_yes", decided_at, key,
    )
    rpc(
        db, "complete_synthetic_coach_guidance_batch_v1",
        batch["id"], ctx["reviewer"], str(uuid4()),
    )

    replay = _submit_visible_judgment(
        db, ctx, visible, exposure["id"], "rating_yes", decided_at, key,
    )
    assert replay["judgment_id"] == first["judgment_id"]
    assert replay["replayed"] is True
    with pytest.raises(psycopg2.Error, match="blind judgment idempotency conflict"):
        _submit_visible_judgment(
            db, ctx, visible, exposure["id"], "rating_no", decided_at, key,
        )
    with pytest.raises(psycopg2.Error, match="blind judgment idempotency conflict"):
        _submit_visible_judgment(
            db, ctx, visible, exposure["id"], "rating_yes", decided_at,
            str(uuid4()),
        )


def test_ordinary_complete_batch_items_remain_available_for_guidance(db, ctx):
    first = d3._make_packet(db, ctx)
    second = d3._make_packet(db, ctx, second=True)
    _render_and_judge(db, ctx, first)
    _render_and_judge(db, ctx, second)
    result = one(
        db,
        "SELECT public.prepare_coach_inline_guidance_context_v1("
        "%s,%s,%s,%s) AS payload",
        (ctx["project"], ctx["owner"], ctx["reviewer"], str(uuid4())),
    )["payload"]
    assert len(result["items"]) == 2
    assert [item["exercise_eligible"] for item in result["items"]] == [False, False]
    assert all(item["source_role"] == "source_before_exercise"
               for item in result["items"])

    product_counts_before = one(
        db,
        "SELECT (SELECT count(*) FROM exercise_practice_sessions) AS practice,"
        "(SELECT count(*) FROM exercise_practice_measurement_revisions) "
        "AS measurements,"
        "(SELECT count(*) FROM coach_inline_exercise_drafts) AS drafts",
    )
    item = result["items"][0]
    authority = rpc(
        db, "issue_coach_inline_general_authority_v1",
        result["review_batch_id"], result["reveal_grant_id"],
        item["reveal_access_id"], item["review_assignment_id"],
        ctx["reviewer"], str(uuid4()),
    )
    key = str(uuid4())
    version = rpc(
        db, "create_coach_inline_general_guidance_v1",
        result["review_batch_id"], result["reveal_grant_id"],
        item["reveal_access_id"], item["review_assignment_id"],
        ctx["reviewer"], authority["id"], "delivery",
        "Slow down at the close.", None,
        "lang-v1", "safety-v1", "rights-v1", "content-v1", key,
    )
    replay = rpc(
        db, "create_coach_inline_general_guidance_v1",
        result["review_batch_id"], result["reveal_grant_id"],
        item["reveal_access_id"], item["review_assignment_id"],
        ctx["reviewer"], authority["id"], "delivery",
        "Slow down at the close.", None,
        "lang-v1", "safety-v1", "rights-v1", "content-v1", key,
    )
    assert replay["id"] == version["id"]
    stored = one(
        db,
        "SELECT feedback_membership_id,feedback_candidate_id,"
        "attachment_class,serves_user,dataset_eligible "
        "FROM coach_guidance_attachments WHERE id=%s",
        (version["attachment_id"],),
    )
    assert stored == {
        "feedback_membership_id": None,
        "feedback_candidate_id": None,
        "attachment_class": "general_product_guidance",
        "serves_user": False,
        "dataset_eligible": False,
    }
    assert one(
        db,
        "SELECT (SELECT count(*) FROM exercise_practice_sessions) AS practice,"
        "(SELECT count(*) FROM exercise_practice_measurement_revisions) "
        "AS measurements,"
        "(SELECT count(*) FROM coach_inline_exercise_drafts) AS drafts",
    ) == product_counts_before


def test_ordinary_private_video_uses_exact_assignment_media_lineage(db, ctx):
    packet = d3._make_packet(db, ctx)
    _render_and_judge(db, ctx, packet)
    result = one(
        db,
        "SELECT public.prepare_coach_inline_guidance_context_v1("
        "%s,%s,%s,%s) AS payload",
        (ctx["project"], ctx["owner"], ctx["reviewer"], str(uuid4())),
    )["payload"]
    item = result["items"][0]
    authority = rpc(
        db, "issue_coach_inline_general_authority_v1",
        result["review_batch_id"], result["reveal_grant_id"],
        item["reveal_access_id"], item["review_assignment_id"],
        ctx["reviewer"], str(uuid4()),
    )
    access = {
        "id": item["reveal_access_id"],
        "reveal_grant_id": result["reveal_grant_id"],
        "review_assignment_id": item["review_assignment_id"],
    }
    permit, media, _ = d3._finalized_media(
        db, ctx, access, authorization_snapshot=authority["id"],
    )
    binding = d3._media_binding(
        db, ctx, permit, media, authorization_snapshot=authority["id"],
    )
    attachment_key = str(uuid4())
    version = rpc(
        db, "create_coach_inline_general_guidance_v1",
        result["review_batch_id"], result["reveal_grant_id"],
        item["reveal_access_id"], item["review_assignment_id"],
        ctx["reviewer"], authority["id"], "structure", None,
        binding["id"], "lang-v1", "safety-v1", "rights-v1",
        "content-v1", attachment_key,
    )
    assert version["media_binding_id"] == binding["id"]

    holder = d3.connect()
    holder.autocommit = False
    lock_name = "coach-guidance-media-validity:" + media["id"]
    query(
        holder,
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        (lock_name,),
    )
    application = "d5_general_replay_" + uuid4().hex[:18]

    def replay_after_wait():
        connection = d3.connect()
        try:
            query(connection, "SET application_name=%s", (application,))
            return rpc(
                connection, "create_coach_inline_general_guidance_v1",
                result["review_batch_id"], result["reveal_grant_id"],
                item["reveal_access_id"], item["review_assignment_id"],
                ctx["reviewer"], authority["id"], "structure", None,
                binding["id"], "lang-v1", "safety-v1", "rights-v1",
                "content-v1", attachment_key,
            )
        finally:
            connection.close()

    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            waiting = workers.submit(replay_after_wait)
            _wait_for_advisory(db, application)
            query(
                db,
                "UPDATE coach_users SET is_active=false WHERE email=("
                "SELECT auth_user.email FROM owner_principals principal "
                "JOIN auth.users auth_user ON auth_user.id=principal.user_id "
                "WHERE principal.id=%s)",
                (ctx["reviewer"],),
            )
            holder.commit()
            with pytest.raises(
                psycopg2.Error, match="COACH_GUIDANCE_REVIEWER_ACCESS_REQUIRED"
            ):
                waiting.result(timeout=5)
    finally:
        holder.rollback()
        holder.close()
    query(
        db,
        "UPDATE coach_users SET is_active=true WHERE email=("
        "SELECT auth_user.email FROM owner_principals principal "
        "JOIN auth.users auth_user ON auth_user.id=principal.user_id "
        "WHERE principal.id=%s)",
        (ctx["reviewer"],),
    )
    assert one(
        db,
        "SELECT count(*) AS n FROM coach_guidance_attachments "
        "WHERE idempotency_key=%s",
        ("inline-general:" + attachment_key,),
    )["n"] == 1
    with pytest.raises(psycopg2.Error):
        rpc(
            db, "create_coach_inline_general_guidance_v1",
            str(uuid4()), result["reveal_grant_id"],
            item["reveal_access_id"], item["review_assignment_id"],
            ctx["reviewer"], authority["id"], "structure", None,
            binding["id"], "lang-v1", "safety-v1", "rights-v1",
            "content-v1", str(uuid4()),
        )
    query(
        db,
        "INSERT INTO processing_service_blocks("
        "acquisition_principal_id,effective_at) VALUES (%s,clock_timestamp())",
        (ctx["owner"],),
    )
    with pytest.raises(psycopg2.Error):
        rpc(
            db, "create_coach_inline_general_guidance_v1",
            result["review_batch_id"], result["reveal_grant_id"],
            item["reveal_access_id"], item["review_assignment_id"],
            ctx["reviewer"], authority["id"], "structure", None,
            binding["id"], "lang-v1", "safety-v1", "rights-v1",
            "content-v1", str(uuid4()),
        )


def test_same_snippet_assignments_stay_distinct_until_both_are_answered(db, ctx):
    first_packet = d3._make_packet(db, ctx)
    second_packet = d3._make_packet(db, ctx)
    first = _present_packet(db, ctx, first_packet)
    second = _present_packet(db, ctx, second_packet)
    batch = _batch(db, ctx)

    _render_visible_and_judge(db, ctx, first, "rating_yes")
    with pytest.raises(psycopg2.Error, match="COACH_GUIDANCE_BATCH_INCOMPLETE"):
        rpc(
            db, "complete_synthetic_coach_guidance_batch_v1",
            batch["id"], ctx["reviewer"], str(uuid4()),
        )

    _render_visible_and_judge(db, ctx, second, "rating_not_sure")
    revealed = one(
        db,
        "SELECT public.prepare_coach_inline_guidance_context_v1("
        "%s,%s,%s,%s) AS payload",
        (ctx["project"], ctx["owner"], ctx["reviewer"], str(uuid4())),
    )["payload"]
    assert revealed["reveal_grant_id"]
    same_clip = [
        item for item in revealed["items"]
        if item["snippet_id"] == ctx["snippet"]
    ]
    assert len(same_clip) == 2
    expected_order = [
        str(row["review_assignment_id"])
        for row in query(
            db,
            "SELECT review_assignment_id "
            "FROM coach_guidance_review_frame_items WHERE frame_id=%s "
            "ORDER BY canonical_position",
            (batch["frame_id"],),
        )
    ]
    assert [item["review_assignment_id"] for item in same_clip] == [
        item for item in expected_order
        if item in {first["review_assignment_id"], second["review_assignment_id"]}
    ]
    assert one(
        db,
        "SELECT count(*) AS n FROM ml_judgments "
        "WHERE review_assignment_id=ANY(%s::uuid[])",
        ([first["review_assignment_id"], second["review_assignment_id"]],),
    )["n"] == 2


def test_no_match_and_ordinary_items_share_one_complete_visible_batch(db):
    from tests.test_mlc3_first_client_service_postgres import (
        _activate_service,
        _service_membership,
    )

    context = d3.make_context(db)
    machine_source = source_pattern(db, context, "confident")
    # No compatibility profiles exist as of assignment.  The complete frozen
    # inventory is therefore honest no-match evidence, not a fabricated match.
    assignment = assign(db, context)
    rpc(
        db, "freeze_exercise_n1_pattern_snapshot_v1",
        assignment["id"], machine_source["id"], str(uuid4()),
    )
    _activate_service(db, context)
    feedback = _service_membership(db, context)
    rendered = rpc(
        db, "ack_feedback_v3_service_render_v1", context["owner"],
        feedback["owner_user"], feedback["membership"]["id"],
        feedback["candidate_id"], feedback["exposure_id"], str(uuid4()),
        feedback["membership"]["content_identity_sha256"],
        one(db, "SELECT clock_timestamp() AS t")["t"],
        "d5-postgres-test", str(uuid4()),
    )
    response = rpc(
        db, "record_feedback_v3_service_response_v1", context["project"],
        context["take"], context["owner"], feedback["owner_user"],
        feedback["membership"]["id"], feedback["candidate_id"],
        feedback["exposure_id"], rendered["id"], "confident_yes", str(uuid4()),
    )
    prepared = one(
        db,
        "SELECT public.prepare_feedback_v3_service_context_v1(%s,%s,%s,%s) "
        "AS payload",
        (
            feedback["membership"]["id"], feedback["candidate_id"],
            context["owner"], str(uuid4()),
        ),
    )["payload"]
    offer = rpc(
        db, "freeze_exercise_service_offer_v2", context["owner"],
        response["id"], prepared["n1_candidate_set_id"],
        prepared["authorization_check_id"], str(uuid4()),
    )
    d3._authorize_coach(db, context)
    context["second_evidence"] = one(
        db,
        "SELECT evidence.id FROM exercise_audio_lineages lineage "
        "JOIN ml_evidence_spans evidence ON evidence.take_id=lineage.take_id "
        "AND evidence.recording_attempt_id=lineage.recording_attempt_id "
        "AND (evidence.coordinates->>'start_ms')::integer="
        "lineage.start_offset_ms "
        "AND (evidence.coordinates->>'end_ms')::integer="
        "lineage.start_offset_ms+lineage.duration_ms "
        "WHERE lineage.id=%s",
        (context["second_lineage"],),
    )["id"]
    ordinary_packet = d3._make_packet(db, context, second=True)
    ordinary_visible = _present_packet(db, context, ordinary_packet)
    canonical_event_id = str(uuid4())
    query(
        db,
        "INSERT INTO ml_canonical_events(id,learning_surface_id,"
        "feedback_family_id,payload_type) VALUES "
        "(%s,'confidence_classification','confident_voice','confidence_event')",
        (canonical_event_id,),
    )
    query(
        db,
        "UPDATE ml_evidence_spans SET canonical_event_id=%s WHERE id=%s",
        (canonical_event_id, context["evidence"]),
    )
    before = one(
        db,
        "SELECT (SELECT count(*) FROM exercise_practice_sessions) AS sessions,"
        "(SELECT count(*) FROM exercise_practice_attempts) AS attempts",
    )
    visible = one(
        db,
        "SELECT public.prepare_coach_inline_blind_batch_v1(%s,%s,%s,%s) "
        "AS payload",
        (
            context["project"], context["owner"], context["reviewer"],
            str(uuid4()),
        ),
    )["payload"]
    assert len(visible["items"]) == 2
    exact = next(
        item for item in visible["items"]
        if item["snippet_id"] == context["snippet"]
    )
    assert exact["review_assignment_id"] == exact["playback_reference_id"]
    assert one(
        db,
        "SELECT count(*) AS n FROM exercise_blind_packets "
        "WHERE review_assignment_id=%s",
        (exact["review_assignment_id"],),
    )["n"] == 1
    assert offer["outcome"] == "coach_exercise_requested"
    exact_judgment = _render_visible_and_judge(db, context, exact, "rating_yes")
    ordinary_item = next(
        item for item in visible["items"]
        if item["review_assignment_id"] == ordinary_visible["review_assignment_id"]
    )
    ordinary_judgment = _render_visible_and_judge(
        db, context, ordinary_item, "rating_not_sure"
    )
    assert exact_judgment["review_assignment_id"] != ordinary_judgment[
        "review_assignment_id"
    ]
    revealed = one(
        db,
        "SELECT public.prepare_coach_inline_guidance_context_v1("
        "%s,%s,%s,%s) AS payload",
        (
            context["project"], context["owner"], context["reviewer"],
            str(uuid4()),
        ),
    )["payload"]
    assert len(revealed["items"]) == 2
    eligibility = {
        item["review_assignment_id"]: item["exercise_eligible"]
        for item in revealed["items"]
    }
    assert eligibility[exact["review_assignment_id"]] is True
    assert eligibility[ordinary_item["review_assignment_id"]] is False
    assert [
        item["review_assignment_id"] for item in revealed["items"]
    ] == [item["review_assignment_id"] for item in visible["items"]]
    assert one(
        db,
        "SELECT count(*) AS n FROM ml_judgments "
        "WHERE review_assignment_id=ANY(%s::uuid[])",
        ([item["review_assignment_id"] for item in visible["items"]],),
    )["n"] == 2
    assert one(
        db,
        "SELECT count(*) AS n FROM ml_review_assignments "
        "WHERE id=ANY(%s::uuid[])",
        ([item["review_assignment_id"] for item in visible["items"]],),
    )["n"] == 2
    after = one(
        db,
        "SELECT (SELECT count(*) FROM exercise_practice_sessions) AS sessions,"
        "(SELECT count(*) FROM exercise_practice_attempts) AS attempts",
    )
    assert after == before


def test_release_migration_reapplies_cleanly(db):
    migration = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "migrations/add_mlc3_coach_inline_exercise_authoring_d5.sql"
    ).read_text()
    with db.cursor() as cursor:
        cursor.execute(migration)
