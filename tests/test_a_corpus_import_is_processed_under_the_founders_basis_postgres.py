"""
STORY    As the founder, I want a coach-imported recording processed only
         under my written corpus basis (N58) and never under a speaker's own
         permit, so that every provider call on the critical path (record ->
         process) has a lawful basis and a speaker's Take is never processed
         without their own acceptance.
OUTCOME
  O1  The basis is one N58 row with the founder's note, never pooled; it can
      only be retired, never edited.
  O2  A registered import gets a permit naming N58 and its session; its
      events land in the corpus ledger, nothing in the Phase-1 one.
  O3  A user's Take, a guest's Take and an owned Take with a forged
      "training_import" flag are refused by the corpus writers.
  O4  The Phase-1 permit writer refuses a corpus import, even for the
      importing coach who has accepted the terms.
  O5  With no basis in force, no import is registered and no permit issued.
  O6  The service key may only call the entry points; the browser roles
      (anon, authenticated) can neither call them nor write the tables.
PROVES   O1 -> test_the_basis_is_the_founders_and_only_ever_retired
         O2 -> test_a_registered_import_is_permitted_under_n58
         O3 -> test_a_users_take_is_refused
               test_a_guests_take_is_refused
               test_a_forged_import_flag_on_an_owned_take_is_refused
         O4 -> test_the_phase1_writer_refuses_a_corpus_import
         O5 -> test_no_basis_in_force_refuses_everything
         O6 -> test_only_the_service_key_reaches_the_entry_points
WHY      Migration a_corpus_import_is_processed_under_the_founders_basis.sql
         (0435; founder 2026-10-07, decisions log N58). Runs the real SQL on
         the rehearsal tier, lane "confident-moment released".
"""
from __future__ import annotations

import json
import os
import uuid

import psycopg2
import psycopg2.errors
import pytest

from tests import test_phase1_processing_postgres as _phase1
from tests.test_phase1_processing_postgres import (
    _accept,
    _permit,
    _principal,
)

# The active Phase-1 policy the binding suite registers (or reuses), so a
# person's receipt can exist beside an import.
policy = _phase1.policy

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)
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

def test_the_basis_is_the_founders_and_only_ever_retired(db):
    with db.cursor() as cur:
        cur.execute("SELECT id::text, decision_ref, recorded_by, covers_source, "
                    "pooled_learning_eligible, retired_at, founder_note "
                    "FROM public.corpus_processing_bases "
                    "WHERE covers_source = 'training_import'")
        rows = cur.fetchall()
    assert len(rows) == 1
    basis_id, ref, by, covers, pooled, retired, note = rows[0]
    assert (basis_id, ref, by, covers, pooled, retired) == (
        BASIS_ID, "N58", "founder", "training_import", False, None)
    assert "agreed with the counsel" in note
    # Any edit other than a retirement is refused, and so is a removal.
    for sql in ("UPDATE public.corpus_processing_bases "
                "SET pooled_learning_eligible = true WHERE id = %s",
                "DELETE FROM public.corpus_processing_bases WHERE id = %s"):
        with pytest.raises(psycopg2.errors.CheckViolation) as raised:
            with db.cursor() as cur:
                cur.execute(sql, (BASIS_ID,))
        assert "CORPUS_BASIS_IMMUTABLE" in str(raised.value)


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


# ── what the corpus basis never authorizes ─────────────────────────────────

def _owned_take(db, owner, *, source="audit_upload"):
    project = _one(db, """
        INSERT INTO public.projects (id, owner_principal_id, display_name)
        VALUES (gen_random_uuid(), %s, 'pitch') RETURNING id::text""", (owner,))
    return _session(db, source=source, owner=owner, project=project)


def test_a_users_take_is_refused(db, policy):
    owner = _principal(db)
    _accept(db, policy, owner)
    sid = _owned_take(db, owner)
    rid = _recording(db, sid, origin=None)
    _refused(db, "CORPUS_SOURCE_NOT_IMPORT", _register, sid, rid)
    _refused(db, "CORPUS_IMPORT_UNREGISTERED", _corpus_permit, sid, rid)
    # Its own owner still gets its Phase-1 permit: 0435 changed nothing there.
    assert _permit(db, owner, sid, None)["operation_kind"] == "transcription"


def test_a_guests_take_is_refused(db, policy):
    guest = _principal(db, guest=True)
    _accept(db, policy, guest)
    sid = _owned_take(db, guest)
    rid = _recording(db, sid, origin=None)
    _refused(db, "CORPUS_SOURCE_NOT_IMPORT", _register, sid, rid)
    _refused(db, "CORPUS_IMPORT_UNREGISTERED", _corpus_permit, sid, rid)
    assert _one(db, "SELECT count(*) FROM public.corpus_import_registrations "
                    "WHERE session_id = %s", (sid,)) == 0


def test_a_forged_import_flag_on_an_owned_take_is_refused(db, policy):
    owner = _principal(db)
    _accept(db, policy, owner)
    sid = _owned_take(db, owner, source="training_import")
    rid = _recording(db, sid)
    _refused(db, "CORPUS_SESSION_HAS_OWNER", _register, sid, rid)
    assert _one(db, "SELECT count(*) FROM public.corpus_import_registrations "
                    "WHERE session_id = %s", (sid,)) == 0


# ── the Phase-1 writer refuses a corpus import ─────────────────────────────

def test_the_phase1_writer_refuses_a_corpus_import(db, policy):
    coach = _principal(db)
    _accept(db, policy, coach)
    sid, rid = _import(db)
    _register(db, sid, rid)
    # Named by session, by recording, or both: always refused.
    _refused(db, "PROCESSING_SOURCE_IS_CORPUS_IMPORT", _permit, coach, sid, None)
    _refused(db, "PROCESSING_SOURCE_IS_CORPUS_IMPORT", _permit, coach, None, rid)
    _refused(db, "PROCESSING_SOURCE_IS_CORPUS_IMPORT", _permit, coach, sid, rid)
    assert _one(db, "SELECT count(*) FROM public.processing_authorization_snapshots "
                    "WHERE source_take_id = %s OR source_recording_id = %s",
                (sid, rid)) == 0


# ── no basis in force ──────────────────────────────────────────────────────

def test_no_basis_in_force_refuses_everything(db):
    registered_sid, registered_rid = _import(db)
    _register(db, registered_sid, registered_rid)
    fresh_sid, fresh_rid = _import(db)
    # Retire N58 inside a transaction that is rolled back, so the basis stays
    # in force for every other suite in this lane.
    conn = psycopg2.connect(DSN)
    try:
        conn.autocommit = False
        conn.cursor().execute(
            "UPDATE public.corpus_processing_bases SET retired_at = now() "
            "WHERE id = %s", (BASIS_ID,))
        _refused(conn, "CORPUS_BASIS_ABSENT", _register, fresh_sid, fresh_rid)
        conn.rollback()
        conn.cursor().execute(
            "UPDATE public.corpus_processing_bases SET retired_at = now() "
            "WHERE id = %s", (BASIS_ID,))
        _refused(conn, "CORPUS_BASIS_ABSENT", _corpus_permit,
                 registered_sid, registered_rid)
    finally:
        conn.rollback()
        conn.close()
    # Rolled back: the basis is in force again.
    assert _corpus_permit(db, registered_sid, registered_rid)["basis_id"] == BASIS_ID


# ── who may write ──────────────────────────────────────────────────────────

_ENTRY_POINTS = (
    "public.register_corpus_import_v1(uuid, uuid)",
    "public.issue_corpus_provider_permit_v1(uuid, uuid, text, text, jsonb, text, integer)",
    "public.record_corpus_provider_operation_v1(uuid, text, text, text, jsonb)",
)
_TABLES = (
    "public.corpus_processing_bases", "public.corpus_import_registrations",
    "public.corpus_provider_permits", "public.corpus_provider_operations",
)


def test_only_the_service_key_reaches_the_entry_points(db):
    for fn in _ENTRY_POINTS:
        assert _one(db, "SELECT has_function_privilege('service_role', %s, "
                        "'EXECUTE')", (fn,)) is True, fn
        for role in ("anon", "authenticated"):
            assert _one(db, "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                        (role, fn)) is False, (role, fn)
    for table in _TABLES:
        for role in ("service_role", "anon", "authenticated"):
            for action in ("INSERT", "UPDATE", "DELETE"):
                assert _one(db, "SELECT has_table_privilege(%s, %s, %s)",
                            (role, table, action)) is False, (role, table, action)
        for role in ("anon", "authenticated"):
            assert _one(db, "SELECT has_table_privilege(%s, %s, 'SELECT')",
                        (role, table)) is False, (role, table)
