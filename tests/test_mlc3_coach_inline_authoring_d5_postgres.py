"""Executable PostgreSQL rejection tests for pending, disabled D5 authoring."""
from __future__ import annotations

from uuid import uuid4

import psycopg2
import pytest

from tests import test_coach_guidance_delivery_d3_postgres as d3
from tests.test_mlc3_dark_assignments_postgres import one, query, rpc

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
