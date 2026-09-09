"""Adversarial PostgreSQL tests for disabled Coach Guidance D3.

The target must be a disposable local database whose name starts with
``willab_d3_``.  These fixtures create synthetic identities and media only;
they never call R2 or expose guidance to a user.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extras import Json

from tests.test_mlc3_dark_assignments_postgres import (
    assign,
    make_context,
    one,
    query,
    rpc,
)
from tests.test_mlc3_n1_source_pattern_postgres import profile, source_pattern
from tests.test_rooting_phrase_qualification_postgres import _v3_context

DSN = os.environ.get("COACH_GUIDANCE_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="disposable D3 rehearsal only")


def connect():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_d3_"):
        raise RuntimeError("Refusing a non-disposable database")
    if not parsed.get("host", "").startswith(("/tmp/willab-", "/private/tmp/willab-")):
        raise RuntimeError("Refusing a non-local rehearsal host")
    connection = psycopg2.connect(DSN)
    connection.autocommit = True
    return connection


def _install_full_review_shape(db) -> None:
    query(db, "CREATE SCHEMA IF NOT EXISTS auth")
    query(
        db,
        "CREATE TABLE IF NOT EXISTS auth.users(id uuid PRIMARY KEY,email text)",
    )
    query(db, "ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS email text")
    query(
        db,
        "CREATE TABLE IF NOT EXISTS coach_users("
        "email text PRIMARY KEY,is_active boolean NOT NULL DEFAULT true)",
    )
    for statement in (
        (
            "ALTER TABLE ml_review_assignments ADD COLUMN IF NOT EXISTS "
            "reviewer_role text NOT NULL DEFAULT 'coach'"
        ),
        (
            "ALTER TABLE ml_review_assignments ADD COLUMN IF NOT EXISTS "
            "blindness_policy_version text NOT NULL DEFAULT 'blind-policy-v1'"
        ),
        (
            "ALTER TABLE ml_review_assignments ADD COLUMN IF NOT EXISTS "
            "assigned_at timestamptz NOT NULL DEFAULT clock_timestamp()"
        ),
        (
            "ALTER TABLE ml_review_assignments ADD COLUMN IF NOT EXISTS "
            "expires_at timestamptz NULL"
        ),
        (
            "ALTER TABLE ml_review_assignments ADD COLUMN IF NOT EXISTS "
            "idempotency_key text NULL"
        ),
        (
            "ALTER TABLE ml_judgments ADD COLUMN IF NOT EXISTS "
            "supersedes_id uuid NULL REFERENCES ml_judgments(id)"
        ),
        (
            "ALTER TABLE ml_judgments ADD COLUMN IF NOT EXISTS "
            "decided_at timestamptz NOT NULL DEFAULT clock_timestamp()"
        ),
    ):
        query(db, statement)
    query(
        db,
        "CREATE TABLE IF NOT EXISTS ml_review_assignment_events("
        "id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        "review_assignment_id uuid NOT NULL REFERENCES ml_review_assignments(id),"
        "event_kind text NOT NULL CHECK(event_kind IN "
        "('assigned','opened','submitted','revealed','expired','cancelled')) ,"
        "occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),"
        "actor_principal_id uuid NULL REFERENCES owner_principals(id),"
        "idempotency_key text NOT NULL UNIQUE,"
        "metadata jsonb NOT NULL DEFAULT '{}'::jsonb,"
        "UNIQUE(review_assignment_id,event_kind))",
    )
    query(
        db,
        "ALTER TABLE ml_evidence_spans ADD COLUMN IF NOT EXISTS "
        "canonical_event_id uuid NULL REFERENCES ml_canonical_events(id)",
    )


def _make_packet(db, ctx, *, second: bool = False, expired: bool = False):
    assignment_id, packet_id, reference_id = (str(uuid4()) for _ in range(3))
    lineage_id = ctx["second_lineage"] if second else ctx["lineage"]
    evidence_id = ctx["second_evidence"] if second else ctx["evidence"]
    digest = one(
        db,
        "SELECT exercise_json_sha256_v1("
        "build_exercise_blind_visible_payload_v1(%s,%s,"
        "'confidence-exercise-blind-packet-v1','confidence-five-state-v1',"
        "%s,2400,%s,NULL)) AS h",
        (packet_id, assignment_id, reference_id, ctx["language"]),
    )["h"]
    assigned = "clock_timestamp()-interval '2 minutes'"
    expires = (
        "clock_timestamp()-interval '1 minute'"
        if expired
        else "clock_timestamp()+interval '10 minutes'"
    )
    query(
        db,
        "INSERT INTO ml_review_assignments("
        "id,learning_surface_id,evidence_span_id,reviewer_principal_id,"
        "reviewer_role,blind_packet_sha256,taxonomy_version,"
        "blindness_policy_version,assigned_at,expires_at,idempotency_key) "
        f"VALUES (%s,'confidence_classification',%s,%s,'coach',%s,"
        f"'confidence-five-state-v1','blind-policy-v1',{assigned},{expires},%s)",
        (assignment_id, evidence_id, ctx["reviewer"], digest, str(uuid4())),
    )
    return rpc(
        db,
        "register_exercise_blind_packet_v1",
        packet_id,
        assignment_id,
        lineage_id,
        ctx["blind_auth"],
        ctx["reviewer"],
        "confidence-exercise-blind-packet-v1",
        "confidence-five-state-v1",
        reference_id,
        one(db, "SELECT clock_timestamp()+interval '10 minutes' AS t")["t"],
        2400,
        ctx["language"],
        None,
        "blind-policy-v1",
        str(uuid4()),
    )


def _authorize_coach(db, ctx) -> str:
    principal = one(
        db,
        "SELECT user_id FROM owner_principals WHERE id=%s",
        (ctx["reviewer"],),
    )
    email = f"coach-{uuid4().hex}@example.test"
    query(
        db,
        "INSERT INTO auth.users(id,email) VALUES (%s,%s)",
        (principal["user_id"], email),
    )
    query(db, "INSERT INTO coach_users(email,is_active) VALUES (%s,true)", (email,))
    query(
        db,
        "INSERT INTO processing_purpose_registry("
        "id,operational,authorizes_processing) VALUES ('coach_review',true,true) "
        "ON CONFLICT(id) DO UPDATE SET operational=true,authorizes_processing=true",
    )
    query(
        db,
        "INSERT INTO processing_policy_purposes(policy_id,purpose_id) "
        "VALUES (%s,'coach_review') ON CONFLICT DO NOTHING",
        (ctx["policy"],),
    )
    query(
        db,
        "INSERT INTO processing_authorization_receipt_purposes("
        "receipt_id,purpose_id) VALUES (%s,'coach_review') ON CONFLICT DO NOTHING",
        (ctx["receipt"],),
    )
    snapshot_id = str(uuid4())
    query(
        db,
        "INSERT INTO processing_authorization_snapshots "
        "VALUES (%s,%s,%s,%s,'coach_review')",
        (snapshot_id, ctx["owner"], ctx["receipt"], ctx["policy"]),
    )
    return snapshot_id


@pytest.fixture
def db():
    connection = connect()
    _install_full_review_shape(connection)
    yield connection
    connection.close()


@pytest.fixture
def ctx(db):
    context = make_context(db)
    context["second_evidence"] = one(
        db,
        "SELECT evidence.id FROM exercise_audio_lineages lineage "
        "JOIN ml_evidence_spans evidence ON evidence.take_id=lineage.take_id "
        "AND evidence.recording_attempt_id=lineage.recording_attempt_id "
        "AND (evidence.coordinates->>'start_ms')::integer=lineage.start_offset_ms "
        "AND (evidence.coordinates->>'end_ms')::integer="
        "lineage.start_offset_ms+lineage.duration_ms "
        "WHERE lineage.id=%s",
        (context["second_lineage"],),
    )["id"]
    context["coach_snapshot"] = _authorize_coach(db, context)
    return context


def _judge(
    db,
    ctx,
    packet,
    *,
    actor_provenance="blind_coach",
    decision="rating_not_sure",
):
    judgment_id = str(uuid4())
    query(
        db,
        "INSERT INTO ml_judgments("
        "id,review_assignment_id,learning_surface_id,evidence_span_id,"
        "actor_provenance,actor_principal_id,decision) "
        "VALUES (%s,%s,'confidence_classification',%s,%s,%s,%s)",
        (
            judgment_id,
            packet["review_assignment_id"],
            one(
                db,
                "SELECT evidence_span_id FROM ml_review_assignments WHERE id=%s",
                (packet["review_assignment_id"],),
            )["evidence_span_id"],
            actor_provenance,
            ctx["reviewer"],
            decision,
        ),
    )
    query(
        db,
        "INSERT INTO exercise_blind_packet_events("
        "blind_packet_id,review_assignment_id,event_kind,actor_principal_id,"
        "judgment_id,blindness_policy_version,idempotency_key,occurred_at) "
        "VALUES (%s,%s,'blind_judgment_submitted',%s,%s,'blind-policy-v1',"
        "%s,clock_timestamp())",
        (
            packet["id"],
            packet["review_assignment_id"],
            ctx["reviewer"],
            judgment_id,
            str(uuid4()),
        ),
    )
    return judgment_id


def test_coach_review_remains_live_without_exercise_purpose(db, ctx):
    _make_packet(db, ctx)
    query(
        db,
        "DELETE FROM processing_authorization_receipt_purposes "
        "WHERE receipt_id=%s AND purpose_id='personalized_exercise_recommendation'",
        (ctx["receipt"],),
    )
    batch = rpc(
        db,
        "freeze_synthetic_coach_guidance_batch_v1",
        ctx["owner"],
        ctx["project"],
        ctx["reviewer"],
        str(uuid4()),
    )
    assert batch["batch_revision"] == 1
    query(
        db,
        "DELETE FROM processing_authorization_receipt_purposes "
        "WHERE receipt_id=%s AND purpose_id='coach_review'",
        (ctx["receipt"],),
    )
    with pytest.raises(psycopg2.Error, match="CURRENT_AUTHORITY_REQUIRED"):
        rpc(
            db,
            "freeze_synthetic_coach_guidance_batch_v1",
            ctx["owner"],
            ctx["project"],
            ctx["reviewer"],
            str(uuid4()),
        )


def test_terminal_assignments_create_an_immutable_batch_revision(db, ctx):
    first = _make_packet(db, ctx)
    second = _make_packet(db, ctx, second=True)
    first_batch = rpc(
        db,
        "freeze_synthetic_coach_guidance_batch_v1",
        ctx["owner"],
        ctx["project"],
        ctx["reviewer"],
        str(uuid4()),
    )
    query(
        db,
        "INSERT INTO ml_review_assignment_events("
        "review_assignment_id,event_kind,actor_principal_id,idempotency_key) "
        "VALUES (%s,'cancelled',%s,%s)",
        (first["review_assignment_id"], ctx["reviewer"], str(uuid4())),
    )
    with pytest.raises(psycopg2.Error, match="SOURCE_NOT_LIVE"):
        rpc(
            db,
            "freeze_synthetic_coach_guidance_batch_v1",
            ctx["owner"],
            ctx["project"],
            ctx["reviewer"],
            first_batch["idempotency_key"],
        )
    revised = rpc(
        db,
        "freeze_synthetic_coach_guidance_batch_v1",
        ctx["owner"],
        ctx["project"],
        ctx["reviewer"],
        str(uuid4()),
    )
    assert revised["batch_revision"] == 2
    assert revised["supersedes_batch_id"] == first_batch["id"]
    frame = one(
        db,
        "SELECT eligible_assignment_count,excluded_assignment_count "
        "FROM coach_guidance_review_frames WHERE id=%s",
        (revised["frame_id"],),
    )
    assert frame == {"eligible_assignment_count": 1, "excluded_assignment_count": 1}
    required = one(
        db,
        "SELECT review_assignment_id FROM coach_guidance_review_frame_items "
        "WHERE frame_id=%s AND membership_state='required'",
        (revised["frame_id"],),
    )
    assert required["review_assignment_id"] == second["review_assignment_id"]


def test_all_terminal_assignments_create_zero_required_successor(db, ctx):
    packets = [_make_packet(db, ctx), _make_packet(db, ctx, second=True)]
    first_batch = rpc(
        db,
        "freeze_synthetic_coach_guidance_batch_v1",
        ctx["owner"],
        ctx["project"],
        ctx["reviewer"],
        str(uuid4()),
    )
    for packet in packets:
        query(
            db,
            "INSERT INTO ml_review_assignment_events("
            "review_assignment_id,event_kind,actor_principal_id,idempotency_key) "
            "VALUES (%s,'cancelled',%s,%s)",
            (packet["review_assignment_id"], ctx["reviewer"], str(uuid4())),
        )
    revised = rpc(
        db,
        "freeze_synthetic_coach_guidance_batch_v1",
        ctx["owner"],
        ctx["project"],
        ctx["reviewer"],
        str(uuid4()),
    )
    assert revised["batch_revision"] == 2
    assert revised["supersedes_batch_id"] == first_batch["id"]
    frame = one(
        db,
        "SELECT eligible_assignment_count,excluded_assignment_count "
        "FROM coach_guidance_review_frames WHERE id=%s",
        (revised["frame_id"],),
    )
    assert frame == {"eligible_assignment_count": 0, "excluded_assignment_count": 2}
    exclusions = query(
        db,
        "SELECT membership_state,exclusion_reason "
        "FROM coach_guidance_review_frame_items WHERE frame_id=%s",
        (revised["frame_id"],),
    )
    assert len(exclusions) == 2
    assert all(row["membership_state"] == "excluded" for row in exclusions)
    assert all(
        row["exclusion_reason"] == "cancelled_before_cutoff" for row in exclusions
    )


def test_coach_batch_rejects_peer_judgment_and_accepts_all_five_coach_answers(db, ctx):
    peer_packet = _make_packet(db, ctx)
    _judge(db, ctx, peer_packet, actor_provenance="blind_peer")
    peer_batch = rpc(
        db,
        "freeze_synthetic_coach_guidance_batch_v1",
        ctx["owner"],
        ctx["project"],
        ctx["reviewer"],
        str(uuid4()),
    )
    with pytest.raises(psycopg2.Error, match="COACH_GUIDANCE_BATCH_INCOMPLETE"):
        rpc(
            db,
            "complete_synthetic_coach_guidance_batch_v1",
            peer_batch["id"],
            ctx["reviewer"],
            str(uuid4()),
        )

    # Keep the peer assignment out of the next coach-only batch revision.
    query(
        db,
        "INSERT INTO ml_review_assignment_events("
        "review_assignment_id,event_kind,actor_principal_id,idempotency_key) "
        "VALUES (%s,'cancelled',%s,%s)",
        (peer_packet["review_assignment_id"], ctx["reviewer"], str(uuid4())),
    )
    decisions = (
        "rating_yes",
        "rating_in_between",
        "rating_no",
        "rating_not_sure",
        "rating_audio_unclear",
    )
    for index, decision in enumerate(decisions):
        packet = _make_packet(db, ctx, second=bool(index % 2))
        _judge(db, ctx, packet, decision=decision)
    coach_batch = rpc(
        db,
        "freeze_synthetic_coach_guidance_batch_v1",
        ctx["owner"],
        ctx["project"],
        ctx["reviewer"],
        str(uuid4()),
    )
    grant = rpc(
        db,
        "complete_synthetic_coach_guidance_batch_v1",
        coach_batch["id"],
        ctx["reviewer"],
        str(uuid4()),
    )
    assert grant["review_batch_id"] == coach_batch["id"]
    assert (
        one(
            db,
            "SELECT count(*) AS n FROM coach_guidance_reveal_grant_judgments "
            "WHERE reveal_grant_id=%s",
            (grant["id"],),
        )["n"]
        == 5
    )


def test_expired_assignment_is_excluded_not_treated_as_pending(db, ctx):
    _make_packet(db, ctx)
    expired = _make_packet(db, ctx, second=True, expired=True)
    batch = rpc(
        db,
        "freeze_synthetic_coach_guidance_batch_v1",
        ctx["owner"],
        ctx["project"],
        ctx["reviewer"],
        str(uuid4()),
    )
    excluded = one(
        db,
        "SELECT exclusion_reason FROM coach_guidance_review_frame_items "
        "WHERE frame_id=%s AND review_assignment_id=%s",
        (batch["frame_id"], expired["review_assignment_id"]),
    )
    assert excluded["exclusion_reason"] == "expired_before_cutoff"


def test_reviewer_access_loss_during_batch_contention_fails_closed(db, ctx):
    _make_packet(db, ctx)
    holder = connect()
    holder.autocommit = False
    query(
        holder,
        "SELECT pg_advisory_xact_lock(hashtextextended(concat_ws(':',"
        "'coach-guidance-batch',%s,%s,%s),0))",
        (ctx["owner"], ctx["project"], ctx["reviewer"]),
    )
    application = "d3_access_" + uuid4().hex

    def work():
        connection = connect()
        try:
            query(connection, "SET application_name=%s", (application,))
            return rpc(
                connection,
                "freeze_synthetic_coach_guidance_batch_v1",
                ctx["owner"],
                ctx["project"],
                ctx["reviewer"],
                str(uuid4()),
            )
        finally:
            connection.close()

    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(work)
            deadline = monotonic() + 5
            while not query(
                db,
                "SELECT 1 FROM pg_stat_activity "
                "WHERE application_name=%s AND wait_event='advisory'",
                (application,),
            ):
                if monotonic() >= deadline:
                    raise AssertionError("worker never reached advisory wait")
                sleep(0.01)
            query(
                db,
                "UPDATE coach_users SET is_active=false WHERE email=("
                "SELECT auth_user.email FROM owner_principals principal "
                "JOIN auth.users auth_user ON auth_user.id=principal.user_id "
                "WHERE principal.id=%s)",
                (ctx["reviewer"],),
            )
            holder.commit()
            with pytest.raises(psycopg2.Error, match="REVIEWER_ACCESS_REQUIRED"):
                future.result(timeout=5)
    finally:
        holder.rollback()
        holder.close()


def _completed_access(db, ctx):
    packet = _make_packet(db, ctx)
    _judge(db, ctx, packet)
    batch = rpc(
        db,
        "freeze_synthetic_coach_guidance_batch_v1",
        ctx["owner"],
        ctx["project"],
        ctx["reviewer"],
        str(uuid4()),
    )
    grant = rpc(
        db,
        "complete_synthetic_coach_guidance_batch_v1",
        batch["id"],
        ctx["reviewer"],
        str(uuid4()),
    )
    return rpc(
        db,
        "record_synthetic_guidance_reveal_access_v1",
        grant["id"],
        ctx["reviewer"],
        packet["review_assignment_id"],
        "guidance_authoring",
        str(uuid4()),
    )


def _finalized_media(
    db,
    ctx,
    access,
    *,
    purpose="coach_review",
    authorization_snapshot=None,
):
    authorization_snapshot = authorization_snapshot or ctx["coach_snapshot"]
    digest = uuid4().hex * 2
    permit = rpc(
        db,
        "reserve_synthetic_coach_guidance_upload_v1",
        access["id"],
        ctx["reviewer"],
        authorization_snapshot,
        purpose,
        "synthetic-coach-guidance",
        "coach/" + uuid4().hex + ".mp4",
        digest,
        1024,
        "video/mp4",
        one(db, "SELECT clock_timestamp()+interval '10 minutes' AS t")["t"],
        str(uuid4()),
    )
    for event_kind in ("write_started", "write_acknowledged"):
        rpc(
            db,
            "record_synthetic_coach_guidance_upload_event_v1",
            permit["id"],
            ctx["reviewer"],
            event_kind,
            None,
            str(uuid4()),
        )
    media = rpc(
        db,
        "register_exercise_media_object_v1",
        permit["bucket"],
        permit["object_key"],
        digest,
        1024,
        "video/mp4",
        "read_after_write_sha256",
        one(db, "SELECT clock_timestamp() AS t")["t"],
        "synthetic-only",
        "d3-rehearsal",
    )
    finalize_key = str(uuid4())
    rpc(
        db,
        "record_synthetic_coach_guidance_upload_event_v1",
        permit["id"],
        ctx["reviewer"],
        "finalized",
        media["id"],
        finalize_key,
    )
    return permit, media, finalize_key


def _media_binding(
    db,
    ctx,
    permit,
    media,
    *,
    purpose="coach_review",
    authorization_snapshot=None,
    idempotency_key=None,
):
    authorization_snapshot = authorization_snapshot or ctx["coach_snapshot"]
    return rpc(
        db,
        "register_synthetic_coach_guidance_media_v1",
        media["id"],
        ctx["owner"],
        authorization_snapshot,
        purpose,
        "user_scoped" if purpose == "coach_review" else "user_source_dependent",
        ctx["owner"],
        None,
        permit["id"],
        "lang-v1",
        "safety-v1",
        "rights-v1",
        "content-v1",
        idempotency_key or str(uuid4()),
    )


def _general_attachment(db, ctx, access, v3, binding, *, idempotency_key=None):
    return rpc(
        db,
        "create_synthetic_coach_guidance_attachment_v1",
        access["reveal_grant_id"],
        access["id"],
        ctx["reviewer"],
        access["review_assignment_id"],
        v3["membership"]["id"],
        v3["confidence"],
        ctx["coach_snapshot"],
        "general_product_guidance",
        "delivery",
        None,
        None,
        None,
        "Synthetic guidance.",
        binding["id"],
        "lang-v1",
        "safety-v1",
        "rights-v1",
        "content-v1",
        idempotency_key or str(uuid4()),
    )


def _invalidate_during_lock_wait(db, ctx, media, lock_name, operation):
    holder = connect()
    holder.autocommit = False
    query(
        holder,
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        (lock_name,),
    )
    application = "d3_media_" + uuid4().hex[:20]

    def work():
        connection = connect()
        try:
            query(connection, "SET application_name=%s", (application,))
            return operation(connection)
        finally:
            connection.close()

    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(work)
            deadline = monotonic() + 5
            while not query(
                db,
                "SELECT 1 FROM pg_stat_activity "
                "WHERE application_name=%s AND wait_event='advisory'",
                (application,),
            ):
                if monotonic() >= deadline:
                    raise AssertionError("worker never reached advisory wait")
                sleep(0.01)
            rpc(
                db,
                "record_synthetic_coach_guidance_media_validity_v1",
                media["id"],
                ctx["owner"],
                "quarantined",
                "synthetic_race",
                "f" * 64,
                str(uuid4()),
            )
            holder.commit()
            with pytest.raises(psycopg2.Error, match="COACH_GUIDANCE_MEDIA_NOT_LIVE"):
                future.result(timeout=5)
    finally:
        holder.rollback()
        holder.close()


def test_clean_media_requires_review_and_invalid_media_fails_replay(db, ctx):
    access = _completed_access(db, ctx)
    permit, media, finalize_key = _finalized_media(db, ctx, access)
    args = (
        media["id"],
        ctx["owner"],
        ctx["coach_snapshot"],
        "coach_review",
        "independent_clean_media",
        None,
        None,
        permit["id"],
        "lang-v1",
        "safety-v1",
        "rights-v1",
        "content-v1",
        str(uuid4()),
    )
    with pytest.raises(psycopg2.Error, match="MEDIA_INVALID"):
        rpc(db, "register_synthetic_coach_guidance_media_v1", *args)
    review = rpc(
        db,
        "register_synthetic_independent_media_review_v1",
        media["id"],
        ctx["reviewer"],
        False,
        False,
        False,
        False,
        False,
        "lang-v1",
        "safety-v1",
        "rights-v1",
        "content-v1",
        "a" * 64,
        str(uuid4()),
    )
    binding = rpc(
        db,
        "register_synthetic_coach_guidance_media_v1",
        media["id"],
        ctx["owner"],
        ctx["coach_snapshot"],
        "coach_review",
        "independent_clean_media",
        None,
        review["id"],
        permit["id"],
        "lang-v1",
        "safety-v1",
        "rights-v1",
        "content-v1",
        str(uuid4()),
    )
    previous = one(
        db,
        "SELECT event_sha256 FROM coach_guidance_media_validity_events "
        "WHERE media_object_id=%s",
        (media["id"],),
    )
    for state in ("quarantined", "invalid", "deleted"):
        rpc(
            db,
            "record_synthetic_coach_guidance_media_validity_v1",
            media["id"],
            ctx["owner"],
            state,
            f"synthetic_{state}",
            previous["event_sha256"],
            str(uuid4()),
        )
        previous = one(
            db,
            "SELECT event_sha256 FROM coach_guidance_media_validity_events "
            "WHERE media_object_id=%s ORDER BY occurred_at DESC,id DESC LIMIT 1",
            (media["id"],),
        )
        with pytest.raises(psycopg2.Error, match="MEDIA_NOT_LIVE"):
            one(
                db,
                "SELECT require_coach_guidance_media_live_v1(%s,%s)",
                (binding["id"], ctx["owner"]),
            )
    with pytest.raises(psycopg2.Error, match="MEDIA_NOT_LIVE"):
        rpc(
            db,
            "record_synthetic_coach_guidance_upload_event_v1",
            permit["id"],
            ctx["reviewer"],
            "finalized",
            media["id"],
            finalize_key,
        )


def test_media_invalidation_during_binding_wait_fails_without_partial_row(db, ctx):
    access = _completed_access(db, ctx)
    permit, media, _ = _finalized_media(db, ctx, access)
    key = str(uuid4())
    _invalidate_during_lock_wait(
        db,
        ctx,
        media,
        "coach-guidance-media:" + key,
        lambda connection: _media_binding(
            connection, ctx, permit, media, idempotency_key=key
        ),
    )
    assert not query(
        db,
        "SELECT 1 FROM coach_guidance_media_bindings WHERE idempotency_key=%s",
        (key,),
    )


def test_media_invalidation_during_finalized_replay_wait_fails_closed(db, ctx):
    access = _completed_access(db, ctx)
    permit, media, finalize_key = _finalized_media(db, ctx, access)
    _invalidate_during_lock_wait(
        db,
        ctx,
        media,
        "coach-guidance-upload-permit:" + permit["id"],
        lambda connection: rpc(
            connection,
            "record_synthetic_coach_guidance_upload_event_v1",
            permit["id"],
            ctx["reviewer"],
            "finalized",
            media["id"],
            finalize_key,
        ),
    )


def test_media_invalidation_during_independent_review_wait_fails_closed(db, ctx):
    access = _completed_access(db, ctx)
    _, media, _ = _finalized_media(db, ctx, access)
    key = str(uuid4())
    _invalidate_during_lock_wait(
        db,
        ctx,
        media,
        "coach-guidance-independent-review:" + media["id"],
        lambda connection: rpc(
            connection,
            "register_synthetic_independent_media_review_v1",
            media["id"],
            ctx["reviewer"],
            False,
            False,
            False,
            False,
            False,
            "lang-v1",
            "safety-v1",
            "rights-v1",
            "content-v1",
            "a" * 64,
            key,
        ),
    )
    assert not query(
        db,
        "SELECT 1 FROM coach_guidance_independent_media_reviews "
        "WHERE idempotency_key=%s",
        (key,),
    )


def test_media_invalidation_during_attachment_wait_fails_without_partial_row(db, ctx):
    v3 = _v3_context(db, ctx)
    access = _completed_access(db, ctx)
    permit, media, _ = _finalized_media(db, ctx, access)
    binding = _media_binding(db, ctx, permit, media)
    key = str(uuid4())
    _invalidate_during_lock_wait(
        db,
        ctx,
        media,
        "coach-guidance-attachment:" + key,
        lambda connection: _general_attachment(
            connection, ctx, access, v3, binding, idempotency_key=key
        ),
    )
    assert not query(
        db,
        "SELECT 1 FROM coach_guidance_attachments WHERE idempotency_key=%s",
        ("attachment:" + key,),
    )


@pytest.mark.parametrize("event_kind", ["rendered", "played"])
def test_media_invalidation_during_render_or_play_wait_fails_without_event(
    db, ctx, event_kind
):
    v3 = _v3_context(db, ctx)
    access = _completed_access(db, ctx)
    permit, media, _ = _finalized_media(db, ctx, access)
    binding = _media_binding(db, ctx, permit, media)
    version = _general_attachment(db, ctx, access, v3, binding)
    preceding = ["assigned", "delivered"]
    if event_kind == "played":
        preceding.append("rendered")
    for prior_kind in preceding:
        actor = (
            ctx["reviewer"] if prior_kind in ("assigned", "delivered") else ctx["owner"]
        )
        rpc(
            db,
            "record_synthetic_coach_guidance_event_v1",
            version["id"],
            actor,
            prior_kind,
            Json({}),
            str(uuid4()),
        )
    key = str(uuid4())
    _invalidate_during_lock_wait(
        db,
        ctx,
        media,
        "coach-guidance-event:" + version["id"],
        lambda connection: rpc(
            connection,
            "record_synthetic_coach_guidance_event_v1",
            version["id"],
            ctx["owner"],
            event_kind,
            Json({}),
            key,
        ),
    )
    assert not query(
        db,
        "SELECT 1 FROM coach_guidance_lifecycle_events "
        "WHERE attachment_version_id=%s AND event_kind=%s",
        (version["id"], event_kind),
    )


def test_media_invalidation_during_publication_wait_fails_without_publication(db, ctx):
    v3 = _v3_context(db, ctx)
    source = source_pattern(db, ctx, "confident")
    for version in ctx["versions"]:
        profile(db, version["id"], ["confident"])
    assignment = assign(db, ctx)
    n1 = rpc(
        db,
        "freeze_exercise_n1_pattern_snapshot_v1",
        assignment["id"],
        source["id"],
        str(uuid4()),
    )
    offer = rpc(
        db,
        "freeze_synthetic_exercise_service_offer_v1",
        v3["membership"]["id"],
        v3["confidence"],
        n1["candidate_set_id"],
        ctx["auth"],
        str(uuid4()),
    )
    access = _completed_access(db, ctx)
    permit, media, _ = _finalized_media(
        db,
        ctx,
        access,
        purpose="personalized_exercise_recommendation",
        authorization_snapshot=ctx["snapshot"],
    )
    binding = _media_binding(
        db,
        ctx,
        permit,
        media,
        purpose="personalized_exercise_recommendation",
        authorization_snapshot=ctx["snapshot"],
    )
    attachment = rpc(
        db,
        "create_synthetic_coach_guidance_attachment_v1",
        access["reveal_grant_id"],
        access["id"],
        ctx["reviewer"],
        access["review_assignment_id"],
        v3["membership"]["id"],
        v3["confidence"],
        ctx["snapshot"],
        "mlc3_exercise",
        None,
        offer["id"],
        offer["selected_exercise_version_id"],
        ctx["need"],
        "Synthetic exercise guidance.",
        binding["id"],
        "lang-v1",
        "safety-v1",
        "rights-v1",
        "content-v1",
        str(uuid4()),
    )
    rpc(
        db,
        "record_exercise_media_availability_v1",
        media["id"],
        "available",
        media["exact_bytes_sha256"],
        "d" * 64,
        one(db, "SELECT clock_timestamp() AS t")["t"],
        str(uuid4()),
    )
    published_version = rpc(
        db,
        "register_exercise_version_v1",
        "published-" + uuid4().hex,
        "coach_case_specific",
        ctx["reviewer"],
        ctx["language"],
        1,
        ctx["need"],
        media["id"],
        "Synthetic published exercise.",
        "approved",
        "active",
        "d3-rehearsal",
    )
    catalog = rpc(
        db,
        "finalize_exercise_catalog_snapshot_v2",
        ctx["language"],
        str(uuid4()),
        "d3-rehearsal",
    )
    key = str(uuid4())
    _invalidate_during_lock_wait(
        db,
        ctx,
        media,
        "coach-guidance-publication:" + key,
        lambda connection: rpc(
            connection,
            "publish_synthetic_coach_exercise_v1",
            attachment["id"],
            published_version["id"],
            catalog["id"],
            ctx["snapshot"],
            key,
        ),
    )
    assert not query(
        db,
        "SELECT 1 FROM coach_guidance_publications WHERE idempotency_key=%s",
        (key,),
    )
