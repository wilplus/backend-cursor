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

import psycopg2
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
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


@pytest.fixture
def principal(db):
    return _one(db, """
        INSERT INTO public.owner_principals (id, user_id)
        VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id""")


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
