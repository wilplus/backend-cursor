"""Retention schedule v1.5 on the real schema (founder 2026-10-05, decisions
log N50 item 5, "P1 A ... P6 A"): the purge reaches what v1.4 left open, and
only once v1.5 is registered.

These cases run the Python production runs (`DataPurgeOrchestrator.run`,
`ProjectPurgeOrchestrator.run`) through the SQL client of
tests/test_account_deletion_starts_postgres.py, as service_role, on the
released rehearsal lane, with migration 0429 applied twice:

  * the mechanism is installed: every table v1.5 deletes carries a guard
    that names this migration, the service role holds DELETE and the
    selecting columns and nothing more, every foreign key between two tables
    the purge deletes points from an earlier delete to a later one, and the
    one table left alone never holds a row;
  * each of the ten guard functions lets through exactly the row a running
    purge's sealed inventory names, under product-records-v1, once v1.5 is
    registered, and refuses every other delete (probe tables, so that every
    guard is proved, not only the ones a seeded account reaches);
  * P1: WITHOUT v1.5 an erasure stops for review on the nine live records
    and deletes nothing; WITH it the account erasure deletes them and
    reaches done, a project erasure deletes that project's (its answers
    reached through the project's memberships) and keeps the other's, and a
    stranger's rows are never reached; a decision the purge keeps (N12)
    still pointing at an item stops the whole erasure before anything is
    deleted;
  * P2-P5 on stand-ins of their production tables: a free founding pass is
    deleted and a paid arc kept as a financial record, the consent snapshot
    is kept as consent evidence, a library video keeps its row and loses
    only the speaker's link while one made for the speaker stops for its
    file, and the four retired corpora with one owner column are deleted -
    the reflection clips past the retired-write guard;
  * the founder's two scripts: the registration refuses until it is signed,
    until the three rules it points at are active and until 0429 is in the
    database, and the read-only count prints a row for every table it names.

v1.5 is not signed yet, so the registration runs with a stand-in hash put
where the founder will put the signed one; everything else is the file as
it is. Named stand-ins: object storage is faked (tests/test_take_purge_
postgres.py); rows of the dark tables are written with triggers and foreign
keys off (session_replication_role = replica), the only way to write them
outside their own database functions; the legacy tables this lane lacks are
laid down from the migrations that created them.
"""
from __future__ import annotations

import hashlib
import pathlib
import uuid

import psycopg2
import psycopg2.extras
import pytest

from services.data_purge import DataPurgeOrchestrator
from services.data_purge_project_scope import (
    PROJECT_SELECTORS,
    ProjectPurgeOrchestrator,
)
from services.data_purge_registry import DEPENDENCIES, SCHEDULE_V1_5
from tests import test_account_deletion_starts_postgres as base
from tests import test_product_records_purge_postgres as v1_4
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
MIGRATION = (ROOT / "migrations"
             / "the_purge_reaches_what_v1_5_decided.sql").read_text()
SCRIPT = (ROOT / "scripts" / "phase1_retention_schedule_v1_5.sql").read_text()
COUNTS = ROOT / "scripts" / "phase1_retention_v1_5_counts.sql"
PLACEHOLDER = "[[sha256 of the signed PDF, from SIGNED-ARTIFACTS.md]]"
STAND_IN_HASH = "5" * 64
MARKER = "/* 0429 v1.5 purge */"
CAPABILITIES = "confident_moment_text_update_capabilities"
#: The legacy tables this lane never created; the cases below lay them down.
LEGACY = {"arc_purchases", "admin_uploaded_reference_videos",
          "reflection_clips", "strong_sides_library", "recording_reviews",
          "recording_review_annotations"}
V1_5 = [d for d in DEPENDENCIES if d.schedule == SCHEDULE_V1_5]
V1_5_DELETES = sorted({d.relation for d in V1_5 if d.disposition == "delete"})
#: Eight of the nine live records of P1 (v1.4 §5.1), by registry code; the
#: ninth, the capabilities table, never holds a row at rest.
P1 = ("feedback_v3_memberships", "feedback_v3_membership_items",
      "feedback_v3_owner_responses", "feedback_v3_service_render_receipts",
      "feedback_v3_service_response_bindings",
      "learning_surface_presentations", "learning_surface_exposure_receipts",
      "ideal_text_user_edit_cas_operations")
P1_TABLES = {code: code for code in P1}


# ── the founder's steps ─────────────────────────────────────────────────


def _earlier_rules(db) -> None:
    """The two rules v1.5 points at besides product-records-v1, as v1.2's
    and v1.3's scripts seed them (codes, categories, periods), active."""
    artifact = _one(db, """
        SELECT id FROM public.processing_legal_artifacts
         WHERE artifact_kind = 'retention_schedule'
         ORDER BY created_at LIMIT 1""")
    with db.cursor() as cur:
        cur.execute("""
            INSERT INTO public.data_retention_rules (
                rule_code, evidence_category, retention_until_rule,
                legal_artifact_id, active)
            VALUES ('consent-evidence-v1', 'consent_evidence',
                    'six_years_after_withdrawal_or_erasure', %s, true),
                   ('financial-evidence-v1', 'financial_evidence',
                    'financial_year_end_plus_5_years', %s, true)
            ON CONFLICT (rule_code) DO NOTHING""", (artifact, artifact))
        cur.execute("""
            UPDATE public.data_retention_rules SET active = true
             WHERE rule_code IN ('consent-evidence-v1',
                                 'financial-evidence-v1')""")


def _unregister_v1_5(db) -> None:
    """Take the 1.5 row out again: the lane is shared, and a later module
    must see the schedule as production does before the founder signs. The
    row is append-only, so its guard steps aside for this one statement."""
    db.autocommit = False
    try:
        with db.cursor() as cur:
            cur.execute("""ALTER TABLE public.processing_legal_artifacts
                           DISABLE TRIGGER processing_legal_artifacts_immutable""")
            cur.execute("""DELETE FROM public.processing_legal_artifacts
                            WHERE artifact_kind = 'retention_schedule'
                              AND version = %s""", (SCHEDULE_V1_5,))
            cur.execute("""ALTER TABLE public.processing_legal_artifacts
                           ENABLE TRIGGER processing_legal_artifacts_immutable""")
        db.commit()
    finally:
        db.autocommit = True


def _register_v1_5(db) -> None:
    """The founder's step, as he will run it: the script, with a stand-in
    where the signed PDF's hash goes (v1.5 is not signed yet)."""
    assert SCRIPT.count(PLACEHOLDER) == 1
    with db.cursor() as cur:
        cur.execute(SCRIPT.replace(PLACEHOLDER, STAND_IN_HASH))


#: The rules a ruled entry names, withdrawn again after each case: a later
#: module on this shared lane must meet them as a fresh database does.
NAMED_RULES = ("product-records-v1", "job-evidence-v1", "consent-evidence-v1",
               "financial-evidence-v1")


def _withdraw_named_rules(db) -> None:
    with db.cursor() as cur:
        cur.execute("""UPDATE public.data_retention_rules SET active = false
                        WHERE rule_code = ANY(%s)""", (list(NAMED_RULES),))


@pytest.fixture
def rules(db):
    """Every rule active, v1.4 registered as signed, v1.5 not registered.
    Afterwards the named rules are withdrawn and v1.5 unregistered again."""
    v1_4._production_shape(db)
    projects._production_columns(db)
    takes._seed_every_retention_rule(db)
    v1_4._v1_4_registered(db)
    _earlier_rules(db)
    _unregister_v1_5(db)
    yield
    _unregister_v1_5(db)
    _withdraw_named_rules(db)


@pytest.fixture
def v1_5(db, rules):
    _register_v1_5(db)
    yield


@pytest.fixture(scope="module", autouse=True)
def _legacy_tables_go_afterwards():
    """The legacy stand-ins this module lays down leave with it: the
    bundled-era erasure (tests/test_bundled_era_erasure_postgres.py) counts
    exactly those tables wherever they exist, and this lane never had them."""
    yield
    if not DSN:
        return
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    connection = psycopg2.connect(DSN)
    connection.autocommit = True
    try:
        with connection.cursor() as cur:
            for table in sorted(LEGACY):
                cur.execute(f"DROP TABLE IF EXISTS public.{table}")
    finally:
        connection.close()


# ── rows the dark tables hold ───────────────────────────────────────────


def _replica(db, statements) -> None:
    """Rows of tables only their own database functions write, written past
    their triggers and foreign keys for the length of these statements."""
    with db.cursor() as cur:
        cur.execute("SET session_replication_role = replica")
        try:
            for statement, args in statements:
                cur.execute(statement, args)
        finally:
            cur.execute("SET session_replication_role = DEFAULT")


def _sha() -> str:
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()


def _v3(db, subject: dict) -> dict:
    """The nine live records of one Take (P1): a V3 membership, its item,
    the speaker's answer, its render receipt and the binding between them,
    a learning-surface presentation with its exposure receipt, and one edit
    of the Ideal Text."""
    principal, project, take = (subject["principal"], subject["project"],
                                subject["take"])
    user = str(_one(db, "SELECT user_id FROM public.owner_principals WHERE id = %s",
                    (principal,)))
    ids = {key: str(uuid.uuid4()) for key in (
        "membership", "candidate", "exposure", "receipt", "response",
        "binding", "presentation", "acknowledgement", "cas")}
    _replica(db, [
        ("""INSERT INTO public.feedback_v3_memberships (
                id, acquisition_principal_id, project_id, take_id,
                candidate_set_id, document_snapshot_id,
                document_snapshot_sha256, content_identity_sha256,
                policy_version, block_partition_version, take_index,
                item_count, selected_count, membership_sha256,
                idempotency_key)
            VALUES (%s, %s, %s, %s, gen_random_uuid(), gen_random_uuid(),
                    %s, %s, 'take-feedback-policy-v3-serving-v1',
                    'blocks-75-words-v1', 1, 1, 1, %s, %s)""",
         (ids["membership"], principal, project, take, _sha(), _sha(),
          _sha(), _sha())),
        ("""INSERT INTO public.feedback_v3_membership_items (
                membership_id, acquisition_principal_id, candidate_id,
                evidence_span_id, candidate_key, feedback_family,
                slide_index, block_key, source_ideal_part_id, snippet_id,
                eligibility, selected, position_shown, item_sha256)
            VALUES (%s, %s, %s, gen_random_uuid(), 'cv-1', 'confident_voice',
                    0, 0, gen_random_uuid(), gen_random_uuid(), 'eligible',
                    true, 1, %s)""",
         (ids["membership"], principal, ids["candidate"], _sha())),
        ("""INSERT INTO public.feedback_v3_owner_responses (
                id, membership_id, candidate_id, acquisition_principal_id,
                owner_user_id, response, response_taxonomy_version,
                idempotency_key)
            VALUES (%s, %s, %s, %s, %s, 'confident_yes',
                    'confidence-owner-five-state-v1', %s)""",
         (ids["response"], ids["membership"], ids["candidate"], principal,
          user, _sha())),
        ("""INSERT INTO public.feedback_v3_service_render_receipts (
                id, acquisition_principal_id, owner_user_id, membership_id,
                candidate_id, feedback_exposure_id, render_instance_id,
                content_identity_sha256, rendered_at, client_version,
                receipt_sha256, idempotency_key)
            VALUES (%s, %s, %s, %s, %s, %s, gen_random_uuid(), %s, now(),
                    'rehearsal', %s, %s)""",
         (ids["receipt"], principal, user, ids["membership"],
          ids["candidate"], ids["exposure"], _sha(), _sha(), _sha())),
        ("""INSERT INTO public.feedback_v3_service_response_bindings (
                id, acquisition_principal_id, owner_user_id, membership_id,
                candidate_id, feedback_exposure_id, render_receipt_id,
                v3_owner_response_id, confidence_self_report_id, response,
                response_taxonomy_version, binding_sha256, idempotency_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, gen_random_uuid(),
                    'confident_yes', 'confidence-owner-five-state-v1', %s,
                    %s)""",
         (ids["binding"], principal, user, ids["membership"],
          ids["candidate"], ids["exposure"], ids["receipt"],
          ids["response"], _sha(), _sha())),
        ("""INSERT INTO public.learning_surface_presentations (
                id, owner_principal_id, project_id, take_id,
                learning_surface, actor_role, actor_id,
                complete_candidate_set, selected_candidate, visible_payload,
                versions, content_hash, delivery_mode, evaluation_only,
                idempotency_key)
            VALUES (%s, %s, %s, %s, 'ideal_text_generation', 'owner', %s,
                    '[{}]', '{}', '{}', '{}', %s, 'production', false, %s)""",
         (ids["presentation"], principal, project, take, user, _sha(),
          _sha())),
        ("""INSERT INTO public.learning_surface_exposure_receipts (
                id, presentation_id, owner_principal_id, project_id, take_id,
                learning_surface, actor_role, actor_id, render_instance_id,
                idempotency_key)
            VALUES (%s, %s, %s, %s, %s, 'ideal_text_generation', 'owner', %s,
                    gen_random_uuid(), %s)""",
         (ids["acknowledgement"], ids["presentation"], principal, project,
          take, user, _sha())),
        ("""INSERT INTO public.ideal_text_user_edit_cas_operations (
                id, owner_user_id, acquisition_principal_id, project_id,
                arc_id, source_document_version, operation_kind,
                operation_key_sha256, result_user_text_revision,
                result_user_text_sha256, desired_parts_lineage_sha256,
                result_payload, idempotency_key)
            VALUES (%s, %s, %s, %s, %s, 1, 'ordinary_owner_edit', %s, 1, %s,
                    %s, '{}', %s)""",
         (ids["cas"], user, principal, project, project, _sha(), _sha(),
          _sha(), _sha())),
    ])
    return {**subject, **ids, "user": user}


def _v3_rows(db, rows: dict) -> dict:
    """How many of those rows are still there, table by table."""
    keyed = {
        "feedback_v3_memberships": ("id", rows["membership"]),
        "feedback_v3_membership_items": ("membership_id", rows["membership"]),
        "feedback_v3_owner_responses": ("id", rows["response"]),
        "feedback_v3_service_render_receipts": ("id", rows["receipt"]),
        "feedback_v3_service_response_bindings": ("id", rows["binding"]),
        "learning_surface_presentations": ("id", rows["presentation"]),
        "learning_surface_exposure_receipts": ("id", rows["acknowledgement"]),
        "ideal_text_user_edit_cas_operations": ("id", rows["cas"]),
    }
    return {
        table: _one(db, f"SELECT count(*) FROM public.{table} WHERE {column} = %s",
                    (value,))
        for table, (column, value) in keyed.items()
    }


ALL_THERE = {table: 1 for table in P1}
ALL_GONE = {table: 0 for table in P1}


def _state(db, request: str) -> str:
    return _one(db, "SELECT state FROM public.data_purge_requests WHERE id = %s",
                (request,))


def _target(db, request: str, code: str) -> dict:
    return v1_4._target(db, request, code)


def _left(db, request: str) -> dict:
    return {row["ref"].split(":", 1)[1]: row["reason"]
            for row in takes._left_for_review(db, request)}


def _as_service(db, statement: str, args=()) -> None:
    with db.cursor() as cur:
        cur.execute("SET ROLE service_role")
        try:
            cur.execute(statement, args)
        finally:
            cur.execute("RESET ROLE")


# ── the mechanism is installed ──────────────────────────────────────────


class TestTheMechanismIsInstalled:

    def _selectors(self) -> dict[str, set[str]]:
        columns: dict[str, set[str]] = {}
        for dependency in V1_5:
            if dependency.disposition != "delete":
                continue
            columns.setdefault(dependency.relation, set()).add(
                dependency.selector_column)
            if dependency.code in PROJECT_SELECTORS:
                columns[dependency.relation].add(
                    PROJECT_SELECTORS[dependency.code][0])
        return columns

    def test_every_table_v1_5_deletes_is_guarded_and_open_only_to_deletes(self, db):
        problems = []
        for relation, selectors in sorted(self._selectors().items()):
            if relation in LEGACY or relation == CAPABILITIES:
                continue
            assert _one(db, "SELECT to_regclass(%s) IS NOT NULL",
                        (f"public.{relation}",)), relation
            if not _one(db, "SELECT has_table_privilege('service_role', %s, 'DELETE')",
                        (f"public.{relation}",)):
                problems.append(f"{relation}: no DELETE")
            for column in sorted(selectors):
                if not _one(db, """SELECT has_column_privilege(
                                       'service_role', %s, %s, 'SELECT')""",
                            (f"public.{relation}", column)):
                    problems.append(f"{relation}.{column}: not selectable")
            for privilege in ("INSERT", "UPDATE", "TRUNCATE"):
                if _one(db, "SELECT has_table_privilege('service_role', %s, %s)",
                        (f"public.{relation}", privilege)):
                    problems.append(f"{relation}: {privilege} held")
            guards = _one(db, """
                SELECT coalesce(jsonb_agg(p.proname), '[]'::jsonb)
                  FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
                 WHERE t.tgrelid = %s::regclass AND NOT t.tgisinternal
                   AND t.tgenabled <> 'D' AND (t.tgtype & 2) <> 0
                   AND (t.tgtype & 8) <> 0 AND (t.tgtype & 1) <> 0
                   AND (strpos(pg_get_functiondef(p.oid), %s) > 0
                        OR p.proname = 'guard_phase1_purge_service_delete_v1')""",
                (f"public.{relation}", MARKER))
            if len(guards) != 1:
                problems.append(f"{relation}: guards {guards}")
        assert problems == []

    def test_the_capabilities_table_is_left_alone_and_never_holds_a_row(self, db):
        """Its rows live inside the transaction of the function that writes
        them, which deletes them before it returns (0327): nothing to grant."""
        assert not _one(db, """SELECT has_table_privilege(
                                   'service_role', %s, 'SELECT,DELETE')""",
                        (f"public.{CAPABILITIES}",))
        assert not _one(db, """SELECT has_any_column_privilege(
                                   'service_role', %s, 'SELECT')""",
                        (f"public.{CAPABILITIES}",))
        assert _one(db, f"SELECT count(*) FROM public.{CAPABILITIES}") == 0

    def test_nine_guard_functions_carry_the_branch_once(self, db):
        for function in (
                "reject_mlc2_immutable_mutation",
                "reject_coach_guidance_d3_mutation_v1",
                "reject_confident_moment_mutation_v1",
                "reject_mlc3_general_service_mutation_v1",
                "reject_canonical_feedback_mutation",
                "reject_coach_inline_mutation_v1",
                "reject_immutable_feedback_mutation",
                "guard_exercise_practice_transcription_run_v1",
                "reject_retired_direction_write_v1"):
            definition = _one(db, "SELECT pg_get_functiondef(%s::regprocedure)",
                              (f"public.{function}()",))
            assert definition.count(MARKER) == 1, function

    def test_each_delete_comes_before_every_row_it_points_at(self, db):
        """Every foreign key between two tables the purge deletes (with all
        rules in force and v1.5 registered) points from an earlier delete to
        a later one, so no delete is refused by a row the purge has not yet
        reached. A cascade is the database's own backstop and is left out."""
        orders: dict[str, list[int]] = {}
        for dependency in DEPENDENCIES:
            if dependency.disposition == "delete":
                orders.setdefault(dependency.relation, []).append(
                    dependency.delete_order)
        edges = _one(db, """
            SELECT jsonb_agg(jsonb_build_array(child.relname, parent.relname,
                                               con.confdeltype))
              FROM pg_constraint con
              JOIN pg_class child ON child.oid = con.conrelid
              JOIN pg_class parent ON parent.oid = con.confrelid
              JOIN pg_namespace n ON n.oid = child.relnamespace
             WHERE con.contype = 'f' AND n.nspname = 'public'
               AND con.conrelid <> con.confrelid""")
        wrong = sorted({
            (child, max(orders[child]), parent, min(orders[parent]))
            for child, parent, action in edges
            if child in orders and parent in orders and action != "c"
            and max(orders[child]) >= min(orders[parent])
        })
        assert wrong == []

    def test_nothing_cascades_into_a_table_v1_5_deletes(self, db):
        """A cascade or a SET NULL into these tables would change rows the
        inventory never counted; there is none."""
        actions = _one(db, """
            SELECT coalesce(jsonb_agg(DISTINCT parent.relname || '<-'
                                      || child.relname), '[]'::jsonb)
              FROM pg_constraint con
              JOIN pg_class child ON child.oid = con.conrelid
              JOIN pg_class parent ON parent.oid = con.confrelid
             WHERE con.contype = 'f' AND con.confdeltype IN ('c', 'n', 'd')
               AND parent.relname = ANY(%s)""", (V1_5_DELETES,))
        assert actions == []

    def test_the_project_graph_lists_the_projects_memberships(self, db, rules):
        subject = _v3(db, takes._account_with_one_take(db))
        graph = _one(db, "SELECT public.resolve_phase1_purge_project_graph_v1(%s, %s)",
                     (subject["principal"], subject["project"]))
        assert graph["feedback_v3_membership_ids"] == [subject["membership"]]


# ── each guard opens for exactly the named row ──────────────────────────


GUARDS = (
    ("reject_mlc2_immutable_mutation", "MLC canonical records are append-only"),
    ("reject_coach_guidance_d3_mutation_v1", "COACH_GUIDANCE_D3_APPEND_ONLY"),
    ("reject_confident_moment_mutation_v1", "CONFIDENT_MOMENT_APPEND_ONLY"),
    ("reject_mlc3_general_service_mutation_v1", "MLC3_GENERAL_SERVICE_APPEND_ONLY"),
    ("reject_canonical_feedback_mutation", "canonical feedback evidence is append-only"),
    ("reject_coach_inline_mutation_v1", "COACH_INLINE_EXERCISE_APPEND_ONLY"),
    ("reject_immutable_feedback_mutation", "immutable feedback evidence cannot be changed"),
    ("guard_exercise_practice_transcription_run_v1", "PRACTICE_TRANSCRIPTION_RUN_IMMUTABLE"),
    ("reject_retired_direction_write_v1", "RETIRED_DIRECTION_PIPELINE_WRITE_FORBIDDEN"),
    ("guard_phase1_purge_service_delete_v1", "PURGE_DELETE_NOT_NAMED"),
)


@pytest.fixture
def running_purge(db, v1_5, fake_storage):
    """A real account purge, frozen and running (`in_progress`), as the
    purge's own freeze leaves it before it resolves anything."""
    subject = takes._account_with_one_take(db)
    DataPurgeOrchestrator(_Database(db)).freeze_inventory(subject["request"])
    assert _state(db, subject["request"]) == "in_progress"
    rule = _one(db, """SELECT id FROM public.data_retention_rules
                        WHERE rule_code = 'product-records-v1'""")
    return {**subject, "rule": str(rule)}


@pytest.fixture
def probes(db):
    """One throwaway table per guard function, its rows owned by two people;
    the guard attached as the real tables attach it. Its owner column is
    deliberately no subject column, so no purge's catalog audit sees it."""
    made = []
    for index, (function, _message) in enumerate(GUARDS):
        table = f"v15_probe_{index}"
        with db.cursor() as cur:
            cur.execute(f"""
                DROP TABLE IF EXISTS public.{table};
                CREATE TABLE public.{table} (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    owner_ref UUID NOT NULL);
                CREATE TRIGGER {table}_guard BEFORE DELETE ON public.{table}
                    FOR EACH ROW EXECUTE FUNCTION public.{function}();
                GRANT SELECT, DELETE ON public.{table} TO service_role""")
        made.append(table)
    yield made
    with db.cursor() as cur:
        for table in made:
            cur.execute(f"DROP TABLE IF EXISTS public.{table}")


def _name_in_inventory(db, purge: dict, table: str, owner: str,
                       state: str = "pending") -> None:
    """A target of the running purge for the probe table, exactly as the
    freeze writes a v1.5 delete (as the owner: the service never writes
    these rows, 0310)."""
    code = f"probe_{table}"
    with db.cursor() as cur:
        cur.execute("""
            INSERT INTO public.data_purge_targets (
                purge_request_id, target_kind, target_ref, resolver_version,
                state, initial_match_count, metadata)
            VALUES (%s, 'database_row', %s, 'phase1-purge-resolver-v4', %s, 1,
                    %s)""",
            (purge["request"], f"dependency:{code}", state,
             psycopg2.extras.Json({
                 "dependency_code": code, "relation": table,
                 "selector_column": "owner_ref", "locator_kind": "principal",
                 "locator_values": [owner], "disposition": "delete",
                 "delete_order": 300, "retention_schedule": "1.5",
                 "retention_rule_id": purge["rule"]})))


class TestEachGuardOpensForExactlyTheNamedRow:

    @pytest.mark.parametrize("index", range(len(GUARDS)))
    def test_only_the_named_row_goes_and_only_while_v1_5_is_registered(
            self, db, running_purge, probes, index):
        table, (function, message) = probes[index], GUARDS[index]
        named, other = str(uuid.uuid4()), str(uuid.uuid4())
        with db.cursor() as cur:
            cur.execute(f"""INSERT INTO public.{table} (owner_ref)
                            VALUES (%s), (%s), (%s)""", (named, named, other))
        delete = f"DELETE FROM public.{table} WHERE owner_ref = %s"

        # Not named by any purge: refused, with the guard's own message.
        with pytest.raises(psycopg2.Error, match=message):
            _as_service(db, delete, (named,))
        _name_in_inventory(db, running_purge, table, named)
        with pytest.raises(psycopg2.Error, match=message):
            _as_service(db, delete, (other,))
        # Named, but v1.5 not registered: refused.
        _unregister_v1_5(db)
        with pytest.raises(psycopg2.Error, match=message):
            _as_service(db, delete, (named,))
        _register_v1_5(db)
        # Named, registered, the rule active: exactly those rows go.
        _as_service(db, delete, (named,))
        assert _one(db, f"SELECT count(*) FROM public.{table} WHERE owner_ref = %s",
                    (named,)) == 0
        assert _one(db, f"SELECT count(*) FROM public.{table} WHERE owner_ref = %s",
                    (other,)) == 1
        assert function

    def test_a_resolved_target_or_a_withdrawn_rule_opens_nothing(
            self, db, running_purge, probes):
        table, (_function, message) = probes[0], GUARDS[0]
        named = str(uuid.uuid4())
        delete = f"DELETE FROM public.{table} WHERE owner_ref = %s"
        with db.cursor() as cur:
            cur.execute(f"INSERT INTO public.{table} (owner_ref) VALUES (%s)",
                        (named,))
        # A target already resolved names the row: refused.
        _name_in_inventory(db, running_purge, table, named, state="deleted")
        with pytest.raises(psycopg2.Error, match=message):
            _as_service(db, delete, (named,))
        # A pending one, under a rule since withdrawn: refused.
        with db.cursor() as cur:
            cur.execute("""DELETE FROM public.data_purge_targets
                            WHERE purge_request_id = %s AND target_ref = %s""",
                        (running_purge["request"], f"dependency:probe_{table}"))
        _name_in_inventory(db, running_purge, table, named)
        with db.cursor() as cur:
            cur.execute("""UPDATE public.data_retention_rules SET active = false
                            WHERE rule_code = 'product-records-v1'""")
        try:
            with pytest.raises(psycopg2.Error, match=message):
                _as_service(db, delete, (named,))
        finally:
            with db.cursor() as cur:
                cur.execute("""UPDATE public.data_retention_rules SET active = true
                                WHERE rule_code = 'product-records-v1'""")
        _as_service(db, delete, (named,))
        assert _one(db, f"SELECT count(*) FROM public.{table}") == 0

    def test_the_owner_still_deletes_from_a_table_that_had_no_guard(self, db, probes):
        """The new guard binds the service role only: the owner's own
        functions keep what they had."""
        table = probes[-1]
        with db.cursor() as cur:
            cur.execute(f"INSERT INTO public.{table} (owner_ref) VALUES (%s)",
                        (str(uuid.uuid4()),))
            cur.execute(f"DELETE FROM public.{table}")
        assert _one(db, f"SELECT count(*) FROM public.{table}") == 0


# ── P1: the nine live records ───────────────────────────────────────────


def _correction_decision(db, rows: dict) -> str:
    """The speaker's accept/keep answer to a rewrite, as the canonical
    dual-write records it (0296, 0321): kept as an empty receipt by the
    lineage tombstone (N12), and pointing at the membership item."""
    decision = str(uuid.uuid4())
    _replica(db, [("""
        INSERT INTO public.correction_decisions (
            id, evidence_span_id, value, rater_id, taxonomy_version,
            idempotency_key, candidate_id, feedback_membership_id,
            feedback_exposure_id, candidate_output_sha256,
            candidate_output_contract_version)
        VALUES (%s, gen_random_uuid(), 'keep_original', %s,
                'feedback-taxonomy-v1', %s, %s, %s, %s, %s,
                'feedback-candidate-output-v1')""",
        (decision, rows["user"], _sha(), rows["candidate"],
         rows["membership"], rows["exposure"], _sha()))])
    return decision


class TestTheLiveRecordsWaitForV1_5:

    def test_without_v1_5_an_account_erasure_stops_on_them_and_deletes_nothing(
            self, db, rules, fake_storage):
        rows = _v3(db, takes._account_with_one_take(db))

        DataPurgeOrchestrator(_Database(db)).run(rows["request"])

        assert _state(db, rows["request"]) == "review_required"
        assert _left(db, rows["request"]) == {
            code: "EXPLICIT_RESOLVER_REQUIRED" for code in P1}
        assert _v3_rows(db, rows) == ALL_THERE
        assert not fake_storage, "nothing may be erased before review"
        with pytest.raises(psycopg2.Error,
                           match="MLC canonical records are append-only"):
            _as_service(db, """DELETE FROM public.feedback_v3_owner_responses
                                WHERE id = %s""", (rows["response"],))

    def test_without_v1_5_a_project_erasure_stops_on_them(
            self, db, rules, fake_storage):
        rows = _v3(db, takes._account_with_one_take(db))
        _request, purge = projects._confirmed_project_deletion(db, rows)

        ProjectPurgeOrchestrator(_Database(db)).run(purge)

        assert _state(db, purge) == "review_required"
        assert set(_left(db, purge)) == set(P1)
        assert _v3_rows(db, rows) == ALL_THERE
        assert not fake_storage


class TestWithV1_5TheLiveRecordsGo:

    def test_the_account_erasure_deletes_them_and_finishes(
            self, db, v1_5, fake_storage):
        rows = _v3(db, takes._account_with_one_take(db))
        stranger = _v3(db, takes._account_with_one_take(db))

        DataPurgeOrchestrator(_Database(db)).run(rows["request"])

        assert takes._left_for_review(db, rows["request"]) == []
        assert _state(db, rows["request"]) == "done"
        assert _v3_rows(db, rows) == ALL_GONE
        for code in P1:
            assert _target(db, rows["request"], code) == {
                "state": "deleted", "reason": None, "disposition": "delete",
                "rule": "product-records-v1"}, code
        assert _v3_rows(db, stranger) == ALL_THERE

    def test_outside_a_running_purge_the_guard_still_refuses(self, db, v1_5):
        rows = _v3(db, takes._account_with_one_take(db))
        with pytest.raises(psycopg2.Error,
                           match="MLC canonical records are append-only"):
            _as_service(db, """DELETE FROM public.feedback_v3_owner_responses
                                WHERE id = %s""", (rows["response"],))
        with pytest.raises(psycopg2.Error, match="CONFIDENT_MOMENT_APPEND_ONLY"):
            _as_service(db, """DELETE FROM public.ideal_text_user_edit_cas_operations
                                WHERE acquisition_principal_id = %s""",
                        (rows["principal"],))
        assert _v3_rows(db, rows) == ALL_THERE

    def test_a_project_erasure_deletes_that_projects_and_keeps_the_others(
            self, db, v1_5, fake_storage):
        erased = _v3(db, takes._account_with_one_take(db))
        kept = projects._second_project(db, erased)
        kept = _v3(db, {**kept, "attempt": v1_4._phase1_attempt(
            db, erased["principal"], kept["project"])})
        _request, purge = projects._confirmed_project_deletion(db, erased)

        ProjectPurgeOrchestrator(_Database(db)).run(purge)

        assert takes._left_for_review(db, purge) == []
        assert _state(db, purge) == "done"
        assert _v3_rows(db, erased) == ALL_GONE
        assert _v3_rows(db, kept) == ALL_THERE
        # The answers name only their membership: reached through the
        # project's memberships, which the project graph now lists.
        assert _target(db, purge, "feedback_v3_owner_responses")["state"] == "deleted"
        selector = _one(db, """
            SELECT metadata ->> 'selector_column' FROM public.data_purge_targets
             WHERE purge_request_id = %s
               AND target_ref = 'dependency:feedback_v3_owner_responses'""",
            (purge,))
        assert selector == "membership_id"


class TestARowThePurgeKeepsStopsTheErasure:

    def test_a_kept_decision_on_an_item_stops_everything_before_any_delete(
            self, db, v1_5, fake_storage):
        """The speaker's answer to a rewrite is kept as an empty receipt
        (N12) and points at the V3 item ON DELETE RESTRICT. Deleting the item
        would fail part-way; the check stops the erasure before it starts,
        and v1.5 leaves the question to the founder."""
        rows = _v3(db, takes._account_with_one_take(db))
        decision = _correction_decision(db, rows)

        DataPurgeOrchestrator(_Database(db)).run(rows["request"])

        assert _state(db, rows["request"]) == "review_required"
        assert _left(db, rows["request"]) == {
            "feedback_v3_membership_items": "KEPT_ROWS_STILL_POINT_HERE"}
        blocked = _one(db, """
            SELECT metadata -> 'blocked_by' FROM public.data_purge_targets
             WHERE purge_request_id = %s
               AND target_ref = 'dependency:feedback_v3_membership_items'""",
            (rows["request"],))
        assert blocked == {"public.correction_decisions": 1}
        assert _v3_rows(db, rows) == ALL_THERE
        assert _one(db, "SELECT count(*) FROM public.correction_decisions WHERE id = %s",
                    (decision,)) == 1
        assert not fake_storage, "nothing may be erased before review"


# ── P2-P5 on the legacy tables ──────────────────────────────────────────


def _legacy_tables(db) -> None:
    """The legacy tables this lane never created, laid down as the
    migrations that created them do (0007, 0008, 0054, 0130, 0168, 0245),
    with the retired-write guard production puts on the reflection clips
    (0310) and Supabase's default grants; then 0429 once more, as
    production applies it over them. Two departures, named: the reference
    video's draft column keeps no foreign key (this lane has no drafts
    table), and the review annotations' id defaults to gen_random_uuid()
    (no uuid-ossp here)."""
    with db.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.arc_purchases (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                arc_id UUID NOT NULL, user_id UUID NOT NULL,
                kind TEXT NOT NULL DEFAULT 'paid',
                source TEXT NOT NULL DEFAULT 'stripe', currency TEXT,
                amount_minor INTEGER, stripe_session_id TEXT,
                delivered_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                credits_charged INTEGER NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_arc_purchases_arc
                ON public.arc_purchases (arc_id);
            CREATE TABLE IF NOT EXISTS public.admin_uploaded_reference_videos (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                draft_id UUID,
                user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
                session_id UUID REFERENCES public.v2_sessions(id) ON DELETE SET NULL,
                storage_path TEXT NOT NULL, source_video_url TEXT,
                transcript_text TEXT,
                transcription_status TEXT NOT NULL DEFAULT 'pending',
                transcription_error TEXT, title TEXT,
                feature_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                tags TEXT[] NOT NULL DEFAULT '{}'::text[],
                is_universal BOOLEAN NOT NULL DEFAULT false,
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_by UUID REFERENCES auth.users(id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
            CREATE TABLE IF NOT EXISTS public.reflection_clips (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL, snippet_id UUID NOT NULL,
                take_session_id UUID, arc_id UUID,
                machine_flagged BOOLEAN NOT NULL DEFAULT FALSE,
                recording_kind TEXT, named_emotion TEXT, topic TEXT,
                start_offset_ms INT, duration_ms INT, transcript TEXT,
                served_at TIMESTAMPTZ, user_vote TEXT, voted_at TIMESTAMPTZ,
                coach_verdict TEXT, verified_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (user_id, snippet_id));
            DROP TRIGGER IF EXISTS reflection_clips_retired_write_guard
                ON public.reflection_clips;
            CREATE TRIGGER reflection_clips_retired_write_guard
                BEFORE INSERT OR UPDATE OR DELETE ON public.reflection_clips
                FOR EACH ROW EXECUTE FUNCTION
                    public.reject_retired_direction_write_v1();
            CREATE TABLE IF NOT EXISTS public.strong_sides_library (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
                session_id UUID NOT NULL, snippet_id UUID NOT NULL,
                note TEXT NOT NULL, tag TEXT NOT NULL, snippet_ref JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (user_id, snippet_id));
            CREATE TABLE IF NOT EXISTS public.recording_reviews (
                session_id UUID PRIMARY KEY
                    REFERENCES public.v2_sessions(id) ON DELETE CASCADE,
                recording_id UUID NULL
                    REFERENCES public.recordings(id) ON DELETE SET NULL,
                overall_quality NUMERIC NULL, confidence_score NUMERIC NULL,
                coach_style_score NUMERIC NULL, notes TEXT NULL,
                reviewer_id UUID NULL REFERENCES auth.users(id) ON DELETE SET NULL,
                rubric_version TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
            CREATE TABLE IF NOT EXISTS public.recording_review_annotations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id UUID NOT NULL
                    REFERENCES public.v2_sessions(id) ON DELETE CASCADE,
                recording_id UUID NOT NULL
                    REFERENCES public.recordings(id) ON DELETE CASCADE,
                start_ms INTEGER NOT NULL CHECK (start_ms >= 0),
                end_ms INTEGER NOT NULL CHECK (end_ms > start_ms),
                label TEXT NOT NULL, notes TEXT NULL,
                reviewer_id UUID NULL REFERENCES auth.users(id) ON DELETE SET NULL,
                rubric_version TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
            GRANT ALL ON public.arc_purchases,
                public.admin_uploaded_reference_videos,
                public.reflection_clips, public.strong_sides_library,
                public.recording_reviews, public.recording_review_annotations
                TO service_role""")
        cur.execute(MIGRATION)


def _user(db, subject: dict) -> str:
    return str(_one(db, "SELECT user_id FROM public.owner_principals WHERE id = %s",
                    (subject["principal"],)))


def _arcs(db, subject: dict, *kinds: str) -> dict:
    """Arc rows of one person, by the paths that wrote them: a founding pass
    (redeemed invite code, no payment), an unlock paid in credits, a manual
    grant (neither)."""
    user = _user(db, subject)
    shapes = {
        "pass": ("founding_pass", "invite_code", None),
        "credits": ("paid", "credits", 25),
        "manual": ("paid", "manual", None),
    }
    made = {}
    for kind in kinds:
        row_kind, source, credits = shapes[kind]
        made[kind] = str(_one(db, """
            INSERT INTO public.arc_purchases (arc_id, user_id, kind, source,
                                              credits_charged)
            VALUES (gen_random_uuid(), %s, %s, %s, %s) RETURNING id""",
            (user, row_kind, source, credits)))
    return made


def _still(db, table: str, ids) -> int:
    return _one(db, f"SELECT count(*) FROM public.{table} WHERE id = ANY(%s::uuid[])",
                (list(ids),))


class TestAnArcPurchaseIsToldApartByItsOwnColumns:

    @pytest.fixture(autouse=True)
    def _tables(self, db, rules):
        _legacy_tables(db)

    def test_without_v1_5_every_arc_row_stops_the_erasure_as_before(
            self, db, fake_storage):
        subject = takes._account_with_one_take(db)
        arcs = _arcs(db, subject, "pass", "credits", "manual")

        DataPurgeOrchestrator(_Database(db)).run(subject["request"])

        assert _left(db, subject["request"]) == {
            "arc_purchases_review": "EXPLICIT_RESOLVER_REQUIRED"}
        assert _one(db, """
            SELECT initial_match_count FROM public.data_purge_targets
             WHERE purge_request_id = %s
               AND target_ref = 'dependency:arc_purchases_review'""",
            (subject["request"],)) == 3
        for code in ("arc_purchases_founding_pass", "arc_purchases_paid"):
            assert _target(db, subject["request"], code) is None
        assert _still(db, "arc_purchases", arcs.values()) == 3

    def test_with_v1_5_a_pass_goes_and_a_paid_arc_is_kept(self, db, fake_storage):
        _register_v1_5(db)
        subject = takes._account_with_one_take(db)
        arcs = _arcs(db, subject, "pass", "credits")

        DataPurgeOrchestrator(_Database(db)).run(subject["request"])

        assert takes._left_for_review(db, subject["request"]) == []
        assert _state(db, subject["request"]) == "done"
        assert _still(db, "arc_purchases", [arcs["pass"]]) == 0
        assert _still(db, "arc_purchases", [arcs["credits"]]) == 1
        assert _target(db, subject["request"], "arc_purchases_founding_pass") == {
            "state": "deleted", "reason": None, "disposition": "delete",
            "rule": "product-records-v1"}
        assert _target(db, subject["request"], "arc_purchases_paid") == {
            "state": "retained", "reason": None, "disposition": "retain",
            "rule": "financial-evidence-v1"}
        assert _target(db, subject["request"], "arc_purchases_review")["state"] == (
            "not_found")

    def test_with_v1_5_a_row_that_is_neither_still_stops_the_erasure(
            self, db, fake_storage):
        _register_v1_5(db)
        subject = takes._account_with_one_take(db)
        arcs = _arcs(db, subject, "pass", "manual")

        DataPurgeOrchestrator(_Database(db)).run(subject["request"])

        assert _left(db, subject["request"]) == {
            "arc_purchases_review": "EXPLICIT_RESOLVER_REQUIRED"}
        assert _still(db, "arc_purchases", arcs.values()) == 2

    def test_a_project_erasure_deletes_the_pass_for_its_arc_only(
            self, db, fake_storage):
        _register_v1_5(db)
        subject = takes._account_with_one_take(db)
        user = _user(db, subject)
        here, elsewhere = (str(_one(db, """
            INSERT INTO public.arc_purchases (arc_id, user_id, kind, source)
            VALUES (%s, %s, 'founding_pass', 'invite_code') RETURNING id""",
            (arc, user))) for arc in (subject["project"], str(uuid.uuid4())))
        _request, purge = projects._confirmed_project_deletion(db, subject)

        ProjectPurgeOrchestrator(_Database(db)).run(purge)

        assert takes._left_for_review(db, purge) == []
        assert _still(db, "arc_purchases", [here]) == 0
        assert _still(db, "arc_purchases", [elsewhere]) == 1


class TestTheConsentSnapshotIsKeptAsEvidence:

    def _snapshot(self, db, subject: dict) -> str:
        snapshot = str(uuid.uuid4())
        _replica(db, [("""
            INSERT INTO public.ml_consent_snapshots (
                id, acquisition_principal_id, grant_event_id,
                consent_policy_version, purpose_state, retention_state,
                snapshot_sha256, take_id)
            VALUES (%s, %s, gen_random_uuid(), 'mlc2-consent-v2',
                    '{"personalized_coaching": true,
                      "pooled_model_improvement": false}', 'eligible', %s, %s)""",
            (snapshot, subject["principal"], _sha(), subject["take"]))])
        return snapshot

    def test_without_v1_5_it_stops_the_erasure_as_before(
            self, db, rules, fake_storage):
        subject = takes._account_with_one_take(db)
        snapshot = self._snapshot(db, subject)

        DataPurgeOrchestrator(_Database(db)).run(subject["request"])

        assert _left(db, subject["request"]) == {
            "ml_consent_snapshots": "EXPLICIT_RESOLVER_REQUIRED"}
        assert _still(db, "ml_consent_snapshots", [snapshot]) == 1

    def test_with_v1_5_it_is_kept_under_consent_evidence(
            self, db, v1_5, fake_storage):
        subject = takes._account_with_one_take(db)
        snapshot = self._snapshot(db, subject)

        DataPurgeOrchestrator(_Database(db)).run(subject["request"])

        assert takes._left_for_review(db, subject["request"]) == []
        assert _state(db, subject["request"]) == "done"
        assert _target(db, subject["request"], "ml_consent_snapshots") == {
            "state": "retained", "reason": None, "disposition": "retain",
            "rule": "consent-evidence-v1"}
        assert _still(db, "ml_consent_snapshots", [snapshot]) == 1


class TestAReferenceVideoGoesUnlessItIsLibraryContent:

    @pytest.fixture(autouse=True)
    def _tables(self, db, rules):
        _legacy_tables(db)

    def _video(self, db, subject: dict, universal: bool) -> str:
        user = _user(db, subject)
        with db.cursor() as cur:
            cur.execute("""INSERT INTO auth.users (id, email) VALUES (%s, %s)
                           ON CONFLICT DO NOTHING""", (user, f"{user}@rehearsal"))
        return str(_one(db, """
            INSERT INTO public.admin_uploaded_reference_videos (
                user_id, session_id, storage_path, is_universal, title)
            VALUES (%s, %s, %s, %s, 'Open with the number') RETURNING id""",
            (user, subject["take"], f"refs/{uuid.uuid4()}.mp4", universal)))

    def _link(self, db, video: str) -> dict:
        return _one(db, """
            SELECT jsonb_build_object('user', user_id, 'session', session_id,
                                      'draft', draft_id, 'title', title)
              FROM public.admin_uploaded_reference_videos WHERE id = %s""",
            (video,))

    def test_0429_lets_the_owner_column_be_empty(self, db):
        assert _one(db, """
            SELECT is_nullable FROM information_schema.columns
             WHERE table_schema = 'public'
               AND table_name = 'admin_uploaded_reference_videos'
               AND column_name = 'user_id'""") == "YES"

    def test_without_v1_5_any_video_stops_the_erasure_as_before(
            self, db, fake_storage):
        subject = takes._account_with_one_take(db)
        video = self._video(db, subject, universal=True)

        DataPurgeOrchestrator(_Database(db)).run(subject["request"])

        assert _left(db, subject["request"]) == {
            "admin_uploaded_reference_review": "EXPLICIT_RESOLVER_REQUIRED"}
        assert self._link(db, video)["user"] == _user(db, subject)

    def test_with_v1_5_a_library_video_stays_and_loses_only_the_speaker(
            self, db, fake_storage):
        _register_v1_5(db)
        subject = takes._account_with_one_take(db)
        video = self._video(db, subject, universal=True)

        DataPurgeOrchestrator(_Database(db)).run(subject["request"])

        assert takes._left_for_review(db, subject["request"]) == []
        assert _state(db, subject["request"]) == "done"
        assert self._link(db, video) == {
            "user": None, "session": None, "draft": None,
            "title": "Open with the number"}
        assert _target(db, subject["request"], "reference_videos_library") == {
            "state": "retained", "reason": None, "disposition": "tombstone",
            "rule": "product-records-v1"}

    def test_with_v1_5_a_video_made_for_the_speaker_stops_for_its_file(
            self, db, fake_storage):
        _register_v1_5(db)
        subject = takes._account_with_one_take(db)
        video = self._video(db, subject, universal=False)

        DataPurgeOrchestrator(_Database(db)).run(subject["request"])

        assert _state(db, subject["request"]) == "review_required"
        assert _left(db, subject["request"]) == {
            video: "REFERENCE_VIDEO_PROVIDER_AND_SHA256_UNRESOLVED"}
        assert _still(db, "admin_uploaded_reference_videos", [video]) == 1
        assert not fake_storage


class TestTheRetiredCorporaWithOneOwnerGo:

    @pytest.fixture(autouse=True)
    def _tables(self, db, rules):
        _legacy_tables(db)

    def _corpora(self, db, subject: dict) -> dict:
        user = _user(db, subject)
        take = subject["take"]
        # The review names its recording; written past the foreign key (no
        # recording row here), so the purge's own recordings step is not
        # what this case is about.
        recording = str(uuid.uuid4())
        ids = {name: str(uuid.uuid4()) for name in ("clip", "side", "annotation")}
        _replica(db, [
            ("""INSERT INTO public.reflection_clips (id, user_id, snippet_id,
                                                    take_session_id, transcript)
                VALUES (%s, %s, gen_random_uuid(), %s, 'We doubled it.')""",
             (ids["clip"], user, take)),
            ("""INSERT INTO public.strong_sides_library (
                    id, user_id, session_id, snippet_id, note, tag)
                VALUES (%s, %s, %s, gen_random_uuid(), 'Strong opening.',
                        'strong')""", (ids["side"], user, take)),
            ("""INSERT INTO public.recording_reviews (session_id, recording_id,
                                                     rubric_version)
                VALUES (%s, %s, 'rubric-v1')""", (take, recording)),
            ("""INSERT INTO public.recording_review_annotations (
                    id, session_id, recording_id, start_ms, end_ms, label,
                    rubric_version)
                VALUES (%s, %s, %s, 0, 900, 'strong_clarity', 'rubric-v1')""",
             (ids["annotation"], take, recording)),
        ])
        return {**ids, "take": take}

    def _rows(self, db, corpora: dict) -> dict:
        return {
            "clip": _still(db, "reflection_clips", [corpora["clip"]]),
            "side": _still(db, "strong_sides_library", [corpora["side"]]),
            "review": _one(db, """SELECT count(*) FROM public.recording_reviews
                                   WHERE session_id = %s""", (corpora["take"],)),
            "annotation": _still(db, "recording_review_annotations",
                                 [corpora["annotation"]]),
        }

    def test_without_v1_5_they_stop_the_erasure_as_before(
            self, db, fake_storage):
        subject = takes._account_with_one_take(db)
        corpora = self._corpora(db, subject)

        DataPurgeOrchestrator(_Database(db)).run(subject["request"])

        assert _left(db, subject["request"]) == {
            code: "EXPLICIT_RESOLVER_REQUIRED" for code in (
                "legacy_reflection_clips", "legacy_strong_sides",
                "legacy_recording_reviews",
                "legacy_recording_review_annotations")}
        assert self._rows(db, corpora) == {
            "clip": 1, "side": 1, "review": 1, "annotation": 1}

    def test_with_v1_5_they_go_with_the_account(self, db, fake_storage):
        _register_v1_5(db)
        subject = takes._account_with_one_take(db)
        corpora = self._corpora(db, subject)

        DataPurgeOrchestrator(_Database(db)).run(subject["request"])

        assert takes._left_for_review(db, subject["request"]) == []
        assert _state(db, subject["request"]) == "done"
        assert self._rows(db, corpora) == {
            "clip": 0, "side": 0, "review": 0, "annotation": 0}
        for code in ("legacy_reflection_clips", "legacy_strong_sides",
                     "legacy_recording_reviews",
                     "legacy_recording_review_annotations"):
            assert _target(db, subject["request"], code)["rule"] == (
                "product-records-v1"), code

    def test_the_retired_write_guard_still_refuses_outside_a_purge(self, db):
        with pytest.raises(psycopg2.Error,
                           match="RETIRED_DIRECTION_PIPELINE_WRITE_FORBIDDEN"):
            _as_service(db, """INSERT INTO public.reflection_clips (user_id, snippet_id)
                               VALUES (gen_random_uuid(), gen_random_uuid())""")


# ── the founder's two scripts ───────────────────────────────────────────


class TestTheRegistration:

    def test_it_refuses_until_it_is_signed(self, db, rules):
        with pytest.raises(psycopg2.Error, match="RETENTION_SCHEDULE_V1_5_UNSIGNED"):
            with db.cursor() as cur:
                cur.execute(SCRIPT)
        assert _one(db, """SELECT count(*) FROM public.processing_legal_artifacts
                            WHERE artifact_kind = 'retention_schedule'
                              AND version = '1.5'""") == 0

    def test_it_refuses_while_a_rule_it_points_at_is_inactive(self, db, rules):
        with db.cursor() as cur:
            cur.execute("""UPDATE public.data_retention_rules SET active = false
                            WHERE rule_code = 'financial-evidence-v1'""")
        try:
            with pytest.raises(psycopg2.Error,
                               match="RETENTION_SCHEDULE_V1_5_RULES_MISSING"):
                _register_v1_5(db)
        finally:
            _earlier_rules(db)

    def test_it_registers_once_and_never_edits_the_row(self, db, rules):
        _register_v1_5(db)
        _register_v1_5(db)
        row = _one(db, """
            SELECT jsonb_build_object('sha', sha256, 'key', object_key,
                                      'day', approved_at::date::text,
                                      'rules', metadata -> 'rules_seeded')
              FROM public.processing_legal_artifacts
             WHERE artifact_kind = 'retention_schedule' AND version = '1.5'""")
        assert row == {"sha": STAND_IN_HASH,
                       "key": "phase1-2026.1/legal/retention-schedule-v1.5.pdf",
                       "day": "2026-10-05", "rules": []}
        with pytest.raises(psycopg2.Error,
                           match="RETENTION_SCHEDULE_VERSION_CONFLICT"):
            with db.cursor() as cur:
                cur.execute(SCRIPT.replace(PLACEHOLDER, "6" * 64))


class TestTheCount:

    def test_one_row_per_question_and_a_missing_table_says_so(self, db):
        script = COUNTS.read_text()
        with db.cursor() as cur:
            cur.execute("BEGIN READ ONLY")
            try:
                cur.execute(script)
                rows = cur.fetchall()
            finally:
                cur.execute("ROLLBACK")
        assert len(rows) == script.count("\n    (")
        by_table = {}
        for section, table, count, question in rows:
            by_table.setdefault(table, []).append((section, count, question))
        for table, answers in by_table.items():
            present = _one(db, "SELECT to_regclass(%s) IS NOT NULL",
                           (f"public.{table}",))
            for _section, count, question in answers:
                if present:
                    assert isinstance(count, int) and count >= 0, table
                else:
                    assert count is None, table
                    assert question == "table not present in this database"
        assert by_table["confident_moment_text_update_capabilities"][0][1] == 0
