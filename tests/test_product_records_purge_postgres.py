"""
STORY    As a speaker deleting my account or a project, I want what the Take
         showed me, my answers and every Paragraph version deleted while job
         evidence is kept, so that my erasure finishes and keeps only what
         the law needs (deletion).
OUTCOME
  O1  Without the v1.4 rules the erasure stops for review on these records
      and deletes nothing (fail closed, as before v1.4).
  O2  With the rules, seeded by scripts/phase1_retention_rules_v1_4.sql as
      the founder runs it, the account erasure reaches done: those records
      are deleted under product-records-v1, the job and its events are kept
      under job-evidence-v1, and a stranger's records are untouched.
  O3  A project erasure deletes that project's records and keeps the other
      project's.
  O4  Outside a running purge, the append-only trigger (0424) still refuses
      a direct delete, even with the rules active.
PROVES   O1 -> test_without_the_rules_the_erasure_stops_and_deletes_nothing
         O2 -> test_the_account_erasure_deletes_the_product_records_and_keeps_the_job
         O3 -> test_a_project_erasure_deletes_only_that_projects_records
         O4 -> test_outside_a_purge_the_trigger_refuses_a_delete
WHY      N14.3: these four tables stopped every erasure; founder 2026-10-05,
         decisions log N48.4 Q15 A (retention schedule v1.4).

Runs the Python production runs (DataPurgeOrchestrator.run,
ProjectPurgeOrchestrator.run) through the SQL client of
tests/test_account_deletion_starts_postgres.py, as service_role, on the
released rehearsal lane. Object storage is faked
(tests/test_take_purge_postgres.py). The lane never applied 0293, so the two
Take tables, the three immutable triggers and production's service_role
grants are laid down here as those files write them. The lane's ACCOUNT graph
lists no job, so job events are proved through the PROJECT graph (0380). The
job plumbing (0425: outbox, carry-over, orphan metadata) is not covered here.
"""
from __future__ import annotations

import pathlib
import uuid

import psycopg2
import pytest

from services.data_purge import DataPurgeOrchestrator
from services.data_purge_project_scope import ProjectPurgeOrchestrator
from tests import test_account_deletion_starts_postgres as base
from tests import test_project_purge_postgres as projects
from tests import test_take_purge_postgres as takes

DSN = base.DSN
_Database = base._Database
_one = base._one
db = base.db
fake_storage = takes.fake_storage

pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "scripts" / "phase1_retention_rules_v1_4.sql").read_text()
V1_4_RULES = ("product-records-v1", "job-evidence-v1")
THE_THREE = {"feedback_exposure", "feedback_self_report",
             "ideal_part_revision"}


def _production_shape(db) -> None:
    """What production has and this lane lacks: 0293's two Take tables and
    the three tables' immutable triggers, and the service_role grants 0293
    and 0336 give. Additive, and only in this disposable database."""
    with db.cursor() as cur:
        # The corpus stand-in tests/test_bundled_era_erasure_postgres.py lays
        # down earlier in the lane; here too, so this module runs on its own.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.training_labels (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                audio_path TEXT, label_key TEXT)""")
    takes._production_columns(db)
    with db.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.take_feedback_exposure (
                arc_id TEXT NOT NULL,
                take_session_id UUID NOT NULL
                    REFERENCES public.v2_sessions(id) ON DELETE CASCADE,
                review_version INTEGER NOT NULL CHECK (review_version >= 1),
                policy_version TEXT NOT NULL,
                model_version TEXT NULL,
                prompt_version TEXT NULL,
                candidate_set JSONB NOT NULL
                    CHECK (jsonb_typeof(candidate_set) = 'array'),
                selected_keys JSONB NOT NULL CHECK (
                    jsonb_typeof(selected_keys) = 'array'
                    AND jsonb_array_length(selected_keys) = 3),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (arc_id, take_session_id));
            CREATE TABLE IF NOT EXISTS public.take_feedback_self_report (
                id BIGSERIAL PRIMARY KEY,
                arc_id TEXT NOT NULL,
                take_session_id UUID NOT NULL
                    REFERENCES public.v2_sessions(id) ON DELETE CASCADE,
                owner_user_id UUID NOT NULL,
                feedback_id TEXT NOT NULL,
                feedback_family TEXT NOT NULL,
                snippet_id UUID NULL,
                response TEXT NOT NULL,
                provenance TEXT NOT NULL DEFAULT 'user_self_report',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (take_session_id, owner_user_id, feedback_id));
            ALTER TABLE public.take_feedback_exposure ENABLE ROW LEVEL SECURITY;
            ALTER TABLE public.take_feedback_self_report ENABLE ROW LEVEL SECURITY;
            DROP TRIGGER IF EXISTS take_feedback_exposure_immutable
                ON public.take_feedback_exposure;
            CREATE TRIGGER take_feedback_exposure_immutable
                BEFORE UPDATE OR DELETE ON public.take_feedback_exposure
                FOR EACH ROW EXECUTE FUNCTION
                    public.reject_immutable_feedback_mutation();
            DROP TRIGGER IF EXISTS take_feedback_self_report_immutable
                ON public.take_feedback_self_report;
            CREATE TRIGGER take_feedback_self_report_immutable
                BEFORE UPDATE OR DELETE ON public.take_feedback_self_report
                FOR EACH ROW EXECUTE FUNCTION
                    public.reject_immutable_feedback_mutation();
            DROP TRIGGER IF EXISTS ideal_text_part_revision_immutable
                ON public.ideal_text_part_revision;
            CREATE TRIGGER ideal_text_part_revision_immutable
                BEFORE UPDATE OR DELETE ON public.ideal_text_part_revision
                FOR EACH ROW EXECUTE FUNCTION
                    public.reject_immutable_feedback_mutation();
            GRANT ALL ON TABLE public.take_feedback_exposure TO service_role;
            GRANT ALL ON TABLE public.take_feedback_self_report TO service_role;
            -- 0293 granted ALL, 0327 took the writes back, 0336 restored
            -- them: SELECT, INSERT, UPDATE and DELETE are what production
            -- holds on the revision table.
            GRANT SELECT, INSERT, UPDATE, DELETE
                ON TABLE public.ideal_text_part_revision TO service_role;
            GRANT USAGE, SELECT
                ON SEQUENCE public.take_feedback_self_report_id_seq
                TO service_role""")


def _v1_4_registered(db) -> None:
    """The founder's step, exactly as he runs it: the script, its signed
    hash in, nothing replaced."""
    assert "[[" not in SCRIPT.split("BEGIN", 1)[0].split("DECLARE", 1)[1], (
        "the script still carries a placeholder")
    with db.cursor() as cur:
        cur.execute(SCRIPT)
        # A disposable lane may already hold the two rows from an earlier
        # case, withdrawn by its teardown; the script never re-activates a
        # row it finds (ON CONFLICT DO NOTHING), so the case does.
        cur.execute("""
            UPDATE public.data_retention_rules SET active = true
             WHERE rule_code = ANY(%s)""", (list(V1_4_RULES),))


@pytest.fixture
def no_v1_4_rules(db):
    """Every rule but v1.4's active; v1.4's withdrawn before and after."""
    def withdraw():
        with db.cursor() as cur:
            cur.execute("""
                UPDATE public.data_retention_rules SET active = false
                 WHERE rule_code = ANY(%s)""", (list(V1_4_RULES),))
    withdraw()
    yield
    withdraw()


def _records(db, subject: dict) -> dict:
    """What a Take showed, the speaker's answers, two versions of a
    Paragraph (the second naming the first, as 0327's chain does), and the
    processing job with its events: the four tables of N14.3."""
    user_id = _one(db, "SELECT user_id FROM public.owner_principals WHERE id = %s",
                   (subject["principal"],))
    project, take = subject["project"], subject["take"]
    with db.cursor() as cur:
        cur.execute("""
            INSERT INTO public.take_feedback_exposure (
                arc_id, take_session_id, review_version, policy_version,
                candidate_set, selected_keys)
            VALUES (%s, %s, 1, 'take-feedback-policy-v3', '[]'::jsonb,
                    '[{"k":1},{"k":2},{"k":3}]'::jsonb)""", (project, take))
        cur.execute("""
            INSERT INTO public.take_feedback_self_report (
                arc_id, take_session_id, owner_user_id, feedback_id,
                feedback_family, response)
            VALUES (%s, %s, %s, 'item-1', 'confident_voice', 'yes'),
                   (%s, %s, %s, 'item-2', 'rewrite_clarity', 'keep_wording')""",
                    (project, take, user_id, project, take, user_id))
        part = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO public.ideal_text_part_revision (
                arc_id, user_id, part_id, action, text)
            VALUES (%s, %s, %s, 'user_edit', 'Our pipeline doubled.')
            RETURNING id""", (project, str(user_id), part))
        first = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO public.ideal_text_part_revision (
                arc_id, user_id, part_id, action, text, previous_revision_id)
            VALUES (%s, %s, %s, 'lock', 'Our pipeline doubled.', %s)""",
                    (project, str(user_id), part, first))
        cur.execute("""
            INSERT INTO public.phase1_processing_jobs (
                acquisition_principal_id, recording_attempt_id,
                authorization_snapshot_id, job_kind, status)
            SELECT attempt.acquisition_principal_id, attempt.id,
                   attempt.authorization_snapshot_id,
                   'recording_transcription_ranking_feedback', 'completed'
              FROM public.processing_recording_attempts attempt
             WHERE attempt.id = %s
            RETURNING id""", (subject["attempt"],))
        job = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO public.phase1_processing_job_events (
                processing_job_id, status, attempts)
            VALUES (%s, 'processing', 1), (%s, 'completed', 1)""", (job, job))
    return {**subject, "job": str(job), "part": part}


def _phase1_attempt(db, principal: str, project: str) -> str:
    """Another accepted recording attempt of the same person, in another
    project, made as tests/test_take_purge_postgres.py makes the first."""
    receipt, policy = _one(db, """
        SELECT ARRAY[id::text, policy_id::text]
          FROM public.processing_authorization_receipts
         WHERE acquisition_principal_id = %s LIMIT 1""", (principal,))
    attempt = str(uuid.uuid4())
    snapshot = _one(db, """
        INSERT INTO public.processing_authorization_snapshots (
            id, acquisition_principal_id, receipt_id, policy_id, purpose_id,
            operation_kind, source_recording_id, authority_evidence_sha256)
        VALUES (gen_random_uuid(), %s, %s, %s, 'recording_voice_processing',
                'recording_upload', %s, repeat('6', 64))
        RETURNING id""", (principal, receipt, policy, attempt))
    _one(db, """
        INSERT INTO public.processing_recording_attempts (
            id, acquisition_principal_id, project_id, recording_id,
            upload_idempotency_key, authorization_snapshot_id)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (attempt, principal, project, attempt, str(uuid.uuid4()), snapshot))
    return attempt


def _rows(db, records: dict) -> dict:
    project, take = records["project"], records["take"]
    return {
        "shown": _one(db, """SELECT count(*) FROM public.take_feedback_exposure
                              WHERE take_session_id = %s""", (take,)),
        "answers": _one(db, """SELECT count(*) FROM public.take_feedback_self_report
                                WHERE take_session_id = %s""", (take,)),
        "versions": _one(db, """SELECT count(*) FROM public.ideal_text_part_revision
                                 WHERE arc_id = %s""", (project,)),
        "job": _one(db, """SELECT count(*) FROM public.phase1_processing_jobs
                            WHERE id = %s""", (records["job"],)),
        "events": _one(db, """SELECT count(*) FROM public.phase1_processing_job_events
                               WHERE processing_job_id = %s""", (records["job"],)),
    }


def _target(db, request: str, code: str) -> dict:
    return _one(db, """
        SELECT jsonb_build_object(
                   'state', target.state,
                   'reason', target.metadata->>'reason_code',
                   'disposition', target.metadata->>'disposition',
                   'rule', rule.rule_code)
          FROM public.data_purge_targets target
          LEFT JOIN public.data_retention_rules rule
            ON rule.id = target.retention_rule_id
         WHERE target.purge_request_id = %s
           AND target.target_ref = %s""", (request, f"dependency:{code}"))


class TestWithoutTheRulesTheErasureStops:

    @pytest.fixture(autouse=True)
    def _rules(self, db, no_v1_4_rules):
        _production_shape(db)
        takes._seed_every_retention_rule(db)

    def test_without_the_rules_the_erasure_stops_and_deletes_nothing(
            self, db, fake_storage):
        records = _records(db, takes._account_with_one_take(db))

        DataPurgeOrchestrator(_Database(db)).run(records["request"])

        assert _one(db, "SELECT state FROM public.data_purge_requests WHERE id = %s",
                    (records["request"],)) != "done"
        stopped = {item["ref"] for item in takes._left_for_review(db, records["request"])
                   if item["reason"] == "EXPLICIT_RESOLVER_REQUIRED"}
        assert {f"dependency:{code}" for code in THE_THREE} <= stopped
        assert _rows(db, records) == {
            "shown": 1, "answers": 2, "versions": 2, "job": 1, "events": 2}


class TestWithTheSignedRulesTheErasureFinishes:

    @pytest.fixture(autouse=True)
    def _rules(self, db, no_v1_4_rules):
        _production_shape(db)
        takes._seed_every_retention_rule(db)
        _v1_4_registered(db)

    def test_the_account_erasure_deletes_the_product_records_and_keeps_the_job(
            self, db, fake_storage):
        records = _records(db, takes._account_with_one_take(db))
        stranger = _records(db, takes._account_with_one_take(db))

        DataPurgeOrchestrator(_Database(db)).run(records["request"])

        assert takes._left_for_review(db, records["request"]) == []
        assert _one(db, "SELECT state FROM public.data_purge_requests WHERE id = %s",
                    (records["request"],)) == "done"
        assert _rows(db, records) == {
            "shown": 0, "answers": 0, "versions": 0, "job": 1, "events": 2}
        for code in ("feedback_exposure", "feedback_self_report",
                     "ideal_part_revision"):
            assert _target(db, records["request"], code) == {
                "state": "deleted", "reason": None, "disposition": "delete",
                "rule": "product-records-v1"}, code
        assert _target(db, records["request"], "phase1_jobs") == {
            "state": "retained", "reason": None, "disposition": "retain",
            "rule": "job-evidence-v1"}
        # The stranger's records were never reached.
        assert _rows(db, stranger) == {
            "shown": 1, "answers": 2, "versions": 2, "job": 1, "events": 2}


    def test_a_project_erasure_deletes_only_that_projects_records(
            self, db, fake_storage):
        projects._production_columns(db)
        erased = _records(db, takes._account_with_one_take(db))
        kept = projects._second_project(db, erased)
        kept = _records(db, {**kept, "attempt": _phase1_attempt(
            db, erased["principal"], kept["project"])})
        _request, purge = projects._confirmed_project_deletion(db, erased)

        ProjectPurgeOrchestrator(_Database(db)).run(purge)

        assert takes._left_for_review(db, purge) == []
        assert _one(db, "SELECT state FROM public.data_purge_requests WHERE id = %s",
                    (purge,)) == "done"
        assert _rows(db, erased) == {
            "shown": 0, "answers": 0, "versions": 0, "job": 1, "events": 2}
        for code in THE_THREE:
            assert _target(db, purge, code)["rule"] == "product-records-v1", code
        for code in ("phase1_job_events", "phase1_jobs"):
            assert _target(db, purge, code) == {
                "state": "retained", "reason": None, "disposition": "retain",
                "rule": "job-evidence-v1"}, code
        assert _rows(db, kept) == {
            "shown": 1, "answers": 2, "versions": 2, "job": 1, "events": 2}

    def test_outside_a_purge_the_trigger_refuses_a_delete(self, db):
        records = _records(db, takes._account_with_one_take(db))
        for table in ("take_feedback_exposure", "take_feedback_self_report"):
            with pytest.raises(psycopg2.Error) as refused:
                _one(db, f"DELETE FROM public.{table} WHERE take_session_id = %s "
                         "RETURNING 1", (records["take"],))
            assert "immutable feedback evidence" in str(refused.value)
        assert _rows(db, records)["shown"] == 1
