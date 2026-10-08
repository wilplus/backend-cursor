"""A speaker's skip keeps an empty receipt, on the released lane (0448; founder
N12; decision tree 2026-10-08, Q3 YES and Q4 YES: "empty receipt").

WHAT WAS BROKEN. record_root_phrase_skip_v1 writes a feedback_revisions row
(rater_role 'owner', rater_id the speaker's user id) under the evidence span
of the speaker's lock decision. 0379's lineage wipe empties
feedback_revisions.revision_payload as a child of that span, but since 0327
the table's guard (reject_confident_moment_mutation_v1) refused every UPDATE,
so the wipe raised and rolled back and the erasure could not finish.

Pins:
  * feedback_revisions has its own guard; every other 0327 table keeps the
    shared one, whose body still only raises;
  * an account erasure, and a project erasure, with a real skip (written through
    record_paragraph_decision_v1 + record_root_phrase_skip_v1) reaches
    `done`: the skip row stays, its payload is '{}', and the wipe reports
    not_blank 0;
  * outside a running purge, UPDATE and DELETE still raise
    CONFIDENT_MOMENT_APPEND_ONLY, and inside one any change but emptying the
    payload still raises;
  * fail closed: a coach row under an erased span makes the wipe raise, and
    an owner row of the person that hangs off a span outside the wipe's scope
    is reported not blank, never passed as retained.

This lane's `paragraphs` is a two-column MLC-2 fixture stub, and its
`evidence_spans` lacks four of 0296's columns. They are added here, in the
disposable database only, as 0296 defines them (nullable where 0296 is NOT
NULL, because earlier suites' rows are already in these tables).
"""
from __future__ import annotations

import uuid

import psycopg2
import pytest

from services.data_purge import DataPurgeOrchestrator
from services.data_purge_project_scope import ProjectPurgeOrchestrator
from tests import test_account_deletion_starts_postgres as base
from tests import test_project_purge_postgres as projects
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

SAID = "We cut churn by a third in one quarter."
TAXONOMY = "paragraph-versioning-v1"


def _canonical_shapes(db) -> None:
    """0296's paragraphs and evidence_spans columns this lane lacks."""
    takes._production_columns(db)
    with db.cursor() as cur:
        cur.execute("""
            ALTER TABLE public.paragraphs
                ADD COLUMN IF NOT EXISTS project_id UUID,
                ADD COLUMN IF NOT EXISTS take_id UUID,
                ADD COLUMN IF NOT EXISTS transcript_version_id UUID,
                ADD COLUMN IF NOT EXISTS slide_id UUID,
                ADD COLUMN IF NOT EXISTS paragraph_index INTEGER,
                ADD COLUMN IF NOT EXISTS source_ideal_part_id UUID,
                ADD COLUMN IF NOT EXISTS paragraph_text TEXT,
                ADD COLUMN IF NOT EXISTS start_char INTEGER,
                ADD COLUMN IF NOT EXISTS end_char INTEGER,
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ
                    NOT NULL DEFAULT now();
            ALTER TABLE public.evidence_spans
                ADD COLUMN IF NOT EXISTS transcript_version_id UUID,
                ADD COLUMN IF NOT EXISTS slide_id UUID,
                ADD COLUMN IF NOT EXISTS paragraph_id UUID,
                ADD COLUMN IF NOT EXISTS target_locator JSONB
                    NOT NULL DEFAULT '{}'::jsonb""")


def _account_with_a_skip(db) -> dict:
    """One account, one take with its permanent record, one Paragraph the
    speaker locked and then skipped helper words for - the live writers."""
    subject = record._with_permanent_record(db, takes._account_with_one_take(db))
    return _a_skip(db, subject)


def _a_skip(db, subject: dict) -> dict:
    user_id = str(_one(db, "SELECT user_id FROM public.owner_principals WHERE id = %s",
                       (subject["principal"],)))
    slide = _one(db, "SELECT id FROM public.slides WHERE take_id = %s",
                 (subject["take"],))
    part = str(uuid.uuid4())
    _one(db, """
        INSERT INTO public.paragraphs (
            id, owner_principal_id, project_id, take_id, transcript_version_id,
            slide_id, paragraph_index, source_ideal_part_id, paragraph_text,
            start_char, end_char)
        VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, 0, %s, %s, 0, %s)
        RETURNING id""",
        (subject["principal"], subject["project"], subject["take"],
         subject["transcript_version"], slide, part, SAID, len(SAID)))
    decision = _one(db, """
        SELECT public.record_paragraph_decision_v1(
            %s, %s, %s, %s, %s, 'lock_for_next_take', %s, gen_random_uuid(),
            %s, repeat('a', 64), %s)""",
        (subject["project"], subject["take"], user_id, part, SAID, TAXONOMY,
         f"evidence-{uuid.uuid4()}", f"decision-{uuid.uuid4()}"))
    skip = _one(db, """
        SELECT public.record_root_phrase_skip_v1(%s, %s, %s, %s, %s, %s)""",
        (subject["project"], subject["take"], user_id, part, TAXONOMY,
         f"skip-{uuid.uuid4()}"))
    span = _one(db, """
        SELECT evidence_span_id FROM public.feedback_revisions WHERE id = %s""",
        (skip["feedback_revision_id"],))
    return {**subject, "user": user_id,
            "decision": decision["paragraph_decision_id"],
            "skip": str(skip["feedback_revision_id"]), "span": str(span)}


def _payload(db, revision: str):
    return _one(db, "SELECT revision_payload FROM public.feedback_revisions "
                    "WHERE id = %s", (revision,))


def _frozen(db, subject: dict) -> None:
    """The real freeze: the request is `in_progress` with a sealed manifest."""
    DataPurgeOrchestrator(_Database(db)).freeze_inventory(subject["request"])
    assert _one(db, "SELECT state FROM public.data_purge_requests WHERE id = %s",
                (subject["request"],)) == "in_progress"


def _wipe(db, request: str) -> dict:
    return _one(db, "SELECT public.tombstone_phase1_purge_lineage_v1(%s)",
                (request,))


class TestTheGuard:

    def test_feedback_revisions_has_its_own_guard_and_the_others_keep_theirs(
            self, db):
        assert _one(db, """
            SELECT tgfoid::regproc::text FROM pg_trigger
             WHERE tgrelid = 'public.feedback_revisions'::regclass
               AND tgname = 'feedback_revisions_append_only'
               AND NOT tgisinternal AND tgenabled IN ('O', 'A')""") == (
            "reject_feedback_revision_mutation_v1")
        # The shared 0327 guard is untouched and still guards its tables.
        assert "RAISE EXCEPTION 'CONFIDENT_MOMENT_APPEND_ONLY'" in _one(db, """
            SELECT prosrc FROM pg_proc
             WHERE proname = 'reject_confident_moment_mutation_v1'""")
        assert "purge_wipe_request_id" not in _one(db, """
            SELECT prosrc FROM pg_proc
             WHERE proname = 'reject_confident_moment_mutation_v1'""")
        assert _one(db, """
            SELECT count(*) FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
             WHERE p.proname = 'reject_confident_moment_mutation_v1'
               AND NOT t.tgisinternal""") > 0

    def test_outside_a_purge_the_skip_still_refuses_any_change(self, db):
        _canonical_shapes(db)
        subject = _account_with_a_skip(db)
        for statement in (
                "UPDATE public.feedback_revisions SET revision_payload = '{}' "
                "WHERE id = %s RETURNING id",
                "UPDATE public.feedback_revisions SET value = 'x' "
                "WHERE id = %s RETURNING id",
                "DELETE FROM public.feedback_revisions WHERE id = %s RETURNING id"):
            with pytest.raises(psycopg2.Error, match="CONFIDENT_MOMENT_APPEND_ONLY"):
                _one(db, statement, (subject["skip"],))
        assert _payload(db, subject["skip"]) != {}

    def test_inside_a_running_purge_only_emptying_the_payload_passes(self, db):
        _canonical_shapes(db)
        takes._seed_every_retention_rule(db)
        subject = _account_with_a_skip(db)
        _frozen(db, subject)
        with db.cursor() as cur:
            cur.execute("BEGIN")
            try:
                cur.execute("SELECT set_config('willab.purge_wipe_request_id', %s, true)",
                            (subject["request"],))
                for change in ("value = 'x'",
                               "revision_payload = '{\"a\": 1}'::jsonb",
                               "revision_payload = '{}', value = 'x'"):
                    cur.execute("SAVEPOINT s")
                    with pytest.raises(psycopg2.Error,
                                       match="CONFIDENT_MOMENT_APPEND_ONLY"):
                        cur.execute(
                            f"UPDATE public.feedback_revisions SET {change} "
                            "WHERE id = %s", (subject["skip"],))
                    cur.execute("ROLLBACK TO SAVEPOINT s")
                cur.execute("SAVEPOINT s")
                with pytest.raises(psycopg2.Error, match="CONFIDENT_MOMENT_APPEND_ONLY"):
                    cur.execute("DELETE FROM public.feedback_revisions WHERE id = %s",
                                (subject["skip"],))
                cur.execute("ROLLBACK TO SAVEPOINT s")
            finally:
                cur.execute("ROLLBACK")


class TestTheSkipIsAnEmptyReceipt:

    def test_the_wipe_empties_the_skip_and_reports_nothing_left(self, db):
        _canonical_shapes(db)
        takes._seed_every_retention_rule(db)
        subject = _account_with_a_skip(db)
        assert _payload(db, subject["skip"]) != {}
        _frozen(db, subject)

        outcome = _wipe(db, subject["request"])

        assert outcome["not_blank"] == 0, outcome
        assert _payload(db, subject["skip"]) == {}
        # The receipt: the row, its link and its label stay.
        assert _one(db, """
            SELECT jsonb_build_object('span', evidence_span_id::text,
                                      'value', value, 'role', rater_role)
              FROM public.feedback_revisions WHERE id = %s""",
            (subject["skip"],)) == {"span": subject["span"],
                                    "value": "root_phrase_skipped",
                                    "role": "owner"}
        # Idempotent: a second call finds nothing to do.
        assert _wipe(db, subject["request"]) == {"tombstoned": 0, "not_blank": 0}

    def test_the_account_erasure_reaches_done(self, db, fake_storage):
        """Before 0448 this ended `failed`: the wipe raised on the skip."""
        _canonical_shapes(db)
        takes._seed_every_retention_rule(db)
        subject = _account_with_a_skip(db)
        stranger = _account_with_a_skip(db)

        DataPurgeOrchestrator(_Database(db)).run(subject["request"])

        assert takes._left_for_review(db, subject["request"]) == []
        assert _one(db, "SELECT state FROM public.data_purge_requests WHERE id = %s",
                    (subject["request"],)) == "done"
        assert _one(db, """
            SELECT state FROM public.data_purge_targets
             WHERE purge_request_id = %s
               AND target_ref = 'dependency:feedback_revision_owner_raters'""",
            (subject["request"],)) == "retained"
        assert _payload(db, subject["skip"]) == {}
        assert _one(db, "SELECT paragraph_text FROM public.paragraphs "
                        "WHERE take_id = %s", (subject["take"],)) == "[erased]"
        # Someone else's skip is untouched.
        assert _payload(db, stranger["skip"]) != {}


    def test_a_project_erasure_reaches_done_and_keeps_the_other_projects_skip(
            self, db, fake_storage):
        """The project's skips go with its evidence spans; the same person's
        skip in another project is not the project's and stays as it was."""
        _canonical_shapes(db)
        takes._seed_every_retention_rule(db)
        subject = _account_with_a_skip(db)
        other = _a_skip(db, projects._second_project(db, subject))
        _request, purge = projects._confirmed_project_deletion(db, subject)

        ProjectPurgeOrchestrator(_Database(db)).run(purge)

        assert takes._left_for_review(db, purge) == []
        assert _one(db, "SELECT state FROM public.data_purge_requests WHERE id = %s",
                    (purge,)) == "done"
        assert _payload(db, subject["skip"]) == {}
        assert _payload(db, other["skip"]) != {}


class TestItFailsClosed:

    def test_a_coach_row_under_an_erased_span_makes_the_wipe_raise(self, db):
        _canonical_shapes(db)
        takes._seed_every_retention_rule(db)
        subject = _account_with_a_skip(db)
        coach = str(uuid.uuid4())
        _one(db, """
            INSERT INTO public.feedback_revisions (
                id, evidence_span_id, value, rater_role, rater_id,
                taxonomy_version, revision_payload, idempotency_key)
            VALUES (%s, %s, 'Say it slower.', 'coach', gen_random_uuid(),
                    'rehearsal-coach-v1', '{"output_kind": "comment"}', %s)
            RETURNING id""", (coach, subject["span"], f"coach-{uuid.uuid4()}"))
        _frozen(db, subject)

        with pytest.raises(psycopg2.Error, match="CONFIDENT_MOMENT_APPEND_ONLY"):
            _wipe(db, subject["request"])
        # Rolled back whole: the skip was not emptied either.
        assert _payload(db, subject["skip"]) != {}
        assert _payload(db, coach) == {"output_kind": "comment"}

    def test_an_owner_row_outside_the_scope_is_not_blank(self, db):
        _canonical_shapes(db)
        takes._seed_every_retention_rule(db)
        subject = _account_with_a_skip(db)
        stranger = _account_with_a_skip(db)
        # The person's own row under a span the wipe does not reach.
        _one(db, """
            INSERT INTO public.feedback_revisions (
                id, evidence_span_id, value, rater_role, rater_id,
                taxonomy_version, revision_payload, idempotency_key)
            VALUES (gen_random_uuid(), %s, 'root_phrase_skipped', 'owner', %s,
                    %s, '{"paragraph_id": "x"}', %s)
            RETURNING id""",
            (stranger["span"], subject["user"], TAXONOMY, f"stray-{uuid.uuid4()}"))
        _frozen(db, subject)

        outcome = _wipe(db, subject["request"])

        assert outcome["not_blank"] == 1, outcome
        assert _payload(db, subject["skip"]) == {}
        assert _payload(db, stranger["skip"]) != {}
