"""Can the governed purge erase an account that recorded a real Take?

FOUNDER 2026-09-25 ("prove it first", before P1-B builds project scope on the
same engine). #658 proved an account erasure runs to the end for a speaker
whose only data is practice. No case had proved it for the product's own
data: a canonical Project with one recorded Take — its accepted recording
attempt, its stored audio, the take row itself.

The case runs `DataPurgeOrchestrator.run` — the Python production runs —
through the SQL client from tests/test_account_deletion_starts_postgres.py,
as service_role, against the disposable schema. Two stand-ins, both named:

  * every retention rule the registry can ask for is seeded active, as the
    signed retention schedule will seed them (production has none yet, so
    there a run stops at `review_required` before any of this matters);
  * the object-storage delete is faked to succeed, because this lane has no
    R2. Everything after it — marking the object purged, the dependency
    deletes, finalize — is the real code on the real schema.

WHAT IT FOUND. The purge deleted the Take and then failed on the project row:
retained recording-attempt evidence points at it ON DELETE RESTRICT. Founder
decision N9: the project row is kept as a tombstone with its content wiped
(migration 0368).
"""
from __future__ import annotations

import uuid

import pytest

from services import data_purge
from services.data_purge import DataPurgeOrchestrator
from services.data_purge_registry import DEPENDENCIES
from tests import test_account_deletion_starts_postgres as base

# The account-deletion suite's SQL client and fixture, bound as module
# attributes, which is how pytest finds fixtures.
DSN = base.DSN
_Database = base._Database
_one = base._one
db = base.db

pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)


def _seed_every_retention_rule(db) -> None:
    categories = sorted({
        d.retention_category for d in DEPENDENCIES
        if d.disposition == "retain" and d.retention_category
    })
    artifact = _one(db, """
        INSERT INTO public.processing_legal_artifacts (
            artifact_kind, version, approving_authority, approved_at,
            object_key, sha256)
        VALUES ('retention_schedule', 'rehearsal-' || gen_random_uuid(),
                'rehearsal', now(), 'rehearsal/retention.pdf', %s)
        RETURNING id""", ("a" * 64,))
    for category in categories:
        _one(db, """
            INSERT INTO public.data_retention_rules (
                rule_code, evidence_category, retention_until_rule,
                legal_artifact_id, active)
            SELECT %s, %s, 'rehearsal', %s, true
             WHERE NOT EXISTS (
                SELECT 1 FROM public.data_retention_rules
                 WHERE evidence_category = %s AND active)
            RETURNING id""",
            (f"rehearsal-{category}-{uuid.uuid4()}", category, artifact, category))


def _production_columns(db) -> None:
    """Columns production has and this disposable schema's minimal fixtures
    left out. Without them the purge's own row count raises
    PURGE_COUNT_SELECTOR_INVALID on the relation, which is a fixture gap, not
    a finding. Additive, and only in this database."""
    with db.cursor() as cur:
        cur.execute("""
            ALTER TABLE public.recordings
                ADD COLUMN IF NOT EXISTS session_v2_id UUID,
                ADD COLUMN IF NOT EXISTS session_id UUID;
            ALTER TABLE public.training_labels
                ADD COLUMN IF NOT EXISTS session_id UUID""")
        # Supabase grants service_role every privilege on public tables by
        # default; this schema has no Supabase, so it lacks them. Granted here
        # ONLY on tables no migration revokes from service_role — never a
        # blanket grant, which would hide the deliberate revokes (0327's
        # coaching-bundle tables) this case must still meet.
        cur.execute("""
            GRANT SELECT, INSERT, UPDATE, DELETE ON
                public.v2_sessions, public.projects,
                public.ideal_text_document_generations
            TO service_role""")


def _account_with_one_take(db) -> dict:
    """One person, one canonical Project, one accepted Take with stored audio,
    then an account-deletion request."""
    user_id = str(uuid.uuid4())
    principal = _one(db, """
        INSERT INTO public.owner_principals (id, user_id)
        VALUES (gen_random_uuid(), %s) RETURNING id""", (user_id,))
    project = _one(db, """
        INSERT INTO public.projects (id, owner_principal_id, display_name)
        VALUES (gen_random_uuid(), %s, 'Q3 pitch') RETURNING id""", (principal,))
    take = _one(db, """
        INSERT INTO public.v2_sessions (
            id, user_id, owner_principal_id, project_id, arc_id, take_index)
        VALUES (gen_random_uuid(), %s, %s, %s, %s, 1) RETURNING id""",
        (user_id, principal, project, project))
    policy = _one(db, """
        INSERT INTO public.processing_policy_versions (
            id, version, status, terms_version, terms_copy, terms_copy_sha256,
            privacy_version, privacy_copy, privacy_copy_sha256,
            ai_notice_version, ai_notice_copy, ai_notice_copy_sha256,
            agreement_copy, agreement_copy_sha256, allowed_countries,
            created_by)
        VALUES (gen_random_uuid(), 'take-purge-' || gen_random_uuid(), 'draft',
                'terms-v1', 'terms', repeat('1', 64), 'privacy-v1', 'privacy',
                repeat('2', 64), 'ai-v1', 'ai', repeat('3', 64), 'agreement',
                repeat('4', 64), ARRAY['PL'], 'rehearsal')
        RETURNING id""")
    receipt = _one(db, """
        INSERT INTO public.processing_authorization_receipts (
            id, acquisition_principal_id, policy_id, idempotency_key,
            explicit_action, age_18_attested, country_of_residence, locale,
            client_version, accepted_at, evidence_sha256)
        VALUES (gen_random_uuid(), %s, %s, %s, 'agree_and_continue', true,
                'PL', 'en', 'rehearsal', now(), repeat('5', 64))
        RETURNING id""", (principal, policy, str(uuid.uuid4())))
    attempt_id = str(uuid.uuid4())
    snapshot = _one(db, """
        INSERT INTO public.processing_authorization_snapshots (
            id, acquisition_principal_id, receipt_id, policy_id, purpose_id,
            operation_kind, source_recording_id, authority_evidence_sha256)
        VALUES (gen_random_uuid(), %s, %s, %s, 'recording_voice_processing',
                'recording_upload', %s, repeat('6', 64))
        RETURNING id""", (principal, receipt, policy, attempt_id))
    _one(db, """
        INSERT INTO public.processing_recording_attempts (
            id, acquisition_principal_id, project_id, recording_id,
            upload_idempotency_key, authorization_snapshot_id)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (attempt_id, principal, project, attempt_id, str(uuid.uuid4()), snapshot))
    audio = _one(db, """
        INSERT INTO public.processing_audio_objects (
            acquisition_principal_id, recording_attempt_id, storage_provider,
            bucket, object_key, byte_size, content_type, exact_bytes_sha256,
            verified_at, verification_method)
        VALUES (%s, %s, 'r2', 'take-audio', %s, 21, 'audio/wav',
                repeat('7', 64), now(), 'read_after_write_sha256')
        RETURNING id""", (principal, attempt_id, f"{principal}/{take}.wav"))
    request = _one(db, """
        INSERT INTO public.data_purge_requests (
            acquisition_principal_id, trigger_kind, idempotency_key)
        VALUES (%s, 'account_deletion', %s) RETURNING id""",
        (principal, str(uuid.uuid4())))
    return {"principal": str(principal), "project": str(project),
            "take": str(take), "attempt": attempt_id, "audio": str(audio),
            "request": str(request)}


@pytest.fixture
def fake_storage(monkeypatch):
    deleted: list[tuple[str, str]] = []

    def delete(key, *, bucket, storage_provider, expected_sha256):
        deleted.append((bucket, key))
        return True

    monkeypatch.setattr(data_purge, "delete_verified_lab_audio_object", delete)
    monkeypatch.setattr(data_purge, "verify_lab_audio_object_absent",
                        lambda key, *, bucket, storage_provider: True)
    return deleted


def _left_for_review(db, request: str) -> list:
    return _one(db, """
        SELECT coalesce(jsonb_agg(jsonb_build_object(
                   'ref', target_ref, 'state', state,
                   'reason', metadata->>'reason_code',
                   'error', last_error_code) ORDER BY target_ref),
               '[]'::jsonb)
          FROM public.data_purge_targets
         WHERE purge_request_id = %s AND state IN ('unknown', 'failed')""",
        (request,))


class TestAnAccountWithARealTakeCanBeErased:

    def test_the_erasure_reaches_done_and_the_take_is_gone(self, db, fake_storage):
        """Before 0368 this ended at review_required: the project delete was
        refused by retained recording-attempt evidence (RESTRICT)."""
        _production_columns(db)
        _seed_every_retention_rule(db)
        subject = _account_with_one_take(db)

        DataPurgeOrchestrator(_Database(db)).run(subject["request"])

        assert _left_for_review(db, subject["request"]) == []
        assert _one(db, "SELECT state FROM public.data_purge_requests WHERE id = %s",
                    (subject["request"],)) == "done"
        assert fake_storage, "the stored take audio was never deleted"
        # N12 (2026-09-26): the take session is an empty receipt, not a
        # deleted row. It keeps identity, ownership, index, kind, state and
        # times; every other nullable column is empty.
        assert _one(db, "SELECT count(*) FROM public.v2_sessions WHERE id = %s",
                    (subject["take"],)) == 1, "the receipt was lost"
        assert _one(db, """
            SELECT count(*) FROM information_schema.columns c
             WHERE c.table_schema = 'public' AND c.table_name = 'v2_sessions'
               AND c.is_nullable = 'YES'
               AND c.column_name NOT IN (
                   'id', 'arc_id', 'owner_principal_id', 'user_id',
                   'project_id', 'take_index', 'canonical_take_index',
                   'recording_kind', 'analysis_state', 'paired_session_id',
                   'created_at', 'updated_at', 'completed_at')
               AND (SELECT to_jsonb(s) -> c.column_name
                      FROM public.v2_sessions s WHERE s.id = %s)
                   NOT IN ('null'::jsonb)""", (subject["take"],)) == 0, (
            "the take receipt still holds content")
        # N9: the project row is a tombstone. Retained recording-attempt
        # evidence points at it ON DELETE RESTRICT, so the row stays; what the
        # person wrote into it does not.
        row = _one(db, """
            SELECT jsonb_build_object(
                       'name', display_name, 'setup', setup,
                       'deck', presentation_ref,
                       'tombstoned', tombstoned_at IS NOT NULL)
              FROM public.projects WHERE id = %s""", (subject["project"],))
        assert row == {"name": "", "setup": {}, "deck": None,
                       "tombstoned": True}, row
        assert _one(db, """
            SELECT count(*) FROM public.processing_recording_attempts
             WHERE id = %s""", (subject["attempt"],)) == 1, (
            "the retained evidence was lost")

    def test_the_wipe_never_reaches_another_persons_project(self, db, fake_storage):
        """The tombstone function scrubs only projects in the request's frozen
        graph; a stranger's project with the same shape is untouched."""
        _production_columns(db)
        _seed_every_retention_rule(db)
        subject = _account_with_one_take(db)
        stranger = _account_with_one_take(db)

        DataPurgeOrchestrator(_Database(db)).run(subject["request"])

        assert _one(db, "SELECT display_name FROM public.projects WHERE id = %s",
                    (stranger["project"],)) == "Q3 pitch"

    def test_the_wipe_refuses_a_request_that_is_not_running(self, db):
        """Called outside a frozen, running erasure it wipes nothing."""
        subject = _account_with_one_take(db)
        with pytest.raises(Exception, match="PURGE_TOMBSTONE_REQUEST_NOT_IN_PROGRESS"):
            _one(db, "SELECT public.tombstone_phase1_purge_projects_v1(%s)",
                 (subject["request"],))
        assert _one(db, "SELECT display_name FROM public.projects WHERE id = %s",
                    (subject["project"],)) == "Q3 pitch"
