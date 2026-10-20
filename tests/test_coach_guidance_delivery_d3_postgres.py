"""
STORY    As a speaker, I want coach guidance on my Take to depend on my
         coach-review permission, not on the exercise one, so that turning
         off coach review stops it.
OUTCOME
  O1  A guidance batch is still made when only the exercise permission is
      missing.
  O2  Once coach review is removed, a new batch is refused
      (CURRENT_AUTHORITY_REQUIRED).
PROVES   O1, O2 -> test_coach_review_remains_live_without_exercise_purpose
WHY      Coach Guidance D3 (disabled feature); runs on a disposable database
         with synthetic data only.
"""

from __future__ import annotations

import os
from uuid import uuid4

import psycopg2
import pytest

from tests.test_mlc3_dark_assignments_postgres import (
    make_context,
    one,
    query,
    rpc,
)

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
