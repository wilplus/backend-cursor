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
    # A permit with no recording named is for the registered one.
    assert _corpus_permit(db, sid, None)["recording_id"] == rid

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
