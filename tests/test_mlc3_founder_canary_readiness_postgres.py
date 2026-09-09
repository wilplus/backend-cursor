"""Adversarial PostgreSQL checks for the SELECT-only canary readiness audit."""
from __future__ import annotations

import os

import psycopg2
import pytest

from scripts.check_mlc3_founder_canary_readiness import (
    _DEPENDENCY_TABLES,
    _FORBIDDEN_RPC_SIGNATURES,
    _REQUIRED_RPC_SIGNATURES,
    _RLS_TABLES,
    _aggregate_health,
)


DSN = os.environ.get("MLC3_CANARY_READINESS_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="disposable readiness DB only")
PRINCIPAL = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_d3_"):
        raise RuntimeError("Refusing a non-disposable database")
    if not parsed.get("host", "").startswith(
        ("/tmp/willab-", "/private/tmp/willab-")
    ):
        raise RuntimeError("Refusing a non-local rehearsal host")
    connection = psycopg2.connect(DSN)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def _health(db):
    return _aggregate_health(db, PRINCIPAL, "coach@example.com")


def test_every_exact_rpc_and_dependency_table_exists(db):
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT signature FROM unnest(%s::text[]) signature "
            "WHERE to_regprocedure('public.' || signature) IS NULL",
            (list(_REQUIRED_RPC_SIGNATURES),),
        )
        assert cursor.fetchall() == []
        cursor.execute(
            "SELECT name FROM unnest(%s::text[]) name "
            "WHERE to_regclass('public.' || name) IS NULL",
            (list(_DEPENDENCY_TABLES),),
        )
        assert cursor.fetchall() == []


def test_wrong_overload_cannot_satisfy_exact_rpc_registry(db):
    signature = "resolve_exercise_service_offer_read_v1(uuid,uuid)"
    with db.cursor() as cursor:
        cursor.execute(
            "ALTER FUNCTION public.resolve_exercise_service_offer_read_v1("
            "uuid,uuid) RENAME TO readiness_hidden_offer_reader"
        )
        cursor.execute(
            "CREATE FUNCTION public.resolve_exercise_service_offer_read_v1() "
            "RETURNS jsonb LANGUAGE sql AS 'SELECT ''{}''::jsonb'"
        )
    health = _health(db)
    assert health["missing_required_rpc_count"] == 1
    assert signature in _REQUIRED_RPC_SIGNATURES


def test_missing_service_execute_and_client_execute_both_block(db):
    signature = "resolve_exercise_service_offer_read_v1(uuid,uuid)"
    with db.cursor() as cursor:
        cursor.execute(
            f"REVOKE EXECUTE ON FUNCTION public.{signature} FROM service_role"
        )
    assert _health(db)["missing_service_rpc_grant_count"] == 1
    db.rollback()
    with db.cursor() as cursor:
        cursor.execute(
            f"GRANT EXECUTE ON FUNCTION public.{signature} TO authenticated"
        )
    assert _health(db)["runtime_rpc_client_grant_count"] == 1


def test_direct_table_write_grant_and_disabled_rls_block(db):
    with db.cursor() as cursor:
        cursor.execute(
            "GRANT INSERT ON public.exercise_service_offers TO service_role"
        )
    assert _health(db)["runtime_table_write_grant_count"] >= 1
    db.rollback()
    with db.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE public.coach_inline_exercise_drafts "
            "DISABLE ROW LEVEL SECURITY"
        )
    assert _health(db)["rls_disabled_table_count"] == 1


def test_forbidden_internal_helper_cannot_be_reexposed(db):
    assert _health(db)["forbidden_rpc_runtime_grant_count"] == 0
    with db.cursor() as cursor:
        cursor.execute(
            "GRANT EXECUTE ON FUNCTION "
            "public.require_mlc3_service_principal_v1(uuid) TO service_role"
        )
    assert _health(db)["forbidden_rpc_runtime_grant_count"] == 1


@pytest.mark.parametrize("signature", (
    "submit_mlc2_confidence_blind_judgment_v1("
    "uuid,uuid,uuid,text,timestamp with time zone,text)",
    "record_exercise_service_acquisition_receipt_v1("
    "uuid,text,uuid,uuid,uuid,uuid,text)",
))
def test_lower_level_writer_reexposure_blocks_readiness(db, signature):
    assert signature in _FORBIDDEN_RPC_SIGNATURES
    assert _health(db)["forbidden_rpc_runtime_grant_count"] == 0
    with db.cursor() as cursor:
        cursor.execute(
            f"GRANT EXECUTE ON FUNCTION public.{signature} TO service_role"
        )
    assert _health(db)["forbidden_rpc_runtime_grant_count"] == 1


def test_every_registered_rls_table_is_observed(db):
    with db.cursor() as cursor:
        for table in _RLS_TABLES:
            cursor.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
            cursor.execute(
                "SELECT relrowsecurity FROM pg_class "
                "WHERE oid=to_regclass(%s)", (f"public.{table}",),
            )
            assert cursor.fetchone() == (False,)
            assert _health(db)["rls_disabled_table_count"] == 1
            cursor.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    assert _health(db)["rls_disabled_table_count"] == 0


def test_disabled_required_purpose_fails_canonical_authority_readiness(db):
    with db.cursor() as cursor:
        cursor.execute(
            "UPDATE public.processing_purpose_registry "
            "SET operational=false,authorizes_processing=false "
            "WHERE id='coach_review'"
        )
    health = _health(db)
    assert health["required_operational_purpose_count"] == 1
    assert health["founder_current_full_service_receipt_count"] == 0
