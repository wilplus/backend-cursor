"""The self-speaker writer creates a speaker the released table accepts.

R-2 (major), ML provenance audit 2026-09-22.

`record_mlc3_self_speaker_target_v1` minted a speaker with two bare INSERTs
naming one column each:

    INSERT INTO ml_speakers(id) VALUES (speaker_value);
    INSERT INTO ml_speaker_principals(speaker_id, acquisition_principal_id)
         VALUES (speaker_value, p_acquisition_principal_id);

The released `ml_speakers` requires identity_version, identity_hash (UNIQUE,
exactly 64 characters) and created_by. The released `ml_speaker_principals`
requires binding_kind, binding_proof_hash and bound_by. Six NOT NULL columns,
no defaults — so the first speaker this service ever had to mint would have
raised, taking the Take down with it.

WHY THIS FILE RUNS ON THE RELEASED LANE. The D4 suite already calls that
function and passes, because its lane is cloned from the narrow fixture where
`ml_speakers` is declared `(id UUID PRIMARY KEY)` — one column, no
constraints. The fixture had removed exactly the constraints the code
violates. Correcting it turns four lanes red at once (~100 cases that have
been minting identity-less speakers for as long as it allowed it), which is
the audit's Workstream 10 and not this change. So the proof lives here, on
the lane whose `ml_speakers` has always been the real one.
"""
from __future__ import annotations

import os
import pathlib
import re
import uuid

import psycopg2
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "speaker_identity_the_table_accepts.sql"
SPLIT_POLICY = "speaker-sha256-80-10-10-v1"


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


@pytest.fixture
def principal(db):
    return _one(db, """
        INSERT INTO public.owner_principals (id, user_id)
        VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id""")


class TestTheReleasedTableRefusesAnIdentitylessSpeaker:
    """The defect itself, on the real schema."""

    def test_the_old_bare_insert_cannot_satisfy_ml_speakers(self, db):
        """This is the statement 0355 removed, run against production's shape.

        If this ever stops raising, `ml_speakers` lost its constraints and the
        whole finding needs re-reading.
        """
        with pytest.raises(psycopg2.errors.NotNullViolation) as raised:
            _one(db, "INSERT INTO public.ml_speakers(id) VALUES (%s)",
                 (str(uuid.uuid4()),))
        assert "identity_version" in str(raised.value)

    def test_the_old_bare_insert_cannot_satisfy_the_binding_either(
            self, db, principal):
        """Both halves failed, not just the first."""
        # A fresh hash per call: identity_hash is UNIQUE on the released
        # table, so a constant would make this case pass once and then fail
        # on a lane that is re-run.
        speaker = _one(db, """
            INSERT INTO public.ml_speakers (
                identity_version, identity_hash, created_by)
            VALUES ('r2-probe-v1', encode(extensions.digest(
                gen_random_uuid()::text, 'sha256'), 'hex'), 'r2-probe')
            RETURNING id""")

        with pytest.raises(psycopg2.errors.NotNullViolation) as raised:
            _one(db, """
                INSERT INTO public.ml_speaker_principals(
                    speaker_id, acquisition_principal_id) VALUES (%s, %s)""",
                (speaker, principal))
        assert "binding_kind" in str(raised.value)


class TestTheCanonicalWriterIsWhatItNowUses:
    """The shape 0355 replaced those INSERTs with, exercised end to end."""

    def _register(self, db, principal, owner_user_id):
        """Exactly the call 0355 makes, with the same derivations."""
        return _one(db, """
            SELECT link.speaker_id FROM public.register_ml_speaker_principal_v1(
                %s,
                encode(extensions.digest(
                    'mlc3-self-speaker-owner-v1:' || %s::TEXT, 'sha256'), 'hex'),
                'mlc3-self-speaker-owner-v1',
                'initial',
                encode(extensions.digest(
                    'mlc3-self-speaker-proof-v1:' || %s::TEXT || ':'
                    || %s::TEXT, 'sha256'), 'hex'),
                'mlc3-self-speaker-v1'
            ) link""", (principal, owner_user_id, principal, owner_user_id))

    def test_it_writes_every_column_the_table_requires(self, db, principal):
        owner_user_id = _one(
            db, "SELECT user_id::text FROM public.owner_principals WHERE id = %s",
            (principal,))

        speaker = self._register(db, principal, owner_user_id)

        with db.cursor() as cur:
            cur.execute("""
                SELECT s.identity_version, length(s.identity_hash), s.created_by,
                       p.binding_kind, length(p.binding_proof_hash), p.bound_by
                  FROM public.ml_speakers s
                  JOIN public.ml_speaker_principals p ON p.speaker_id = s.id
                 WHERE p.acquisition_principal_id = %s""", (principal,))
            row = cur.fetchone()

        assert row is not None, "no speaker was bound to the principal"
        assert row[0] == "mlc3-self-speaker-owner-v1"
        assert row[1] == 64
        assert row[2] == "mlc3-self-speaker-v1"
        assert row[3] == "initial"
        assert row[4] == 64
        assert row[5] == "mlc3-self-speaker-v1"
        assert speaker

    def test_a_replay_resolves_to_the_same_speaker(self, db, principal):
        """The identity is derived from the owner's user id, so a second call
        must find the first speaker rather than mint another. A random
        identity would make every retry a new person."""
        owner_user_id = _one(
            db, "SELECT user_id::text FROM public.owner_principals WHERE id = %s",
            (principal,))

        first = self._register(db, principal, owner_user_id)
        second = self._register(db, principal, owner_user_id)

        assert first == second
        assert _one(db, """
            SELECT count(*) FROM public.ml_speaker_principals
             WHERE acquisition_principal_id = %s""", (principal,)) == 1

    def test_the_speaker_gets_a_split_assignment(self, db, principal):
        """The bare INSERTs skipped `assign_ml_speaker_split_v1` entirely, so
        a speaker created by the old path had no split at all — invisible
        until something tried to build a dataset from it."""
        owner_user_id = _one(
            db, "SELECT user_id::text FROM public.owner_principals WHERE id = %s",
            (principal,))

        speaker = self._register(db, principal, owner_user_id)

        assert _one(db, """
            SELECT count(*) FROM public.ml_speaker_split_assignments
             WHERE speaker_id = %s AND split_policy_version = %s""",
            (speaker, SPLIT_POLICY)) == 1

    def test_a_different_person_gets_a_different_speaker(self, db):
        """The identity is per owner, not per call."""
        seen = set()
        for _ in range(2):
            principal = _one(db, """
                INSERT INTO public.owner_principals (id, user_id)
                VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id""")
            owner_user_id = _one(
                db, "SELECT user_id::text FROM public.owner_principals"
                    " WHERE id = %s", (principal,))
            seen.add(self._register(db, principal, owner_user_id))

        assert len(seen) == 2


class TestTheFunctionNoLongerHandRollsIt:
    """Source-level, and narrow: the property tests above cannot see which
    statement the migration actually carries."""

    def test_the_migration_drops_the_bare_inserts(self):
        sql = MIGRATION.read_text(encoding="utf-8")
        body = re.sub(r"--[^\n]*", "", sql)

        assert not re.search(
            r"INSERT\s+INTO\s+public\.ml_speakers\s*\(\s*id\s*\)", body,
            re.IGNORECASE,
        ), "the identity-less INSERT is back"
        assert "register_ml_speaker_principal_v1" in body, (
            "the speaker is no longer minted through the canonical writer"
        )
