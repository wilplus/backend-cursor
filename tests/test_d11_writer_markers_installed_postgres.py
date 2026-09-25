"""Every D11 writer's INSTALLED body carries 0327's preamble, in place.

The companion of tests/test_d11_writer_markers_survive_the_manifest.py, run
against a database instead of the files.  The existing marker test
(tests/test_confident_moment_coaching_bundle_postgres.py) re-executes 0327
before it looks, so it can only ever see 0327's own result.  This one
re-executes nothing: it reads the definitions as the lane left them.  Since
2026-09-25 the lane re-applies 0335 and 0354 after 0327, as the manifest
does, so the bodies here match production's.

For each writer 0327 injects into, the preamble must sit directly after the
body's ``BEGIN`` line and be byte-identical to 0327's entry.  That covers
placement and lock order in one comparison.  The two legacy root writers are
rewritten by 0327 differently, so for them the marker alone is checked, as
0327's own verifier does.  A writer in UNRESOLVED must be ABSENT here, which
pins production's state.  When a founder-approved fix lands, this fails until
the entry is removed from UNRESOLVED.

``accept_phase1_processing_authorization_v2`` (0357) is checked too.  0327
never named it; 0363 gives it v1's preamble, and ``registered_writers`` lists
it next to 0327's registry.

Rehearsal tier only (the released confident-moment lane).
"""
from __future__ import annotations

import os

import psycopg2
import pytest

from tests.test_d11_writer_markers_survive_the_manifest import (
    AUTHORIZATION_RECEIPT,
    AUTHORIZATION_RECEIPT_V2,
    OBJECT_PURGE,
    UNRESOLVED,
    registered_writers,
)

REPAIRED = [AUTHORIZATION_RECEIPT, AUTHORIZATION_RECEIPT_V2, OBJECT_PURGE]

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="disposable rehearsal only")


@pytest.fixture
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    connection = psycopg2.connect(**parsed)
    connection.autocommit = True
    try:
        yield connection
    finally:
        connection.close()


def _definition(db, signature: str) -> str:
    with db.cursor() as cur:
        cur.execute("SELECT pg_get_functiondef(%s::regprocedure)", (signature,))
        return cur.fetchone()[0]


@pytest.mark.parametrize("signature", sorted(registered_writers()))
def test_the_installed_writer_carries_its_d11_marker(db, signature):
    spec = registered_writers()[signature]
    body = _definition(db, signature)
    if signature in UNRESOLVED:
        assert spec["marker"] not in body, f"{signature} is repaired: update UNRESOLVED"
        return
    assert spec["marker"] in body, f"{signature} lost '{spec['marker']}'"
    if "sql" in spec:
        preamble = "\nBEGIN\n -- " + spec["marker"] + "\n" + spec["sql"]
        assert preamble in body, f"{signature}: preamble moved or drifted"
        assert body.count(spec["marker"]) == 1, f"{signature}: injected twice"


@pytest.mark.parametrize("signature", REPAIRED)
def test_the_repaired_writers_keep_the_bodies_that_replaced_them(db, signature):
    body = _definition(db, signature)
    if signature == OBJECT_PURGE:
        # 0354's practice branch survives the re-injection.
        assert "'processing_practice_objects'" in body
    elif signature == AUTHORIZATION_RECEIPT_V2:
        # 0357's optional-purpose refusal and evidence hash survive 0363.
        assert "PROCESSING_OPTIONAL_PURPOSE_INVALID" in body
        assert "array_to_string(chosen, ',')" in body
    else:
        # 0335's registry-driven phase-2 refusal survives the re-injection.
        assert "pr.phase = 'phase2'" in body


@pytest.mark.parametrize("signature", REPAIRED)
def test_the_repaired_writers_stay_service_role_only(db, signature):
    with db.cursor() as cur:
        for role, allowed in (
            ("service_role", True),
            ("anon", False),
            ("authenticated", False),
        ):
            cur.execute(
                "SELECT has_function_privilege(%s, %s::regprocedure, 'EXECUTE')",
                (role, signature),
            )
            assert cur.fetchone()[0] is allowed, (role, signature)
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_proc p, aclexplode(p.proacl) a "
            "WHERE p.oid = %s::regprocedure AND a.grantee = 0)",
            (signature,),
        )
        assert cur.fetchone()[0] is False, f"PUBLIC can execute {signature}"


def test_v2_takes_the_receipt_locks_before_anything_else(db):
    """The served acceptance queues behind a writer holding the principal lock.

    A second connection holds the principal's service lock.  v2, called with
    arguments that fail validation, must wait for that lock before it reaches
    the first check, so it runs into the lock timeout rather than raising
    its own error.  Without 0363 it raises PROCESSING_POLICY_UNAPPROVED.
    """
    principal = "00000000-0000-4000-8000-00000000d11a"
    holder = psycopg2.connect(**psycopg2.extensions.parse_dsn(DSN))
    try:
        with holder.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_lock(hashtextextended(%s, 0))",
                ("mlc3-service-principal:" + principal,),
            )
        with db.cursor() as cur:
            cur.execute("SET lock_timeout = '300ms'")
            try:
                with pytest.raises(psycopg2.errors.LockNotAvailable):
                    cur.execute(
                        "SELECT public.accept_phase1_processing_authorization_v2("
                        "%s::uuid, 'no-such-policy', '', '', '', '', "
                        "'agree_and_continue', true, 'de', 'en', 'test', now(), "
                        "'d11-lock-probe', '{}'::text[])",
                        (principal,),
                    )
            finally:
                cur.execute("RESET lock_timeout")
    finally:
        holder.close()
