"""One project is erased; the account's other project is untouched (P1-B, 0380).

The founder's words (2026-09-26): "make the delete work". A person taps
Delete on one project row; an operator confirms it (N8); the purge must then
reach that project's takes, words and audio, and nothing else the person has.

This runs `ProjectPurgeOrchestrator.run` - the Python production runs - on
the released rehearsal lane, with the same two named stand-ins as
tests/test_take_purge_postgres.py: every retention rule seeded active, and
object storage faked.

  * the confirmed project reaches `done`; its words are gone, its row and
    take are kept as empty receipts (N9, N12) and its audio was deleted;
  * the same person's other project keeps its name, its take and its words;
  * the user's request is marked done by the finished purge, never before;
  * a project request can never be frozen as an account-wide purge.
"""
from __future__ import annotations

import uuid

import psycopg2
import psycopg2.extras
import pytest

from services.data_purge_project_scope import ProjectPurgeOrchestrator
from tests import test_account_deletion_starts_postgres as base
from tests import test_real_take_record_purge_postgres as record
from tests import test_take_purge_postgres as takes

DSN = base.DSN
_Database = base._Database
_one = base._one
db = base.db
fake_storage = takes.fake_storage

pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

KEPT = "Our second quarter doubled the pipeline."


def _production_columns(db) -> None:
    """As tests/test_take_purge_postgres.py's, plus the one this lane's stub
    `paragraphs` (id, owner_principal_id) lacks and production's canonical
    table has NOT NULL: `project_id`, which a project purge counts by.
    Additive, and only in this database."""
    takes._production_columns(db)
    with db.cursor() as cur:
        cur.execute("""
            ALTER TABLE public.paragraphs
                ADD COLUMN IF NOT EXISTS project_id UUID""")


def _second_project(db, subject: dict) -> dict:
    """The same person's other project, with a take and its words."""
    principal = subject["principal"]
    user_id = _one(db, "SELECT user_id FROM public.owner_principals WHERE id = %s",
                   (principal,))
    project = _one(db, """
        INSERT INTO public.projects (id, owner_principal_id, display_name)
        VALUES (gen_random_uuid(), %s, 'Board update') RETURNING id""",
        (principal,))
    take = _one(db, """
        INSERT INTO public.v2_sessions (
            id, user_id, owner_principal_id, project_id, arc_id, take_index)
        VALUES (gen_random_uuid(), %s, %s, %s, %s, 1) RETURNING id""",
        (user_id, principal, project, project))
    other = {"principal": principal, "project": str(project), "take": str(take)}
    return record._with_permanent_record(db, other)


def _confirmed_project_deletion(db, subject: dict) -> tuple[str, str]:
    request = _one(db, """
        INSERT INTO public.project_deletion_requests (
            acquisition_principal_id, project_id, due_at, idempotency_key)
        VALUES (%s, %s, now() + interval '7 days', %s) RETURNING id""",
        (subject["principal"], subject["project"], str(uuid.uuid4())))
    purge = _one(db, """
        SELECT (public.confirm_project_deletion_v1(%s, gen_random_uuid()))
               .purge_request_id""", (request,))
    return str(request), str(purge)


def _words(db, project: str) -> int:
    return _one(db, """
        SELECT count(*) FROM public.transcript_versions
         WHERE project_id = %s AND transcript_text NOT IN ('[erased]', '')""",
        (project,))


class TestOneProjectIsErased:

    def test_the_project_reaches_done_and_the_other_is_untouched(
            self, db, fake_storage):
        _production_columns(db)
        takes._seed_every_retention_rule(db)
        erased = record._with_permanent_record(
            db, takes._account_with_one_take(db))
        kept = _second_project(db, erased)
        request, purge = _confirmed_project_deletion(db, erased)

        outcome = ProjectPurgeOrchestrator(_Database(db)).run(purge)

        assert takes._left_for_review(db, purge) == []
        assert _one(db, "SELECT state FROM public.data_purge_requests WHERE id = %s",
                    (purge,)) == "done"
        assert _one(db, """
            SELECT state FROM public.project_deletion_requests WHERE id = %s""",
            (request,)) == "done"
        assert outcome["project_deletion"]["state"] == "done"
        # The erased project: words gone, receipts kept, audio deleted.
        assert _words(db, erased["project"]) == 0
        assert record._words_left(db, erased) == []
        assert _one(db, """
            SELECT display_name = '' AND tombstoned_at IS NOT NULL
              FROM public.projects WHERE id = %s""", (erased["project"],))
        assert _one(db, "SELECT count(*) FROM public.takes WHERE id = %s",
                    (erased["take"],)) == 1
        assert ("take-audio", f"{erased['principal']}/{erased['take']}.wav") \
            in fake_storage
        # The other project: exactly as it was.
        assert _one(db, """
            SELECT display_name FROM public.projects WHERE id = %s""",
            (kept["project"],)) == "Board update"
        assert _one(db, "SELECT tombstoned_at FROM public.projects WHERE id = %s",
                    (kept["project"],)) is None
        assert _words(db, kept["project"]) == 1
        assert len(record._words_left(db, kept)) == 3
        # The person stays: identity and agreement are not the project's.
        assert _one(db, "SELECT count(*) FROM public.owner_principals WHERE id = %s",
                    (erased["principal"],)) == 1
        assert _one(db, """
            SELECT count(*) FROM public.processing_authorization_receipts
             WHERE acquisition_principal_id = %s""", (erased["principal"],)) == 1

    def test_the_request_is_not_done_before_the_purge_is(self, db):
        subject = takes._account_with_one_take(db)
        _request, purge = _confirmed_project_deletion(db, subject)
        with pytest.raises(psycopg2.Error, match="PROJECT_PURGE_NOT_DONE"):
            _one(db, "SELECT public.complete_project_deletion_v1(%s)", (purge,))

    def test_someone_elses_project_cannot_be_confirmed(self, db):
        owner = takes._account_with_one_take(db)
        stranger = takes._account_with_one_take(db)
        request = _one(db, """
            INSERT INTO public.project_deletion_requests (
                acquisition_principal_id, project_id, due_at, idempotency_key)
            VALUES (%s, %s, now() + interval '7 days', %s) RETURNING id""",
            (stranger["principal"], owner["project"], str(uuid.uuid4())))
        with pytest.raises(psycopg2.Error, match="PURGE_PROJECT_NOT_OWNED"):
            _one(db, "SELECT public.confirm_project_deletion_v1(%s, gen_random_uuid())",
                 (request,))

    def test_a_project_request_is_never_frozen_account_wide(self, db):
        subject = takes._account_with_one_take(db)
        _request, purge = _confirmed_project_deletion(db, subject)
        graph = _one(db, "SELECT public.resolve_phase1_purge_subject_graph_v3(%s)",
                     (subject["principal"],))
        with pytest.raises(psycopg2.Error, match="PURGE_MANIFEST_SCOPE_MISMATCH"):
            _one(db, """
                SELECT public.freeze_phase1_purge_inventory_v4(
                    %s, 'phase1-purge-resolver-v4', repeat('a', 64), %s::jsonb,
                    '[{"target_kind": "unknown", "target_ref": "probe"}]'::jsonb,
                    repeat('b', 64), '{}'::text[])""",
                (purge, psycopg2.extras.Json(graph)))
