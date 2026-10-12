"""Regression evidence for the production-shaped fixture helpers.

These prove the new helpers against a REAL released-migration schema, built by
`tests/integration/confident_moment_rehearsal.sh released`. That is the point of
them: the legacy helpers only work against narrow test-only table copies, and
that divergence previously hid a defect that made a migration unable to apply to
production.

Nothing here touches the legacy helpers or any suite that still uses them.
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


def _product_rows(db):
    return create_product_rows(db)


def test_released_rehearsal_applies_recording_attempt_take_boundary(db):
    """The released lane contains 0297's functions and exact identity checks."""
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


def test_authorization_receipt_and_snapshot_come_from_the_canonical_rpc(db):
    """Receipt and snapshot are written by the acceptance RPC, fully populated."""
    ids = _product_rows(db)
    policy = register_policy(db)
    accept_authorization(db, ids["owner"], policy)
    receipt = one(
        db,
        "SELECT id,policy_id,explicit_action,age_18_attested,accepted_at,"
        "evidence_sha256 FROM processing_authorization_receipts "
        "WHERE acquisition_principal_id=%s",
        (ids["owner"],),
    )
    assert receipt["explicit_action"] == "agree_and_continue"
    assert receipt["age_18_attested"] is True
    # Every NOT NULL the released table declares is populated by the RPC.
    assert receipt["accepted_at"] is not None
    assert receipt["evidence_sha256"] is not None
    # Acceptance writes the RECEIPT only. The per-operation snapshot is a
    # separate canonical writer, which is exactly the seam the legacy helpers
    # bypassed by inserting the snapshot row by hand.
    assert one(
        db,
        "SELECT count(*) n FROM processing_authorization_snapshots "
        "WHERE acquisition_principal_id=%s",
        (ids["owner"],),
    )["n"] == 0
