"""An account deletion can start: the orchestrator's own freeze, on the real schema.

FOUNDER 2026-09-25, decision 6 ("fix it now"). Migration 0362.

`DataPurgeOrchestrator.build_subject_graph` added `delivery_job_ids` to the
graph it sends (2026-09-19). `freeze_phase1_purge_inventory_v4` recomputes the
graph in SQL and requires the two to be identical, and its graph had no such
key. So every freeze raised PURGE_SUBJECT_GRAPH_MISMATCH and every account
deletion sat at `requested` with nothing erased.

The existing rehearsal cases could not see it: they hand the freeze the graph
SQL itself resolves. These cases run `DataPurgeOrchestrator.freeze_inventory`
— the Python that production runs — through a thin client that turns its
PostgREST calls into SQL, as service_role, against the disposable schema. The
two halves are compared by the only thing that decides: the freeze accepting
what the orchestrator sends.
"""
from __future__ import annotations

import os
import uuid
from typing import Any

import psycopg2
import psycopg2.extras
import pytest
from psycopg2 import sql

from services.data_purge import DataPurgeOrchestrator

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)


class _Result:
    def __init__(self, data: Any) -> None:
        self.data = data


class _Query:
    """The slice of the PostgREST builder the orchestrator uses."""

    def __init__(self, client: "_SqlClient", relation: str) -> None:
        self.client, self.relation = client, relation
        self.columns = "*"
        self.filters: list[tuple[str, str, Any]] = []
        self.bounds: tuple[int, int] | None = None
        self.cap: int | None = None
        self.deleting = False

    def select(self, columns: str) -> "_Query":
        self.columns = columns
        return self

    def delete(self) -> "_Query":
        self.deleting = True
        return self

    def eq(self, column: str, value: Any) -> "_Query":
        self.filters.append((column, "=", value))
        return self

    def in_(self, column: str, values: list) -> "_Query":
        self.filters.append((column, "in", list(values)))
        return self

    def limit(self, count: int) -> "_Query":
        self.cap = count
        return self

    def range(self, first: int, last: int) -> "_Query":
        self.bounds = (first, last)
        return self

    def execute(self) -> _Result:
        columns = (
            sql.SQL("*") if self.columns.strip() == "*"
            else sql.SQL(",").join(
                sql.Identifier(c.strip()) for c in self.columns.split(","))
        )
        where, args = [], []
        for column, op, value in self.filters:
            if op == "=":
                where.append(sql.SQL("{}::text = %s").format(sql.Identifier(column)))
                args.append(str(value))
            else:
                where.append(sql.SQL("{}::text = ANY(%s)").format(sql.Identifier(column)))
                args.append([str(v) for v in value])
        if self.deleting:
            assert where, "an unfiltered DELETE never reaches the database"
            statement = sql.SQL("DELETE FROM public.{} WHERE {} RETURNING *").format(
                sql.Identifier(self.relation), sql.SQL(" AND ").join(where))
            return _Result(self.client.fetch(statement, args))
        query = sql.SQL("SELECT {} FROM public.{}").format(
            columns, sql.Identifier(self.relation))
        if where:
            query += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(where)
        if self.bounds:
            query += sql.SQL(" OFFSET {} LIMIT {}").format(
                sql.Literal(self.bounds[0]),
                sql.Literal(self.bounds[1] - self.bounds[0] + 1))
        elif self.cap:
            query += sql.SQL(" LIMIT {}").format(sql.Literal(self.cap))
        return _Result(self.client.fetch(query, args))


class _Rpc:
    def __init__(self, client: "_SqlClient", name: str, params: dict) -> None:
        self.client, self.name, self.params = client, name, params

    def execute(self) -> _Result:
        parts, args = [], []
        for key, value in self.params.items():
            # A mapping, or a list of mappings, is JSONB; a list of strings
            # is a text array, as PostgREST coerces each for its parameter.
            if isinstance(value, dict) or (
                isinstance(value, list) and any(isinstance(v, dict) for v in value)
            ):
                parts.append(sql.SQL("{} => %s::jsonb").format(sql.Identifier(key)))
                args.append(psycopg2.extras.Json(value))
            elif isinstance(value, list):
                parts.append(sql.SQL("{} => %s::text[]").format(sql.Identifier(key)))
                args.append(value)
            else:
                parts.append(sql.SQL("{} => %s").format(sql.Identifier(key)))
                args.append(value)
        query = sql.SQL("SELECT * FROM public.{}({})").format(
            sql.Identifier(self.name), sql.SQL(", ").join(parts))
        rows = self.client.fetch(query, args)
        # A function returning one JSONB value comes back as that value, as
        # PostgREST returns it; a set-returning one as its rows.
        if len(rows) == 1 and list(rows[0]) == [self.name]:
            return _Result(rows[0][self.name])
        return _Result(rows)


class _SqlClient:
    def __init__(self, connection) -> None:
        self.connection = connection

    def table(self, relation: str) -> _Query:
        return _Query(self, relation)

    def rpc(self, name: str, params: dict) -> _Rpc:
        return _Rpc(self, name, params)

    def fetch(self, query, args) -> list[dict]:
        with self.connection.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor,
        ) as cur:
            cur.execute("SET ROLE service_role")
            try:
                cur.execute(query, args)
                return [dict(row) for row in cur.fetchall()]
            finally:
                cur.execute("RESET ROLE")


class _Database:
    def __init__(self, connection) -> None:
        self.client = _SqlClient(connection)


@pytest.fixture
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    try:
        yield conn
    finally:
        conn.close()


def _one(db, statement, args=()):
    with db.cursor() as cur:
        cur.execute(statement, args)
        row = cur.fetchone()
        return row[0] if row else None


def _request_for_speaker_with_practice(db) -> dict:
    """A speaker who recorded one practice attempt, then asked to be erased."""
    principal = _one(db, """
        INSERT INTO public.owner_principals (id, user_id)
        VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id""")
    practice_id = _one(db, """
        INSERT INTO public.confident_voice_practice (
            id, owner_user_id, take_session_id)
        VALUES (gen_random_uuid(), gen_random_uuid(), gen_random_uuid())
        RETURNING id""")
    attempt = _one(db, """
        INSERT INTO public.confident_voice_practice_attempt (id, practice_id)
        VALUES (gen_random_uuid(), %s) RETURNING id""", (practice_id,))
    _one(db, """
        INSERT INTO public.processing_practice_objects (
            acquisition_principal_id, practice_attempt_id, storage_provider,
            bucket, object_key, byte_size, content_type, exact_bytes_sha256)
        VALUES (%s, %s, 'r2', 'practice-audio', %s, 4096, 'audio/webm', %s)
        RETURNING id""",
        (principal, attempt, f"confidence-practice/{uuid.uuid4()}/a.webm", "c" * 64))
    request = _one(db, """
        INSERT INTO public.data_purge_requests (
            acquisition_principal_id, trigger_kind, idempotency_key)
        VALUES (%s, 'account_deletion', %s) RETURNING id""",
        (principal, str(uuid.uuid4())))
    return {"principal": str(principal), "request": str(request)}


def _add_delivery_job(db, principal: str) -> str:
    """One Feedback-language delivery job owned by the speaker.

    Its revision and bundle attachment are foreign keys into the coaching
    bundle, whose fixtures would dwarf this file; the graph reads only
    `acquisition_principal_id`. So this one insert skips FK triggers for its
    own statement, in this disposable database only.
    """
    with db.cursor() as cur:
        cur.execute("SET session_replication_role = replica")
        try:
            cur.execute("""
                INSERT INTO public.feedback_language_delivery_materialization_jobs (
                    revision_id, bundle_attachment_id, acquisition_principal_id,
                    job_state, job_sha256, idempotency_key)
                VALUES (gen_random_uuid(), gen_random_uuid(), %s, 'pending',
                        %s, %s) RETURNING id""",
                (principal, "d" * 64, str(uuid.uuid4())))
            return str(cur.fetchone()[0])
        finally:
            cur.execute("SET session_replication_role = origin")


class TestAnAccountDeletionStarts:

    def test_the_orchestrators_own_freeze_is_accepted(self, db):
        """Before 0362 this raised PURGE_SUBJECT_GRAPH_MISMATCH, always."""
        subject = _request_for_speaker_with_practice(db)
        orchestrator = DataPurgeOrchestrator(_Database(db))

        result = orchestrator.freeze_inventory(subject["request"])

        assert result.get("state") in ("in_progress", "review_required"), result
        manifest = _one(db, """
            SELECT subject_graph FROM public.data_purge_inventory_manifests
             WHERE purge_request_id = %s""", (subject["request"],))
        assert manifest is not None, "nothing was frozen"
        assert manifest["delivery_job_ids"] == []
        assert subject["principal"] in manifest["principal_ids"]
        assert _one(db, """
            SELECT count(*) FROM public.data_purge_targets
             WHERE purge_request_id = %s
               AND metadata->>'source_relation' = 'processing_practice_objects'
               AND state = 'pending'""", (subject["request"],)) == 1, (
            "the practice recording never reached the frozen manifest")

    def test_a_speakers_delivery_jobs_are_in_the_graph_and_the_freeze_takes_them(self, db):
        """The registry's delivery-job dependencies map to the graph (0362).

        They are `external_review` in the registry, so with rows present they
        freeze as `unknown` and the request goes to review — the designed
        fail-closed path — rather than raising on the locator map."""
        subject = _request_for_speaker_with_practice(db)
        job = _add_delivery_job(db, subject["principal"])
        orchestrator = DataPurgeOrchestrator(_Database(db))

        graph = orchestrator.build_subject_graph(subject["principal"], frozenset())
        assert graph.delivery_job_ids == (job,)

        result = orchestrator.freeze_inventory(subject["request"])
        assert result.get("state") == "review_required", result
        assert _one(db, """
            SELECT count(*) FROM public.data_purge_targets
             WHERE purge_request_id = %s
               AND metadata->>'locator_kind' = 'delivery_job'""",
            (subject["request"],)) >= 1

    def test_a_replay_of_the_same_freeze_is_accepted(self, db):
        """A worker that retries after a crash must not be refused."""
        subject = _request_for_speaker_with_practice(db)
        orchestrator = DataPurgeOrchestrator(_Database(db))
        first = orchestrator.freeze_inventory(subject["request"])
        again = orchestrator.freeze_inventory(subject["request"])
        assert again["state"] == "frozen"
        assert again["inventory_sha256"] == first["inventory_sha256"]

    def test_a_graph_that_is_not_the_subjects_is_still_refused(self, db):
        """The equality check stays: a stale or foreign graph never freezes."""
        subject = _request_for_speaker_with_practice(db)
        orchestrator = DataPurgeOrchestrator(_Database(db))
        graph = orchestrator.build_subject_graph(subject["principal"], frozenset())
        forged = {**graph.payload(), "delivery_job_ids": [str(uuid.uuid4())]}
        with pytest.raises(psycopg2.Error, match="PURGE_SUBJECT_GRAPH_MISMATCH"):
            _one(db, """
                SELECT public.freeze_phase1_purge_inventory_v4(
                    %s, 'phase1-purge-resolver-v4', %s, %s::jsonb, %s::jsonb,
                    %s, %s::text[])""",
                (subject["request"], "f" * 64, psycopg2.extras.Json(forged),
                 psycopg2.extras.Json([{"target_kind": "unknown",
                                        "target_ref": "x"}]),
                 "e" * 64, []))

    def test_the_erasure_runs_to_the_end_once_the_retention_rules_exist(self, db):
        """The whole run — freeze, resolve, finalize.

        FIRST, THE REMAINING BLOCKER, STATED BY RUNNING IT. The purge keeps
        the person's identity row as proof the erasure happened, and keeps it
        only under an active `deletion_evidence` retention rule. Production has
        none: the seed waits in migrations/pending/ for the signed retention
        schedule (doc 06). Without it the run stops at `review_required` and
        deletes nothing — on that retention rule and on nothing else.

        THEN THE CODE PATH, ONCE THE DOCUMENT LANDS. Seeded here as the pending
        file would seed it, the same run reaches `done` and the practice rows
        are gone. No storage object: deleting one calls R2, which this lane
        does not have."""
        if not _one(db, """
                SELECT count(*) FROM public.data_retention_rules
                 WHERE evidence_category = 'deletion_evidence' AND active"""):
            blocked = _request_with_practice_rows(db)
            DataPurgeOrchestrator(_Database(db)).run(blocked["request"])
            assert _one(db, "SELECT state FROM public.data_purge_requests WHERE id = %s",
                        (blocked["request"],)) == "review_required"
            reasons = _one(db, """
                SELECT jsonb_agg(DISTINCT metadata->>'reason_code')
                  FROM public.data_purge_targets
                 WHERE purge_request_id = %s AND state IN ('unknown', 'failed')""",
                (blocked["request"],))
            assert reasons == ["RETENTION_RULE_UNRESOLVED"], reasons
            _seed_deletion_evidence_rule(db)

        subject = _request_with_practice_rows(db)
        outcome = DataPurgeOrchestrator(_Database(db)).run(subject["request"])

        left = _one(db, """
            SELECT coalesce(jsonb_agg(target_ref), '[]'::jsonb)
              FROM public.data_purge_targets
             WHERE purge_request_id = %s AND state IN ('unknown', 'failed')""",
            (subject["request"],))
        assert left == [], f"targets left for review or failed: {left}"
        assert _one(db, "SELECT state FROM public.data_purge_requests WHERE id = %s",
                    (subject["request"],)) == "done", outcome
        assert _one(db, "SELECT count(*) FROM public.confident_voice_practice WHERE id = %s",
                    (subject["practice"],)) == 0, "the practice row survived the erasure"


def _request_with_practice_rows(db) -> dict:
    principal = _one(db, """
        INSERT INTO public.owner_principals (id, user_id)
        VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id""")
    user_id = _one(db, "SELECT user_id FROM public.owner_principals WHERE id = %s",
                   (principal,))
    practice = _one(db, """
        INSERT INTO public.confident_voice_practice (
            id, owner_user_id, take_session_id)
        VALUES (gen_random_uuid(), %s, gen_random_uuid()) RETURNING id""",
        (user_id,))
    _one(db, """
        INSERT INTO public.confident_voice_practice_attempt (id, practice_id)
        VALUES (gen_random_uuid(), %s) RETURNING id""", (practice,))
    request = _one(db, """
        INSERT INTO public.data_purge_requests (
            acquisition_principal_id, trigger_kind, idempotency_key)
        VALUES (%s, 'account_deletion', %s) RETURNING id""",
        (principal, str(uuid.uuid4())))
    return {"request": str(request), "practice": str(practice)}


def _seed_deletion_evidence_rule(db) -> None:
    """What migrations/the_retention_schedule_is_loaded.sql will write,
    with a stand-in document: this database is disposable."""
    artifact = _one(db, """
        INSERT INTO public.processing_legal_artifacts (
            artifact_kind, version, approving_authority, approved_at,
            object_key, sha256)
        VALUES ('retention_schedule', 'rehearsal-' || gen_random_uuid(),
                'rehearsal', now(), 'rehearsal/retention.pdf', %s)
        RETURNING id""", ("a" * 64,))
    _one(db, """
        INSERT INTO public.data_retention_rules (
            rule_code, evidence_category, retention_until_rule,
            legal_artifact_id, active)
        VALUES ('deletion-evidence-v1', 'deletion_evidence',
                'accountability_need_ends', %s, true)
        ON CONFLICT (rule_code) DO NOTHING RETURNING id""", (artifact,))
