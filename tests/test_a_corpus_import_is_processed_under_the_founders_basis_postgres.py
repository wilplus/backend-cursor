"""A corpus import is processed under the founder's corpus basis, on a
disposable database (0435; founder 2026-10-07, panel answer CO2, decisions
log N58).

Pins, by executing the real functions:

  * the basis: one N58 row, the founder's note, never pooled; applying the
    file again changes nothing; retire-only (no other change, no removal);
  * an import registered by the route gets a permit that names the basis
    (id and N58) and the session; its events land in the corpus ledger and
    nothing lands in the Phase-1 one;
  * refused: an unregistered import, a user's Take, a guest's Take, a forged
    source flag on an owned Take, a registered import later given an owner,
    a recording another session owns, a recording a person handed over
    through the Phase-1 intake, an operation the basis does not cover, no
    basis in force;
  * the other way round: the Phase-1 permit writer refuses a corpus import
    under any principal (the importing coach's included), and still issues
    an ordinary Take's permit to its owner;
  * the service key cannot write the corpus tables, only call the three
    entry points; the browser roles can do neither.
"""
from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.errors
import pytest

from tests import test_phase1_processing_postgres as _phase1
from tests.test_phase1_processing_postgres import (
    _accept, _intake, _permit, _principal,
)

# The active Phase-1 policy the binding suite registers (or reuses), so a
# person's receipt can exist beside an import.
policy = _phase1.policy

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)
MIGRATION = (Path(__file__).resolve().parents[1] / "migrations"
             / "a_corpus_import_is_processed_under_the_founders_basis.sql")
BASIS_ID = "0d580435-5858-4058-8058-000000000058"


@pytest.fixture(scope="module")
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


@contextmanager
def rolled_back():
    """A second connection whose every change is rolled back."""
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.rollback()
        conn.close()


def _one(db, sql, args=()):
    with db.cursor() as cur:
        cur.execute(sql, args)
        row = cur.fetchone()
        return row[0] if row else None


def _session(db, *, source="training_import", owner=None, project=None,
             user_id=None) -> str:
    return _one(db, """
        INSERT INTO public.v2_sessions (
            id, arc_id, user_id, take_index, owner_principal_id, project_id,
            source)
        VALUES (gen_random_uuid(), gen_random_uuid(), %s, 1, %s, %s, %s)
        RETURNING id::text""",
        (user_id or str(uuid.uuid4()), owner, project, source))


def _recording(db, session_id, *, origin="admin_import", rid=None) -> str:
    return _one(db, """
        INSERT INTO public.recordings (id, session_v2_id, recording_origin)
        VALUES (%s, %s, %s) RETURNING id::text""",
        (rid or str(uuid.uuid4()), session_id, origin))


def _import(db) -> tuple:
    """What the coach import route writes: an ownerless training_import
    session and its admin_import recording."""
    sid = _session(db)
    return sid, _recording(db, sid)


def _register(db, sid, rid) -> dict:
    return _one(db, "SELECT public.register_corpus_import_v1(%s, %s)", (sid, rid))


def _corpus_permit(db, sid, rid, *, operation="transcription", key=None):
    return _one(db, """
        SELECT public.issue_corpus_provider_permit_v1(
            %s, %s, 'openai', %s, %s::jsonb, %s, 900)""",
        (sid, rid, operation,
         json.dumps({"content": ["audio_bytes"],
                     "purpose": "transcription_feedback"}),
         key or f"corpus-{uuid.uuid4()}"))


def _refused(db, code, call, *args, **kwargs):
    with pytest.raises(psycopg2.errors.RaiseException) as raised:
        call(db, *args, **kwargs)
    assert code in str(raised.value), str(raised.value)


# ── the basis ──────────────────────────────────────────────────────────────

def test_the_founders_basis_is_recorded_once(db):
    with db.cursor() as cur:
        cur.execute("""
            SELECT id::text, decided_on::text, recorded_by, legal_basis,
                   founder_note, covers_source, pooled_learning_eligible,
                   retired_at
              FROM public.corpus_processing_bases WHERE decision_ref = 'N58'""")
        rows = cur.fetchall()
    assert len(rows) == 1
    (basis_id, decided_on, recorded_by, legal_basis, note, covers, pooled,
     retired) = rows[0]
    assert basis_id == BASIS_ID and decided_on == "2026-10-07"
    assert recorded_by == "founder" and covers == "training_import"
    assert legal_basis == "legal basis recorded by the founder, agreed with counsel"
    assert note.startswith("no need for license check pls;")
    assert note.endswith("it is my executive decision")
    assert pooled is False and retired is None


def test_applying_it_again_changes_nothing(db):
    sid, rid = _import(db)
    _register(db, sid, rid)
    before = _one(db, "SELECT count(*) FROM public.corpus_import_registrations")
    with db.cursor() as cur:
        cur.execute(MIGRATION.read_text())
    assert _one(db, "SELECT count(*) FROM public.corpus_processing_bases") == 1
    assert _one(db, "SELECT count(*) FROM public.corpus_import_registrations") == before
    assert _one(db, "SELECT count(*) FROM pg_trigger WHERE tgname = "
                    "'corpus_processing_bases_retire_only'") == 1


def test_a_basis_is_only_ever_retired():
    with rolled_back() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation,
                           match="CORPUS_BASIS_IMMUTABLE"):
            cur.execute("UPDATE public.corpus_processing_bases "
                        "SET legal_basis = 'x' WHERE decision_ref = 'N58'")
    for statement in ("DELETE FROM public.corpus_processing_bases",
                      "TRUNCATE public.corpus_processing_bases CASCADE"):
        with rolled_back() as cur:
            with pytest.raises(psycopg2.errors.CheckViolation,
                               match="CORPUS_BASIS_IMMUTABLE"):
                cur.execute(statement)
    with rolled_back() as cur:
        cur.execute("UPDATE public.corpus_processing_bases "
                    "SET retired_at = now() WHERE decision_ref = 'N58'")
        assert cur.rowcount == 1


def test_a_retirement_takes_effect_at_once():
    # retired_at is when it was retired, never a date ahead (HO-13 finding 1).
    with rolled_back() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation,
                           match="CORPUS_BASIS_IMMUTABLE"):
            cur.execute("UPDATE public.corpus_processing_bases SET retired_at "
                        "= now() + interval '1 day' WHERE decision_ref = 'N58'")


def test_only_one_basis_is_ever_in_force():
    with rolled_back() as cur:
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("""
                INSERT INTO public.corpus_processing_bases (
                    id, decision_ref, decided_on, recorded_by, legal_basis,
                    founder_note, covers_source)
                VALUES (gen_random_uuid(), 'N99', CURRENT_DATE, 'founder',
                        'another basis', 'another note', 'training_import')""")


# ── a registered import is permitted under N58 ─────────────────────────────

def test_a_registered_import_is_permitted_under_n58(db):
    sid, rid = _import(db)
    registration = _register(db, sid, rid)
    assert registration["basis_decision_ref"] == "N58"
    assert registration["basis_id"] == BASIS_ID
    assert _register(db, sid, rid)["registered_at"] == registration["registered_at"]

    permit = _corpus_permit(db, sid, rid)
    assert permit["basis_decision_ref"] == "N58" and permit["basis_id"] == BASIS_ID
    assert permit["session_id"] == sid and permit["recording_id"] == rid
    assert permit["operation_kind"] == "transcription"
    # A permit must name the registered recording (HO-13).
    _refused(db, "CORPUS_IMPORT_UNREGISTERED", _corpus_permit, sid, None)

    for event in ("started", "completed"):
        _one(db, "SELECT public.record_corpus_provider_operation_v1("
                 "%s, %s, NULL, NULL, '{}'::jsonb)", (permit["permit_id"], event))
    with db.cursor() as cur:
        cur.execute("SELECT status, basis_decision_ref, session_id::text, "
                    "pooled_learning_eligible FROM public.corpus_provider_permits "
                    "WHERE id = %s", (permit["permit_id"],))
        assert cur.fetchone() == ("used", "N58", sid, False)
    # Nothing in the Phase-1 ledger: no snapshot, no person's permit.
    assert _one(db, "SELECT count(*) FROM public.processing_authorization_snapshots "
                    "WHERE source_take_id = %s OR source_recording_id = %s",
                (sid, rid)) == 0


def test_a_registration_names_one_recording(db):
    sid, rid = _import(db)
    _register(db, sid, rid)
    other = _recording(db, sid)
    _refused(db, "CORPUS_IMPORT_CONFLICT", _register, sid, other)
    _refused(db, "CORPUS_IMPORT_UNREGISTERED", _corpus_permit, sid, other)


# ── what the corpus basis never authorizes ─────────────────────────────────

def test_an_unregistered_import_is_refused(db):
    sid, rid = _import(db)
    _refused(db, "CORPUS_IMPORT_UNREGISTERED", _corpus_permit, sid, rid)


def test_a_users_take_is_refused(db, policy):
    owner = _principal(db)
    _accept(db, policy, owner)
    project = _one(db, """
        INSERT INTO public.projects (id, owner_principal_id, display_name)
        VALUES (gen_random_uuid(), %s, 'pitch') RETURNING id::text""", (owner,))
    sid = _session(db, source="audit_upload", owner=owner, project=project)
    rid = _recording(db, sid, origin=None)
    _refused(db, "CORPUS_SOURCE_NOT_IMPORT", _register, sid, rid)
    _refused(db, "CORPUS_IMPORT_UNREGISTERED", _corpus_permit, sid, rid)
    # Its own owner still gets its Phase-1 permit: 0435 changed nothing there.
    assert _permit(db, owner, sid, None)["operation_kind"] == "transcription"


def test_a_guests_take_is_refused(db):
    guest = _principal(db, guest=True)
    sid = _session(db, source="interview", owner=guest)
    rid = _recording(db, sid, origin=None)
    _refused(db, "CORPUS_SOURCE_NOT_IMPORT", _register, sid, rid)


def test_a_forged_source_flag_on_an_owned_take_is_refused(db):
    owner = _principal(db)
    sid = _session(db, source="training_import", owner=owner)
    rid = _recording(db, sid)
    _refused(db, "CORPUS_SESSION_HAS_OWNER", _register, sid, rid)


def test_an_import_given_an_owner_later_is_refused(db):
    sid, rid = _import(db)
    _register(db, sid, rid)
    _one(db, "UPDATE public.v2_sessions SET owner_principal_id = %s "
             "WHERE id = %s RETURNING id", (_principal(db), sid))
    _refused(db, "CORPUS_SESSION_HAS_OWNER", _corpus_permit, sid, rid)


def test_a_flag_flipped_back_is_refused(db):
    sid, rid = _import(db)
    _register(db, sid, rid)
    _one(db, "UPDATE public.v2_sessions SET source = 'audit_upload' "
             "WHERE id = %s RETURNING id", (sid,))
    _refused(db, "CORPUS_SOURCE_NOT_IMPORT", _corpus_permit, sid, rid)


def test_a_recording_that_is_not_the_imports_is_refused(db):
    sid = _session(db)
    elsewhere = _session(db)
    _refused(db, "CORPUS_RECORDING_NOT_IMPORT", _register, sid,
             _recording(db, elsewhere))
    _refused(db, "CORPUS_RECORDING_NOT_IMPORT", _register, sid,
             _recording(db, sid, origin="homework"))
    _refused(db, "CORPUS_RECORDING_NOT_IMPORT", _register, sid, str(uuid.uuid4()))


def test_a_recording_a_person_handed_over_is_refused(db, policy):
    person = _principal(db, guest=True)
    _accept(db, policy, person)
    acquired = _intake(db, person)["recording"]
    sid = _session(db)
    _recording(db, sid, rid=acquired)
    _refused(db, "CORPUS_RECORDING_ACQUIRED", _register, sid, acquired)


def test_an_operation_the_basis_does_not_cover_is_refused(db):
    sid, rid = _import(db)
    _register(db, sid, rid)
    _refused(db, "CORPUS_OPERATION_NOT_COVERED", _corpus_permit, sid, rid,
             operation="coach_delivery")


def test_with_no_basis_in_force_nothing_is_permitted(db):
    sid, rid = _import(db)
    _register(db, sid, rid)
    fresh, fresh_rid = _import(db)
    with rolled_back() as cur:
        cur.execute("UPDATE public.corpus_processing_bases "
                    "SET retired_at = now() WHERE decision_ref = 'N58'")
        with pytest.raises(psycopg2.errors.RaiseException,
                           match="CORPUS_BASIS_ABSENT"):
            cur.execute("SELECT public.issue_corpus_provider_permit_v1("
                        "%s, %s, 'openai', 'transcription', '{}'::jsonb, %s, 900)",
                        (sid, rid, f"corpus-{uuid.uuid4()}"))
    with rolled_back() as cur:
        cur.execute("UPDATE public.corpus_processing_bases "
                    "SET retired_at = now() WHERE decision_ref = 'N58'")
        with pytest.raises(psycopg2.errors.RaiseException,
                           match="CORPUS_BASIS_ABSENT"):
            cur.execute("SELECT public.register_corpus_import_v1(%s, %s)",
                        (fresh, fresh_rid))
    # Rolled back: the basis is in force again.
    assert _corpus_permit(db, sid, rid)["basis_decision_ref"] == "N58"


# ── the Phase-1 writer refuses a corpus import ─────────────────────────────

def test_the_phase1_writer_refuses_an_import_under_the_importers_receipt(
        db, policy):
    """0355's ownership check is silent for a Take with no owner; 0435 makes
    the writer refuse an import outright, whoever holds the receipt."""
    importer = _principal(db)
    _accept(db, policy, importer)
    sid, rid = _import(db)
    _refused(db, "PROCESSING_SOURCE_IS_CORPUS_IMPORT", _permit, importer, sid, None)
    _register(db, sid, rid)
    _refused(db, "PROCESSING_SOURCE_IS_CORPUS_IMPORT", _permit, importer, None, rid)
    assert _one(db, "SELECT count(*) FROM public.processing_authorization_snapshots "
                    "WHERE acquisition_principal_id = %s", (importer,)) == 0


def test_the_phase1_writer_still_serves_a_guests_own_intake(db, policy):
    guest = _principal(db, guest=True)
    _accept(db, policy, guest)
    source = _intake(db, guest)
    assert _permit(db, guest, source["attempt"],
                   source["recording"])["operation_kind"] == "transcription"


# ── who may write ──────────────────────────────────────────────────────────

TABLES = ("corpus_processing_bases", "corpus_import_registrations",
          "corpus_provider_permits", "corpus_provider_operations")
ENTRY_POINTS = (
    "public.register_corpus_import_v1(uuid,uuid)",
    "public.issue_corpus_provider_permit_v1(uuid,uuid,text,text,jsonb,text,integer)",
    "public.record_corpus_provider_operation_v1(uuid,text,text,text,jsonb)",
)


@pytest.mark.parametrize("table", TABLES)
def test_the_service_key_reads_but_never_writes_the_corpus_tables(db, table):
    for privilege, expected in (("SELECT", True), ("INSERT", False),
                                ("UPDATE", False), ("DELETE", False),
                                ("TRUNCATE", False)):
        assert _one(db, "SELECT has_table_privilege('service_role', %s, %s)",
                    (f"public.{table}", privilege)) is expected, privilege
    for role in ("anon", "authenticated"):
        assert _one(db, "SELECT has_table_privilege(%s, %s, 'SELECT')",
                    (role, f"public.{table}")) is False


def test_only_the_service_key_calls_the_entry_points(db):
    for fn in ENTRY_POINTS:
        assert _one(db, "SELECT has_function_privilege('service_role', %s, "
                        "'EXECUTE')", (fn,)) is True, fn
        for role in ("anon", "authenticated", "public"):
            assert _one(db, "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                        (role, fn)) is False, (role, fn)
        assert _one(db, "SELECT prosecdef FROM pg_proc WHERE oid = %s::regprocedure",
                    (fn,)) is True, fn
        config = _one(db, "SELECT proconfig FROM pg_proc WHERE oid = %s::regprocedure",
                      (fn,))
        assert config and any(c.startswith("search_path=") for c in config), fn
    assert _one(db, "SELECT has_function_privilege('service_role', "
                    "'public.corpus_import_refusal_v1(uuid,uuid)', 'EXECUTE')") is False


def test_a_registration_never_changes(db):
    sid, rid = _import(db)
    _register(db, sid, rid)
    for statement in ("UPDATE public.corpus_import_registrations "
                      "SET registered_via = 'coach_import_route' WHERE session_id = %s",
                      "DELETE FROM public.corpus_import_registrations "
                      "WHERE session_id = %s"):
        with rolled_back() as cur:
            with pytest.raises(psycopg2.errors.CheckViolation,
                               match="CORPUS_REGISTRATION_IMMUTABLE"):
                cur.execute(statement, (sid,))


# ── HO-13: a permit is one exact request, used for one call ────────────────

def _event(db, permit_id, kind):
    return _one(db, "SELECT public.record_corpus_provider_operation_v1("
                    "%s, %s, NULL, NULL, '{}'::jsonb)", (permit_id, kind))


def _permit_with(db, sid, rid, *, provider="openai", manifest=None, key):
    return _one(db, """
        SELECT public.issue_corpus_provider_permit_v1(
            %s, %s, %s, 'transcription', %s::jsonb, %s, 900)""",
        (sid, rid, provider,
         None if manifest is False else json.dumps(manifest or {"content": ["audio_bytes"]}),
         key))


def test_every_request_defining_input_is_required(db):
    sid, rid = _import(db)
    _register(db, sid, rid)
    _refused(db, "CORPUS_PROVIDER_REQUIRED", _permit_with, sid, rid,
             provider="", key=f"k-{uuid.uuid4()}")
    _refused(db, "CORPUS_MANIFEST_REQUIRED", _permit_with, sid, rid,
             manifest=False, key=f"k-{uuid.uuid4()}")


def test_a_replayed_key_returns_its_permit_only_for_the_same_request(db):
    sid, rid = _import(db)
    _register(db, sid, rid)
    key = f"k-{uuid.uuid4()}"
    first = _permit_with(db, sid, rid, key=key)
    assert _permit_with(db, sid, rid, key=key)["permit_id"] == first["permit_id"]
    _refused(db, "IDEMPOTENCY_CONFLICT", _permit_with, sid, rid,
             provider="cloudflare_r2", key=key)
    _refused(db, "IDEMPOTENCY_CONFLICT", _permit_with, sid, rid,
             manifest={"content": ["everything"]}, key=key)


def test_a_permit_serves_one_call_in_order(db):
    sid, rid = _import(db)
    _register(db, sid, rid)
    permit = _corpus_permit(db, sid, rid)["permit_id"]
    _refused(db, "PROVIDER_EVENT_OUT_OF_ORDER", _event, permit, "completed")
    _refused(db, "PROVIDER_EVENT_OUT_OF_ORDER", _event, permit, "deleted")
    _event(db, permit, "started")
    _refused(db, "PROVIDER_PERMIT_INVALID", _event, permit, "started")
    _refused(db, "PROVIDER_EVENT_OUT_OF_ORDER", _event, permit, "cancelled")
    _event(db, permit, "failed")
    for kind in ("started", "completed", "failed", "cancelled"):
        _refused(db, "PROVIDER_", _event, permit, kind)
    _event(db, permit, "deleted")
    with db.cursor() as cur:
        cur.execute("SELECT status, started_at IS NOT NULL, finished_at IS NOT NULL, "
                    "revoked_at IS NULL FROM public.corpus_provider_permits "
                    "WHERE id = %s", (permit,))
        assert cur.fetchone() == ("failed", True, True, True)

    unused = _corpus_permit(db, sid, rid)["permit_id"]
    _event(db, unused, "cancelled")
    _refused(db, "PROVIDER_PERMIT_INVALID", _event, unused, "started")
    with db.cursor() as cur:
        cur.execute("SELECT status, revoked_at IS NOT NULL FROM "
                    "public.corpus_provider_permits WHERE id = %s", (unused,))
        assert cur.fetchone() == ("cancelled", True)


def test_the_provider_ledger_keeps_its_history(db):
    sid, rid = _import(db)
    _register(db, sid, rid)
    permit = _corpus_permit(db, sid, rid)["permit_id"]
    event = _event(db, permit, "started")
    for statement, args in (
        ("UPDATE public.corpus_provider_operations SET error_code = 'x' WHERE id = %s", (event,)),
        ("DELETE FROM public.corpus_provider_operations WHERE id = %s", (event,)),
        ("TRUNCATE public.corpus_provider_operations", ()),
        ("DELETE FROM public.corpus_provider_permits WHERE id = %s", (permit,)),
        ("TRUNCATE public.corpus_provider_permits CASCADE", ()),
    ):
        with rolled_back() as cur:
            with pytest.raises(psycopg2.errors.CheckViolation,
                               match="CORPUS_LEDGER_IMMUTABLE"):
                cur.execute(statement, args)


# ── HO-13b: an older shape or another N58 row stops the migration ──────────

def _shape_guard() -> str:
    """The shape text and its reader, then the guard from the end of the
    file: the reference copy is built (ON COMMIT DROP) and compared."""
    text = MIGRATION.read_text()
    start = text.index("-- ── the four tables, written once")
    helpers = text[start:text.index("$seen$;", start) + len("$seen$;")]
    guard = text.index("DO $$", text.index("-- ── refuse an older shape"))
    return helpers + "\n" + text[guard:text.index("END $$;", guard) + len("END $$;")]


def test_the_shape_guard_passes_on_the_real_schema():
    with rolled_back() as cur:
        cur.execute(_shape_guard())


def test_a_missing_rule_stops_the_migration():
    with rolled_back() as cur:
        cur.execute("ALTER TABLE public.corpus_provider_permits "
                    "DROP CONSTRAINT corpus_provider_permits_never_pooled")
        with pytest.raises(psycopg2.errors.RaiseException,
                           match="CORPUS_SCHEMA_MISMATCH"):
            cur.execute(_shape_guard())


def test_another_n58_row_stops_the_migration():
    with rolled_back() as cur:
        cur.execute("ALTER TABLE public.corpus_processing_bases "
                    "DISABLE TRIGGER corpus_processing_bases_retire_only")
        cur.execute("UPDATE public.corpus_processing_bases "
                    "SET legal_basis = 'something else' WHERE decision_ref = 'N58'")
        with pytest.raises(psycopg2.errors.RaiseException,
                           match="CORPUS_BASIS_SEED_MISMATCH"):
            cur.execute(_shape_guard())


def test_a_permit_cannot_name_a_decision_its_basis_is_not(db):
    sid, rid = _import(db)
    _register(db, sid, rid)
    with rolled_back() as cur:
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute("""
                INSERT INTO public.corpus_provider_permits (
                    basis_id, basis_decision_ref, session_id, recording_id,
                    provider, operation_kind, minimum_data_manifest,
                    expires_at, idempotency_key)
                VALUES (%s, 'N99', %s, %s, 'openai', 'transcription',
                        '{}'::jsonb, now() + interval '5 minutes', %s)""",
                (BASIS_ID, sid, rid, f"k-{uuid.uuid4()}"))


# ── HO-13c: the recording's own session; the guard reads definitions ──────

def test_naming_another_take_beside_an_imports_recording_is_refused(db, policy):
    importer = _principal(db)
    _accept(db, policy, importer)
    _sid, rid = _import(db)                      # never registered
    other = _session(db, source="lab", owner=importer)
    _refused(db, "PROCESSING_SOURCE_IS_CORPUS_IMPORT", _permit,
             importer, other, rid)


def test_a_rule_with_the_right_name_but_another_definition_stops_the_migration():
    with rolled_back() as cur:
        cur.execute("ALTER TABLE public.corpus_provider_permits "
                    "DROP CONSTRAINT corpus_provider_permits_never_pooled")
        cur.execute("ALTER TABLE public.corpus_provider_permits "
                    "ADD CONSTRAINT corpus_provider_permits_never_pooled CHECK (true)")
        with pytest.raises(psycopg2.errors.RaiseException,
                           match="CORPUS_SCHEMA_MISMATCH"):
            cur.execute(_shape_guard())


def test_an_index_that_is_not_partial_stops_the_migration():
    with rolled_back() as cur:
        cur.execute("DROP INDEX public.corpus_processing_bases_one_in_force")
        cur.execute("CREATE UNIQUE INDEX corpus_processing_bases_one_in_force "
                    "ON public.corpus_processing_bases (covers_source, id)")
        with pytest.raises(psycopg2.errors.RaiseException,
                           match="CORPUS_SCHEMA_MISMATCH"):
            cur.execute(_shape_guard())


def test_another_founder_note_stops_the_migration():
    with rolled_back() as cur:
        cur.execute("ALTER TABLE public.corpus_processing_bases "
                    "DISABLE TRIGGER corpus_processing_bases_retire_only")
        cur.execute("UPDATE public.corpus_processing_bases "
                    "SET founder_note = 'another note' WHERE decision_ref = 'N58'")
        with pytest.raises(psycopg2.errors.RaiseException,
                           match="CORPUS_BASIS_SEED_MISMATCH"):
            cur.execute(_shape_guard())


def test_a_permits_request_never_changes(db):
    sid, rid = _import(db)
    _register(db, sid, rid)
    permit = _corpus_permit(db, sid, rid)
    assert permit["status"] == "issued"
    for column, value in (("provider", "'cloudflare_r2'"),
                          ("expires_at", "now() + interval '1 day'"),
                          ("minimum_data_manifest", "'{}'::jsonb")):
        with rolled_back() as cur:
            with pytest.raises(psycopg2.errors.CheckViolation,
                               match="CORPUS_LEDGER_IMMUTABLE"):
                cur.execute(f"UPDATE public.corpus_provider_permits SET {column} = "
                            f"{value} WHERE id = %s", (permit["permit_id"],))


# ── HO-13d: the whole shape is compared, and a retirement waits ────────────

def _guard_refuses(*statements):
    with rolled_back() as cur:
        for statement in statements:
            cur.execute(statement)
        with pytest.raises(psycopg2.errors.RaiseException,
                           match="CORPUS_SCHEMA_MISMATCH"):
            cur.execute(_shape_guard())


def test_a_check_that_still_names_its_column_but_says_less_stops_the_migration():
    _guard_refuses(
        "ALTER TABLE public.corpus_provider_permits "
        "DROP CONSTRAINT corpus_provider_permits_analysis_only",
        "ALTER TABLE public.corpus_provider_permits "
        "ADD CONSTRAINT corpus_provider_permits_analysis_only "
        "CHECK (operation_kind IS NOT NULL)")


def test_a_missing_unique_stops_the_migration():
    _guard_refuses(
        "ALTER TABLE public.corpus_provider_permits "
        "DROP CONSTRAINT corpus_provider_permits_idempotency_key_key")


def test_a_missing_foreign_key_stops_the_migration():
    _guard_refuses(
        "ALTER TABLE public.corpus_provider_permits "
        "DROP CONSTRAINT corpus_provider_permits_session_id_fkey")


def test_another_column_type_stops_the_migration():
    _guard_refuses(
        "ALTER TABLE public.corpus_provider_operations "
        "ALTER COLUMN error_code TYPE varchar(40)")


def test_an_extra_rule_stops_the_migration():
    _guard_refuses(
        "ALTER TABLE public.corpus_import_registrations "
        "ADD CONSTRAINT corpus_import_registrations_extra CHECK (true)")


def test_the_migration_drops_nothing():
    from scripts.migrate import destructive_statements
    assert destructive_statements(MIGRATION.read_text()) == []


def test_the_real_tables_are_not_the_reference_copy():
    with rolled_back() as cur:
        cur.execute(_shape_guard())
        cur.execute("SELECT count(*) FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relpersistence = 'p' "
                    "AND c.relname IN ('corpus_processing_bases', "
                    "'corpus_import_registrations', 'corpus_provider_permits', "
                    "'corpus_provider_operations')")
        assert cur.fetchone()[0] == 4


def test_a_retirement_waits_for_a_registration_in_progress(db):
    sid, rid = _import(db)
    registering = psycopg2.connect(DSN)
    try:
        with registering.cursor() as cur:
            cur.execute("SELECT public.register_corpus_import_v1(%s, %s)",
                        (sid, rid))
            with rolled_back() as other:
                other.execute("SET lock_timeout = '300ms'")
                with pytest.raises(psycopg2.errors.LockNotAvailable):
                    other.execute("UPDATE public.corpus_processing_bases "
                                  "SET retired_at = now() "
                                  "WHERE decision_ref = 'N58'")
    finally:
        registering.rollback()
        registering.close()

