"""Retention schedule v1.4 on the real schema: the four tables that stopped
every erasure (N14.3) are decided, and the purge acts on them only once the
v1.4 rules are active (founder 2026-10-05, decisions log N48.4 Q15 A:
product records go with the account or the project; job evidence is kept 12
months).

These cases run the Python production runs (`DataPurgeOrchestrator.run`,
`ProjectPurgeOrchestrator.run`) through the SQL client of
tests/test_account_deletion_starts_postgres.py, as service_role, on the
released rehearsal lane:

  * WITHOUT the v1.4 rules: the erasure stops for review on exactly these
    rows (EXPLICIT_RESOLVER_REQUIRED), deletes nothing, and the append-only
    trigger still refuses a direct delete. Fail closed, as before v1.4;
  * WITH them, seeded by scripts/phase1_retention_rules_v1_4.sql itself, as
    the founder runs it (the signed hash in it): the account erasure reaches
    done; what the Take showed, the speaker's answers and every version of
    the Paragraph are deleted under product-records-v1; the job and its
    events are kept under job-evidence-v1;
  * a project erasure deletes that project's records and keeps the other
    project's; a stranger's rows are never reached, and outside a running
    purge the trigger refuses even with the rules active;
  * the job plumbing (0425): with the rules active the account erasure
    deletes the person's outbox row, carry-over and orphaned object's
    metadata, as the registry always listed them, and keeps the job and its
    events as job evidence; without them it stops for review exactly as on
    main, with the plumbing untouched.

Named stand-ins: object storage is faked (tests/test_take_purge_postgres.py).
The lane never applied 0293, so the two Take tables, the three immutable
triggers and production's service_role grants (0293, and 0336 for the
revision table) are laid down here exactly as those files write them. The
lane's ACCOUNT graph is a pre-0313 stand-in that lists no job
(tests/integration/mlc3_exercise_foundation_prerequisites.sql); production's
(0312) lists every job of the person. So job events are proved through the
PROJECT graph, which is the released one (0380) and lists the project's jobs,
and the job-plumbing cases lay production's job list over the stand-in for
their length (`production_job_list`), then put the stand-in back.
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
THE_FOUR = THE_THREE | {"phase1_job_events"}


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


@pytest.fixture
def production_job_list(db):
    """The account graph with production's job list (0312: every job whose
    principal is the person's) laid over the lane's stand-in, which lists
    none. The stand-in is renamed and wrapped, never rewritten, and put back
    after the case: the rest of the lane keeps the graph it was built on."""
    with db.cursor() as cur:
        cur.execute("""
            ALTER FUNCTION public.resolve_phase1_purge_subject_graph_v1(uuid)
                RENAME TO resolve_phase1_purge_subject_graph_v1_lane_stand_in""")
        cur.execute("""
            CREATE FUNCTION public.resolve_phase1_purge_subject_graph_v1(
                p_acquisition_principal_id UUID
            ) RETURNS JSONB LANGUAGE sql STABLE AS $$
            SELECT base.graph || jsonb_build_object('job_ids', COALESCE((
                       SELECT jsonb_agg(job.id::text ORDER BY job.id::text)
                         FROM public.phase1_processing_jobs job
                        WHERE job.acquisition_principal_id::text IN (
                              SELECT jsonb_array_elements_text(
                                         base.graph -> 'principal_ids'))),
                   '[]'::jsonb))
              FROM (SELECT public.resolve_phase1_purge_subject_graph_v1_lane_stand_in(
                               p_acquisition_principal_id) AS graph) base
            $$""")
    try:
        yield
    finally:
        with db.cursor() as cur:
            cur.execute("""
                DROP FUNCTION public.resolve_phase1_purge_subject_graph_v1(uuid)""")
            cur.execute("""
                ALTER FUNCTION
                    public.resolve_phase1_purge_subject_graph_v1_lane_stand_in(uuid)
                    RENAME TO resolve_phase1_purge_subject_graph_v1""")


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


def _plumbing(db, records: dict) -> dict:
    """The three rows 0425 lets the purge delete: the job's delivery row
    (intake writes one with every Phase-1 job, 0310), a carry-over of that job
    to a newer policy, and the metadata of an upload that never became a
    recording, its object still in storage."""
    principal, job = records["principal"], records["job"]
    outbox = _one(db, """
        INSERT INTO public.phase1_processing_outbox (
            processing_job_id, event_type, idempotency_key, payload)
        VALUES (%s, 'phase1_recording_ready', %s, '{}'::jsonb)
        RETURNING id""", (job, str(uuid.uuid4())))
    old_policy = _one(db, """
        SELECT policy_id FROM public.processing_authorization_receipts
         WHERE acquisition_principal_id = %s LIMIT 1""", (principal,))
    new_policy = _one(db, """
        INSERT INTO public.processing_policy_versions (
            id, version, status, terms_version, terms_copy, terms_copy_sha256,
            privacy_version, privacy_copy, privacy_copy_sha256,
            ai_notice_version, ai_notice_copy, ai_notice_copy_sha256,
            agreement_copy, agreement_copy_sha256, allowed_countries,
            created_by)
        VALUES (gen_random_uuid(), 'carry-over-' || gen_random_uuid(), 'draft',
                'terms-v2', 'terms', repeat('1', 64), 'privacy-v2', 'privacy',
                repeat('2', 64), 'ai-v2', 'ai', repeat('3', 64), 'agreement',
                repeat('4', 64), ARRAY['PL'], 'rehearsal')
        RETURNING id""")
    carryover = _one(db, """
        INSERT INTO public.processing_job_carryovers (
            acquisition_principal_id, old_policy_id, new_policy_id,
            processing_job_id, exact_operation, cutoff_at, expires_at)
        VALUES (%s, %s, %s, %s, 'recording_transcription_ranking_feedback',
                now(), now() + interval '1 day')
        RETURNING id""", (principal, old_policy, new_policy, job))
    key = f"{principal}/never-finalized.wav"
    orphan = _one(db, """
        INSERT INTO public.processing_orphan_objects (
            acquisition_principal_id, storage_provider, bucket, object_key,
            exact_bytes_sha256, reason_code, not_before)
        VALUES (%s, 'r2', 'take-audio', %s, repeat('8', 64),
                'upload_not_finalized', now())
        RETURNING id""", (principal, key))
    return {"outbox": str(outbox), "carryover": str(carryover),
            "orphan": str(orphan), "orphan_key": key}


def _plumbing_rows(db, plumbing: dict) -> dict:
    return {
        "outbox": _one(db, """SELECT count(*) FROM public.phase1_processing_outbox
                               WHERE id = %s""", (plumbing["outbox"],)),
        "carryover": _one(db, """SELECT count(*) FROM public.processing_job_carryovers
                                  WHERE id = %s""", (plumbing["carryover"],)),
        "orphan": _one(db, """SELECT count(*) FROM public.processing_orphan_objects
                               WHERE id = %s""", (plumbing["orphan"],)),
    }


#: The registry codes of the three tables 0425 opens.
THE_PLUMBING = ("phase1_outbox", "policy_carryovers", "orphan_metadata")


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


def _direct_delete_is_refused(db, take: str) -> None:
    with db.cursor() as cur:
        cur.execute("SET ROLE service_role")
        try:
            with pytest.raises(psycopg2.Error,
                               match="immutable feedback evidence cannot be changed"):
                cur.execute("""DELETE FROM public.take_feedback_exposure
                                WHERE take_session_id = %s""", (take,))
        finally:
            cur.execute("RESET ROLE")


def _left(db, request: str) -> dict:
    return {row["ref"].split(":", 1)[1]: row["reason"]
            for row in takes._left_for_review(db, request)}


class TestTheFourTablesWaitForTheSignedRules:

    @pytest.fixture(autouse=True)
    def _shape(self, db, no_v1_4_rules):
        _production_shape(db)
        projects._production_columns(db)
        takes._seed_every_retention_rule(db)

    def test_without_v1_4_an_account_erasure_stops_and_deletes_nothing(
            self, db, fake_storage):
        records = _records(db, takes._account_with_one_take(db))
        before = _rows(db, records)

        DataPurgeOrchestrator(_Database(db)).run(records["request"])

        assert _one(db, "SELECT state FROM public.data_purge_requests WHERE id = %s",
                    (records["request"],)) == "review_required"
        assert _left(db, records["request"]) == {
            code: "EXPLICIT_RESOLVER_REQUIRED" for code in THE_THREE}
        assert _target(db, records["request"], "phase1_jobs")["disposition"] == (
            "delete"), "before v1.4 the job row is deleted, as it always was"
        assert _rows(db, records) == before, "an unready erasure deleted something"
        assert not fake_storage, "nothing may be erased before review"
        _direct_delete_is_refused(db, records["take"])

    def test_without_v1_4_a_project_erasure_stops_on_all_four(
            self, db, fake_storage):
        records = _records(db, takes._account_with_one_take(db))
        before = _rows(db, records)
        _request, purge = projects._confirmed_project_deletion(db, records)

        ProjectPurgeOrchestrator(_Database(db)).run(purge)

        assert _one(db, "SELECT state FROM public.data_purge_requests WHERE id = %s",
                    (purge,)) == "review_required"
        assert _left(db, purge) == {
            code: "EXPLICIT_RESOLVER_REQUIRED" for code in THE_FOUR}
        assert _rows(db, records) == before
        assert not fake_storage


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

    def test_outside_a_running_purge_the_trigger_still_refuses(self, db):
        records = _records(db, takes._account_with_one_take(db))
        _direct_delete_is_refused(db, records["take"])
        assert _rows(db, records)["shown"] == 1

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


class TestTheJobPlumbingGoesWithTheAccount:
    """0425 (decided 2026-10-05 on W3-B1's finding): the purge deletes the
    outbox row, the carry-over and the orphaned object's metadata with the
    account, as the registry has always listed them; v1.4 keeps the job and
    its events. Proved on production's job list, without which the lane's
    account erasure never reaches a job (`production_job_list`)."""

    @pytest.fixture(autouse=True)
    def _shape(self, db, no_v1_4_rules, production_job_list):
        _production_shape(db)
        takes._seed_every_retention_rule(db)

    def test_without_v1_4_the_erasure_stops_and_the_plumbing_stays(
            self, db, fake_storage):
        records = _records(db, takes._account_with_one_take(db))
        plumbing = _plumbing(db, records)
        before = (_rows(db, records), _plumbing_rows(db, plumbing))

        DataPurgeOrchestrator(_Database(db)).run(records["request"])

        assert _one(db, "SELECT state FROM public.data_purge_requests WHERE id = %s",
                    (records["request"],)) == "review_required"
        # As on main: the three product tables and, with the jobs listed,
        # the jobs' events stop the erasure before anything is touched.
        assert _left(db, records["request"]) == {
            code: "EXPLICIT_RESOLVER_REQUIRED" for code in THE_FOUR}
        for code in THE_PLUMBING + ("phase1_jobs",):
            assert _target(db, records["request"], code) == {
                "state": "pending", "reason": None, "disposition": "delete",
                "rule": None}, code
        assert (_rows(db, records), _plumbing_rows(db, plumbing)) == before
        assert not fake_storage, "nothing may be erased before review"

    def test_with_v1_4_the_erasure_deletes_the_plumbing_and_keeps_the_job(
            self, db, fake_storage):
        _v1_4_registered(db)
        records = _records(db, takes._account_with_one_take(db))
        plumbing = _plumbing(db, records)

        DataPurgeOrchestrator(_Database(db)).run(records["request"])

        assert takes._left_for_review(db, records["request"]) == []
        assert _one(db, "SELECT state FROM public.data_purge_requests WHERE id = %s",
                    (records["request"],)) == "done"
        assert _plumbing_rows(db, plumbing) == {
            "outbox": 0, "carryover": 0, "orphan": 0}
        for code in THE_PLUMBING:
            assert _target(db, records["request"], code) == {
                "state": "deleted", "reason": None, "disposition": "delete",
                "rule": None}, code
        assert _rows(db, records) == {
            "shown": 0, "answers": 0, "versions": 0, "job": 1, "events": 2}
        for code in ("phase1_jobs", "phase1_job_events"):
            assert _target(db, records["request"], code) == {
                "state": "retained", "reason": None, "disposition": "retain",
                "rule": "job-evidence-v1"}, code
        # The orphaned upload's object went from storage before its row.
        assert ("take-audio", plumbing["orphan_key"]) in fake_storage

    def test_a_project_erasure_deletes_its_outbox_row_and_carry_over(
            self, db, fake_storage):
        """The project graph lists the project's jobs (0380): their outbox
        rows and carry-overs go with the project, the job and its events
        stay, and the orphaned upload, which belongs to the account, stays
        for the account's erasure (the runbook's account of 0425)."""
        projects._production_columns(db)
        _v1_4_registered(db)
        records = _records(db, takes._account_with_one_take(db))
        plumbing = _plumbing(db, records)
        _request, purge = projects._confirmed_project_deletion(db, records)

        ProjectPurgeOrchestrator(_Database(db)).run(purge)

        assert takes._left_for_review(db, purge) == []
        assert _one(db, "SELECT state FROM public.data_purge_requests WHERE id = %s",
                    (purge,)) == "done"
        assert _plumbing_rows(db, plumbing) == {
            "outbox": 0, "carryover": 0, "orphan": 1}
        assert _rows(db, records)["job"] == 1
        assert _rows(db, records)["events"] == 2

