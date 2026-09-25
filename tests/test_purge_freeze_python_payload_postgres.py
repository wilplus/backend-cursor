"""The freeze accepts the subject graph the orchestrator actually sends.

#490 (2026-09-13) taught `services/data_purge.py` a `delivery_job_ids` key:
`SubjectGraph.payload()` always carries it, and `build_subject_graph` filled
it in Python from `feedback_language_delivery_materialization_jobs`. The SQL
side was never told:

  * `freeze_phase1_purge_inventory_v4` compares the graph it is sent against
    `resolve_phase1_purge_subject_graph_v2(...)` with IS DISTINCT FROM, and
    the resolver never returned `delivery_job_ids`, so the comparison failed
    for EVERY subject and raised `PURGE_SUBJECT_GRAPH_MISMATCH`;
  * its locator CASE had no `'delivery_job'` branch, while four registry
    dependencies (`services/data_purge_registry.py`) locate by it, so every
    such dependency target raised `PURGE_DEPENDENCY_TARGET_GRAPH_MISMATCH`.

Every governed Phase-1 purge therefore stopped at the freeze: the request was
written and nothing was erased. It stayed invisible because the only rehearsal
cases froze with the resolver's own output, never with the payload Python
builds. These cases drive the REAL orchestrator through a thin psycopg2
stand-in for the Supabase client, so the freeze sees exactly the bytes
production sends. The target must be a disposable local database.
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Any

import psycopg2
import pytest

from services.data_purge import DataPurgeOrchestrator
from services.data_purge_registry import DEPENDENCIES

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

RESOLVER = "phase1-purge-resolver-v4"
DELIVERY_JOB_DEPENDENCIES = tuple(
    dependency for dependency in DEPENDENCIES
    if dependency.locator_kind == "delivery_job"
)


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


def _one(db, sql, args=()):
    with db.cursor() as cur:
        cur.execute(sql, args)
        row = cur.fetchone()
        return row[0] if row else None


# ── A psycopg2 stand-in for the Supabase client ─────────────────────────────
# Only the surface the orchestrator's inventory and freeze paths call. Every
# RPC it reaches returns a scalar JSONB, which PostgREST hands back as the
# value itself; a table read comes back as a list of row dicts. A database
# error keeps its SQLSTATE on `.code`, which is what `_missing_relation` reads.


class _Result:
    def __init__(self, data: Any) -> None:
        self.data = data


class _DatabaseError(RuntimeError):
    def __init__(self, error: psycopg2.Error) -> None:
        super().__init__(str(error))
        self.code = error.pgcode or ""


class _Rpc:
    def __init__(self, conn, name: str, params: dict[str, Any]) -> None:
        self.conn, self.name, self.params = conn, name, params

    def execute(self) -> _Result:
        names = list(self.params)
        args = [
            json.dumps(value) if isinstance(value, (dict, list))
            and not name.endswith("_relations") else value
            for name, value in self.params.items()
        ]
        call = ", ".join(f"{name} => %s" for name in names)
        try:
            return _Result(_one(self.conn, f"SELECT public.{self.name}({call})", args))
        except psycopg2.Error as error:
            raise _DatabaseError(error) from error


class _Query:
    def __init__(self, conn, relation: str) -> None:
        self.conn, self.relation = conn, relation
        self.columns = "*"
        self.filters: list[tuple[str, list[str]]] = []
        self.bounds: tuple[int, int] | None = None
        self.max_rows: int | None = None

    def select(self, columns: str) -> "_Query":
        self.columns = columns
        return self

    def eq(self, column: str, value: Any) -> "_Query":
        self.filters.append((column, [str(value)]))
        return self

    def in_(self, column: str, values: list[Any]) -> "_Query":
        self.filters.append((column, [str(value) for value in values]))
        return self

    def range(self, start: int, end: int) -> "_Query":
        self.bounds = (start, end)
        return self

    def limit(self, count: int) -> "_Query":
        self.max_rows = count
        return self

    def execute(self) -> _Result:
        columns = ", ".join(
            f'"{column.strip()}"' for column in self.columns.split(",")
        ) if self.columns != "*" else "*"
        where = " AND ".join(
            f'"{column}"::text = ANY(%s)' for column, _values in self.filters
        ) or "true"
        sql = f'SELECT to_jsonb(r) FROM (SELECT {columns} FROM public."{self.relation}" WHERE {where}) r'
        if self.bounds:
            sql += f" OFFSET {self.bounds[0]} LIMIT {self.bounds[1] - self.bounds[0] + 1}"
        elif self.max_rows is not None:
            sql += f" LIMIT {self.max_rows}"
        try:
            with self.conn.cursor() as cur:
                cur.execute(sql, [values for _column, values in self.filters])
                return _Result([row[0] for row in cur.fetchall()])
        except psycopg2.Error as error:
            raise _DatabaseError(error) from error


class _Client:
    def __init__(self, conn) -> None:
        self.conn = conn

    def rpc(self, name: str, params: dict[str, Any]) -> _Rpc:
        return _Rpc(self.conn, name, params)

    def table(self, relation: str) -> _Query:
        return _Query(self.conn, relation)


class _Database:
    def __init__(self, conn) -> None:
        self.client = _Client(conn)


# ── The subject ─────────────────────────────────────────────────────────────


def _principal(db) -> str:
    return str(_one(db, """
        INSERT INTO public.owner_principals (id, user_id)
        VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id"""))


def _request(db, principal: str) -> str:
    return str(_one(db, """
        INSERT INTO public.data_purge_requests (
            acquisition_principal_id, trigger_kind, idempotency_key)
        VALUES (%s, 'account_deletion', %s) RETURNING id""",
        (principal, str(uuid.uuid4()))))


def _delivery_job(db, principal: str) -> str:
    """One materialization job owned by `principal`.

    The job's two parents — a feedback revision and a bundle attachment — are
    the whole coaching-bundle chain, and neither the resolver nor the freeze
    reads them: both locate a job by `acquisition_principal_id` alone. So the
    row is written with replica role on THIS connection, which suspends the FK
    and due-head triggers for the one INSERT. Disposable-only, and the
    principal FK is exactly the column the question is about.
    """
    with db.cursor() as cur:
        cur.execute("SET session_replication_role = replica")
        try:
            cur.execute("""
                INSERT INTO public.feedback_language_delivery_materialization_jobs (
                    revision_id, bundle_attachment_id, acquisition_principal_id,
                    job_state, job_sha256, idempotency_key)
                VALUES (gen_random_uuid(), gen_random_uuid(), %s, 'pending', %s, %s)
                RETURNING id""",
                (principal, "c" * 64, f"purge-freeze-{uuid.uuid4()}"))
            return str(cur.fetchone()[0])
        finally:
            cur.execute("SET session_replication_role = DEFAULT")


def _freeze(db, request: str, graph: dict, targets: list[dict]):
    return _one(db, """
        SELECT public.freeze_phase1_purge_inventory_v4(
            %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::text[])""",
        (request, RESOLVER, "f" * 64, json.dumps(graph), json.dumps(targets),
         "e" * 64, []))


@pytest.fixture
def subject(db):
    """A speaker with one delivery job, asking to be erased."""
    principal = _principal(db)
    return {
        "principal": principal,
        "job": _delivery_job(db, principal),
        "request": _request(db, principal),
    }


class TestTheFreezeTakesThePayloadPythonBuilds:

    def test_the_orchestrator_freezes_a_subject_with_a_delivery_job(self, db, subject):
        """The reproduction: the real inventory, the real freeze, end to end.

        Before the fix this raised PURGE_SUBJECT_GRAPH_MISMATCH for every
        subject, because the graph Python sends carries `delivery_job_ids` and
        the one the server derives did not.
        """
        orchestrator = DataPurgeOrchestrator(_Database(db))
        orchestrator.freeze_inventory(subject["request"])

        frozen = _one(db, """
            SELECT subject_graph FROM public.data_purge_inventory_manifests
             WHERE purge_request_id = %s""", (subject["request"],))
        assert frozen is not None, "the freeze wrote no manifest"
        assert frozen["delivery_job_ids"] == [subject["job"]], (
            "the frozen graph does not name the subject's delivery job")

    def test_a_subject_with_no_delivery_job_also_freezes(self, db):
        """The common case. The four job-keyed dependencies still emit a
        target with `locator_kind = 'delivery_job'` and no values; before the
        fix the freeze had no branch for that locator and refused it."""
        principal = _principal(db)
        request = _request(db, principal)

        DataPurgeOrchestrator(_Database(db)).freeze_inventory(request)

        assert _one(db, """
            SELECT subject_graph->'delivery_job_ids'
              FROM public.data_purge_inventory_manifests
             WHERE purge_request_id = %s""", (request,)) == []
        located = _one(db, """
            SELECT count(*) FROM public.data_purge_targets
             WHERE purge_request_id = %s
               AND metadata->>'locator_kind' = 'delivery_job'""", (request,))
        assert located == len(DELIVERY_JOB_DEPENDENCIES), (
            "a delivery-job dependency target never reached the manifest")

    def test_the_server_names_only_the_subjects_own_jobs(self, db, subject):
        """The server is the authority on the graph, so it must derive the key
        itself — and scope it to the subject, never the whole table."""
        stranger = _principal(db)
        strangers_job = _delivery_job(db, stranger)

        graph = _one(db, "SELECT public.resolve_phase1_purge_subject_graph_v2(%s)",
                     (subject["principal"],))

        assert graph.get("delivery_job_ids") == [subject["job"]]
        assert strangers_job not in graph["delivery_job_ids"]

    def test_a_graph_claiming_someone_elses_job_is_refused(self, db, subject):
        """Python cannot widen the erasure: a payload that names a job the
        server does not attribute to this subject is still a mismatch."""
        stranger = _principal(db)
        strangers_job = _delivery_job(db, stranger)
        graph = DataPurgeOrchestrator(_Database(db)).build_subject_graph(
            subject["principal"], frozenset(),
        ).payload()
        graph["delivery_job_ids"] = sorted([subject["job"], strangers_job])

        with pytest.raises(psycopg2.errors.RaiseException) as raised:
            _freeze(db, subject["request"], graph, [_job_target(graph)])
        assert "PURGE_SUBJECT_GRAPH_MISMATCH" in str(raised.value)

    def test_a_delivery_job_target_must_match_the_graph(self, db, subject):
        """The new locator branch checks its values exactly as its siblings
        do: a target locating a job the graph does not hold is refused."""
        graph = _one(db, "SELECT public.resolve_phase1_purge_subject_graph_v2(%s)",
                     (subject["principal"],))
        target = _job_target(graph)
        target["metadata"]["locator_values"] = [str(uuid.uuid4())]

        with pytest.raises(psycopg2.errors.RaiseException) as raised:
            _freeze(db, subject["request"], graph, [target])
        assert "PURGE_DEPENDENCY_TARGET_GRAPH_MISMATCH" in str(raised.value)


def _job_target(graph: dict) -> dict:
    dependency = DELIVERY_JOB_DEPENDENCIES[0]
    return {
        "target_kind": dependency.target_kind,
        "target_ref": f"dependency:{dependency.code}",
        "initial_match_count": 0,
        "metadata": {
            "dependency_code": dependency.code,
            "relation": dependency.relation,
            "selector_column": dependency.selector_column,
            "locator_kind": dependency.locator_kind,
            "locator_values": list(graph.get("delivery_job_ids") or []),
            "disposition": dependency.disposition,
            "delete_order": dependency.delete_order,
        },
    }
