"""
STORY    As a coach, I want the blind audio for my assignment to resolve only
         for me and only while the speaker still allows processing, so that
         coach review stays blind, bound to the assignment and stops at
         revocation.
OUTCOME
  O1  The assigned reviewer gets the exact span of the clip, and nothing
      else: no prediction, score or label rides with it (Never-2: no coach
      sees the machine's guess before answering).
  O2  Another active coach, or the reviewer's login on someone else's
      principal, is refused.
  O3  Once the speaker's processing is blocked, the read raises.
  O4  Resolving the audio creates no practice or draft rows.
PROVES   O1, O2, O3, O4 -> test_blind_audio_resolver_is_assignment_bound_and_fails_after_revocation
WHY      D5 coach inline authoring (pending lane in scripts/rehearsal_tier.sh).
"""
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

_COUNTS = (
    "SELECT (SELECT count(*) FROM exercise_practice_sessions) AS practice,"
    "(SELECT count(*) FROM exercise_practice_attempts) AS attempts,"
    "(SELECT count(*) FROM coach_inline_exercise_drafts) AS drafts"
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
    """Shared fixture: tests/test_confident_moment_coaching_bundle_postgres.py imports it."""
    return rpc(
        db,
        "freeze_synthetic_coach_guidance_batch_v1",
        context["owner"],
        context["project"],
        context["reviewer"],
        str(uuid4()),
    )


def _other_active_coach(db) -> tuple[str, str]:
    """A second principal with live coach access, not assigned to the packet."""
    principal, user = str(uuid4()), str(uuid4())
    email = f"coach-{uuid4().hex}@example.test"
    query(db, "INSERT INTO owner_principals(id,user_id) VALUES (%s,%s)", (principal, user))
    query(db, "INSERT INTO auth.users(id,email) VALUES (%s,%s)", (user, email))
    query(db, "INSERT INTO coach_users(email,is_active) VALUES (%s,true)", (email,))
    return principal, user


def test_blind_audio_resolver_is_assignment_bound_and_fails_after_revocation(db, ctx):
    counts_before = one(db, _COUNTS)
    packet = d3._make_packet(db, ctx)
    assignment_id = packet["review_assignment_id"]
    reviewer_user = one(
        db, "SELECT user_id FROM owner_principals WHERE id=%s", (ctx["reviewer"],)
    )["user_id"]

    # O1: the assigned coach gets the clip's exact span and only the audio.
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
    assert set(resolved) == {
        "assignment_id", "blind_packet_id", "bucket", "object_key",
        "exact_bytes_sha256", "byte_size", "content_type",
        "start_offset_ms", "duration_ms",
    }

    # O2: bound to the assignment and to the reviewer's own identity.
    other_principal, other_user = _other_active_coach(db)
    with pytest.raises(psycopg2.Error):
        rpc(db, "resolve_coach_inline_blind_audio_read_v1",
            assignment_id, other_user, other_principal)
    with pytest.raises(psycopg2.Error, match="COACH_INLINE_REVIEWER_IDENTITY_INVALID"):
        rpc(db, "resolve_coach_inline_blind_audio_read_v1",
            assignment_id, other_user, ctx["reviewer"])

    # O4: reading the audio writes nothing.
    assert one(db, _COUNTS) == counts_before

    # O3: revocation stops the read.
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
