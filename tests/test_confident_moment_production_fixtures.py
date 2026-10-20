"""
GUARD      The rehearsal fixture helpers (tests/confident_moment_production_
           fixtures.py) run on the real released-migration schema, built by
           tests/integration/confident_moment_rehearsal.sh released.
CATCHES    A DB test passing on a schema production never had: the legacy
           helpers used narrow test-only table copies, and that divergence
           once hid a migration that could not apply to production.
IF REMOVED A helper can drift from the released schema (the take/attempt
           identity check, the consent RPC) and every rehearsal suite built
           on it goes green on a fiction.
PROVES     test_released_rehearsal_applies_recording_attempt_take_boundary
             the take/attempt identity constraint and 0297's function exist
           test_accepting_goes_through_the_canonical_rpc
             accept_authorization writes a receipt through the RPC and no
             snapshot (the seam the legacy helpers bypassed by hand)
"""
from __future__ import annotations

import os

import psycopg2
import pytest

from tests.confident_moment_production_fixtures import (
    accept_authorization,
    create_product_rows,
    one,
    query,
    register_policy,
)

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


def test_released_rehearsal_applies_recording_attempt_take_boundary(db):
    assert one(
        db,
        "SELECT to_regprocedure('public.register_recording_attempt_v1(uuid,uuid,"
        "uuid,text,uuid,text,text,text,text)') IS NOT NULL AS present",
    )["present"] is True
    constraints = {
        row["conname"]: row["definition"]
        for row in query(
            db,
            "SELECT conname,pg_get_constraintdef(oid) AS definition "
            "FROM pg_constraint WHERE conrelid='public.takes'::regclass",
        )
    }
    assert "take_identity_matches_attempt" in constraints
    assert "id = recording_attempt_id" in constraints[
        "take_identity_matches_attempt"
    ]


def test_accepting_goes_through_the_canonical_rpc(db):
    ids = create_product_rows(db)
    policy = register_policy(db)
    accept_authorization(db, ids["owner"], policy)
    receipt = one(
        db,
        "SELECT explicit_action FROM processing_authorization_receipts "
        "WHERE acquisition_principal_id=%s",
        (ids["owner"],),
    )
    assert receipt["explicit_action"] == "agree_and_continue"
    assert one(
        db,
        "SELECT count(*) n FROM processing_authorization_snapshots "
        "WHERE acquisition_principal_id=%s",
        (ids["owner"],),
    )["n"] == 0
