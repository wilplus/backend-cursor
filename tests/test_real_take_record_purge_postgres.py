"""An account whose take has its permanent record can be erased (founder N12).

tests/test_take_purge_postgres.py proved an erasure reaches `done` for an
account with one recorded take, but its take never wrote the permanent record
every real upload writes: the recording attempt (`recording_attempts`), the
take (`takes`), the processing transitions, and the canonical transcript and
evidence built on it. Those tables refuse any UPDATE or DELETE, and they point
at the take session and the project ON DELETE RESTRICT. So in production no
deletion could finish for anyone who had recorded.

Founder decision N12 (2026-09-26), "keep an empty receipt": the record stays
as identifiers and timestamps; every word, every piece of feedback and all
audio is erased. This case writes that record the way the live writers do and
runs the real orchestrator (as tests/test_take_purge_postgres.py does, with
the same two named stand-ins: every retention rule seeded active, and object
storage faked).
"""
from __future__ import annotations

import uuid

import pytest

from services.data_purge import DataPurgeOrchestrator
from tests import test_account_deletion_starts_postgres as base
from tests import test_take_purge_postgres as takes

DSN = base.DSN
_Database = base._Database
_one = base._one
db = base.db
fake_storage = takes.fake_storage

pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

SAID = "We cut churn by a third in one quarter."


def _with_permanent_record(db, subject: dict) -> dict:
    """The take's permanent record, as the live writers leave it."""
    principal, project, take = (
        subject["principal"], subject["project"], subject["take"])
    attempt = _one(db, """
        INSERT INTO public.recording_attempts (
            id, owner_principal_id, project_id, upload_idempotency_key,
            recording_kind, status, attempt_count, provenance_eligible,
            created_at, terminal_at, last_error)
        VALUES (%s, %s, %s, %s, 'spoken', 'succeeded', 1, true, now(), now(),
                '{"note": "slow upload"}'::jsonb)
        RETURNING id""", (take, principal, project, f"upload-{uuid.uuid4()}"))
    _one(db, """
        INSERT INTO public.takes (
            id, recording_attempt_id, owner_principal_id, project_id,
            take_index, completion_hash, completed_at)
        VALUES (%s, %s, %s, %s, 1, repeat('c', 64), now()) RETURNING id""",
        (take, attempt, principal, project))
    version = _one(db, """
        INSERT INTO public.transcript_versions (
            id, owner_principal_id, project_id, take_id, version, source_kind,
            transcript_text, transcript_hash, input_hash, model_version,
            prompt_version, code_commit)
        VALUES (gen_random_uuid(), %s, %s, %s, 1, 'automatic', %s, repeat('d', 64),
                repeat('e', 64), 'asr-v1', 'p-v1', 'c-v1')
        RETURNING id""", (principal, project, take, SAID))
    _one(db, """
        INSERT INTO public.slides (
            id, owner_principal_id, project_id, take_id,
            transcript_version_id, slide_index, title, source_payload)
        VALUES (gen_random_uuid(), %s, %s, %s, %s, 0, 'Churn',
                '{"words": "We cut churn"}'::jsonb)
        RETURNING id""", (principal, project, take, version))
    # paragraphs is left out: the rehearsal lane's paragraphs table predates
    # the canonical one (different shape). The wipe skips what a database
    # lacks; production's paragraph_text is in its list.
    return {**subject, "record_attempt": str(attempt),
            "transcript_version": str(version)}


def _words_left(db, subject: dict) -> list[str]:
    """Every place the take's words could still be read."""
    return _one(db, """
        SELECT coalesce(jsonb_agg(src), '[]'::jsonb) FROM (
            SELECT 'transcript_versions' AS src FROM public.transcript_versions
             WHERE take_id = %(take)s AND transcript_text LIKE '%%churn%%'
            UNION ALL
            SELECT 'slides' FROM public.slides
             WHERE take_id = %(take)s
               AND (coalesce(title, '') LIKE '%%Churn%%'
                    OR source_payload::text LIKE '%%churn%%')
            UNION ALL
            SELECT 'recording_attempts' FROM public.recording_attempts
             WHERE id = %(take)s AND last_error::text LIKE '%%slow%%'
        ) found""", {"take": subject["take"]})


class TestAnAccountWithAPermanentTakeRecordCanBeErased:

    def test_the_erasure_reaches_done_and_keeps_only_an_empty_receipt(
            self, db, fake_storage):
        takes._production_columns(db)
        takes._seed_every_retention_rule(db)
        subject = _with_permanent_record(db, takes._account_with_one_take(db))

        DataPurgeOrchestrator(_Database(db)).run(subject["request"])

        assert takes._left_for_review(db, subject["request"]) == []
        assert _one(db, "SELECT state FROM public.data_purge_requests WHERE id = %s",
                    (subject["request"],)) == "done"
        assert _words_left(db, subject) == []
        # The receipt: the take and its attempt still exist, as ids and times.
        assert _one(db, "SELECT count(*) FROM public.takes WHERE id = %s",
                    (subject["take"],)) == 1
        assert _one(db, """
            SELECT count(*) FROM public.transcript_versions WHERE take_id = %s""",
            (subject["take"],)) == 1

    def test_a_strangers_record_is_untouched(self, db, fake_storage):
        takes._production_columns(db)
        takes._seed_every_retention_rule(db)
        subject = _with_permanent_record(db, takes._account_with_one_take(db))
        stranger = _with_permanent_record(db, takes._account_with_one_take(db))

        DataPurgeOrchestrator(_Database(db)).run(subject["request"])

        assert len(_words_left(db, stranger)) == 3

    def test_the_record_still_refuses_any_other_change(self, db):
        subject = _with_permanent_record(db, takes._account_with_one_take(db))
        with pytest.raises(Exception, match="append-only"):
            _one(db, """
                UPDATE public.transcript_versions SET transcript_text = '[erased]'
                 WHERE take_id = %s RETURNING id""", (subject["take"],))
