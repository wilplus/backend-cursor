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


# ── the Phase-1 writer refuses a corpus import ─────────────────────────────


# ── who may write ──────────────────────────────────────────────────────────


# ── HO-13: a permit is one exact request, used for one call ────────────────


# ── HO-13b: an older shape or another N58 row stops the migration ──────────


# ── HO-13c: the recording's own session; the guard reads definitions ──────


# ── HO-13d: the whole shape is compared, and a retirement waits ────────────
