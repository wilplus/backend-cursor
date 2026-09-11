"""Executable checks run only against a disposable production-shaped clone."""
from __future__ import annotations

import os
from pathlib import Path

import psycopg2
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="disposable rehearsal only")
SQL = (Path(__file__).resolve().parents[1] / "migrations/pending/add_confident_moment_coaching_bundle_v1.sql").read_text()


@pytest.fixture
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(**parsed)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def test_apply_reapply_forced_rls_and_exact_signatures(db):
    with db.cursor() as cur:
        cur.execute(SQL)
        cur.execute(SQL)
        cur.execute("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname=ANY(%s) ORDER BY relname", (["confident_moment_bundle_attachments","root_phrase_coverage_frames","root_phrase_coverage_items","feedback_language_revision_deliveries"],))
        rows = cur.fetchall()
        assert len(rows) == 4 and all(row[1:] == (True, True) for row in rows)
        cur.execute("SELECT to_regprocedure(%s) IS NOT NULL", ("public.record_root_phrase_product_action_v2(uuid,uuid,uuid,uuid,integer,text,uuid,uuid,uuid,uuid,uuid,uuid,bigint,uuid,uuid,uuid,text,text)",))
        assert cur.fetchone()[0]
        cur.execute("SELECT to_regprocedure(%s) IS NOT NULL", ("public.require_root_phrase_practice_source_live_v1(uuid,uuid,uuid,uuid,uuid)",))
        assert cur.fetchone()[0]
        cur.execute(
            "SELECT pg_get_function_identity_arguments(%s::regprocedure::oid)",
            ("public.prepare_confident_moment_bundle_v1(uuid,uuid,uuid,uuid,uuid,text)",),
        )
        assert "p_bundle_subject_candidate_id uuid" in cur.fetchone()[0]


def test_legacy_root_writers_delegate_exclusively_to_internal_helper(db):
    with db.cursor() as cur:
        cur.execute(SQL)
        for signature in (
            "public.activate_synthetic_root_phrase_v1(uuid,uuid,boolean,boolean,text)",
            "public.remove_synthetic_root_phrase_v1(uuid,integer,integer,uuid,uuid,text)",
        ):
            cur.execute("SELECT pg_get_functiondef(%s::regprocedure)", (signature,))
            body = cur.fetchone()[0]
            assert "transition_ideal_text_root_state_v1" in body
            assert "UPDATE public.ideal_text_part" not in body
            assert "INSERT INTO public.ideal_text_part_revision" not in body
        # A PUBLIC grant would also make each concrete runtime role executable.
        for role in ("anon", "authenticated", "service_role"):
            cur.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')",
                (
                    role,
                    "public.transition_ideal_text_root_state_v1(uuid,uuid,uuid,uuid,bigint,text,text)",
                ),
            )
            assert cur.fetchone()[0] is False


def test_runtime_roles_have_no_direct_writes_or_rpc_execution(db):
    with db.cursor() as cur:
        cur.execute(SQL)
        tables = (
            "confident_moment_bundle_attachments",
            "root_phrase_coverage_frames",
            "root_phrase_coverage_items",
            "feedback_language_revision_deliveries",
            "feedback_revisions",
            "root_phrase_product_actions",
        )
        for role in ("anon", "authenticated", "service_role"):
            for table in tables:
                cur.execute(
                    "SELECT has_table_privilege(%s,'public.'||%s,'INSERT,UPDATE,DELETE')",
                    (role, table),
                )
                assert cur.fetchone()[0] is False
            cur.execute("SELECT has_function_privilege(%s,'public.prepare_confident_moment_bundle_v1(uuid,uuid,uuid,uuid,uuid,text)','EXECUTE')", (role,))
            assert cur.fetchone()[0] is False
            cur.execute("SELECT has_function_privilege(%s,'public.require_root_phrase_practice_source_live_v1(uuid,uuid,uuid,uuid,uuid)','EXECUTE')", (role,))
            assert cur.fetchone()[0] is False


def test_structural_false_defaults_append_only_and_exact_foreign_key(db):
    with db.cursor() as cur:
        cur.execute(SQL)
        cur.execute(
            "SELECT table_name,column_name,column_default FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=ANY(%s) "
            "AND column_name IN ('serves_user','dataset_eligible')",
            (
                [
                    "confident_moment_bundle_attachments",
                    "root_phrase_coverage_frames",
                    "root_phrase_coverage_items",
                    "feedback_language_revision_deliveries",
                ],
            ),
        )
        defaults = cur.fetchall()
        assert len(defaults) == 8
        assert all(row[2] == "false" for row in defaults)
        cur.execute(
            "SELECT count(*) FROM pg_trigger WHERE tgrelid=ANY(ARRAY["
            "'public.confident_moment_bundle_attachments'::regclass,"
            "'public.root_phrase_coverage_frames'::regclass,"
            "'public.root_phrase_coverage_items'::regclass,"
            "'public.feedback_language_revision_deliveries'::regclass]) "
            "AND NOT tgisinternal AND tgname LIKE '%append_only'"
        )
        assert cur.fetchone()[0] == 4
        cur.execute(
            "SELECT count(*) FROM pg_trigger "
            "WHERE tgrelid='public.feedback_revisions'::regclass "
            "AND NOT tgisinternal AND tgname='feedback_revisions_append_only'"
        )
        assert cur.fetchone()[0] == 1
        cur.execute(
            "SELECT count(*) FROM pg_indexes WHERE schemaname='public' "
            "AND indexname IN "
            "('feedback_language_coach_revision_original_idx',"
            "'feedback_language_coach_revision_supersedes_idx')"
        )
        assert cur.fetchone()[0] == 2
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid='public.confident_moment_bundle_attachments'::regclass "
            "AND pg_get_constraintdef(oid) LIKE "
            "'FOREIGN KEY (canonical_feedback_presentation_id, attached_candidate_id)%'"
        )
        assert cur.fetchone() is not None
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid='public.root_phrase_product_actions'::regclass "
            "AND conname='root_phrase_product_action_v2_source_matrix_check'"
        )
        source_matrix = cur.fetchone()[0]
        assert "source_target_speaker_binding_id" in source_matrix
        assert "practice_target_speaker_binding_id" in source_matrix
        assert "practice_guard_sha256" in source_matrix


def test_failed_statement_leaves_no_partial_row(db):
    with db.cursor() as cur:
        cur.execute(SQL)
        cur.execute("BEGIN")
        cur.execute("SAVEPOINT negative")
        with pytest.raises(psycopg2.Error):
            cur.execute("INSERT INTO public.root_phrase_coverage_frames(id) VALUES(gen_random_uuid())")
        cur.execute("ROLLBACK TO SAVEPOINT negative")
        cur.execute("SELECT count(*) FROM public.root_phrase_coverage_frames")
        assert cur.fetchone()[0] == 0


def test_d6_source_matrix_and_internal_practice_guard_fail_before_writes(db):
    with db.cursor() as cur:
        cur.execute(SQL)
        cur.execute("BEGIN")
        cur.execute("SELECT count(*) FROM public.root_phrase_product_actions")
        before = cur.fetchone()[0]
        cur.execute("SAVEPOINT invalid_matrix")
        with pytest.raises(psycopg2.Error, match="ROOTING_PHRASE_SOURCE_COMBINATION_INVALID"):
            cur.execute(
                "SELECT public.record_root_phrase_product_action_v2("
                "gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),"
                "gen_random_uuid(),0,'activate_automatic_root',NULL,NULL,NULL,"
                "NULL,NULL,NULL,NULL,NULL,NULL,NULL,"
                "'rooting-coverage-30-80-100-v1','invalid-matrix')"
            )
        cur.execute("ROLLBACK TO SAVEPOINT invalid_matrix")
        cur.execute("SAVEPOINT invalid_practice")
        with pytest.raises(psycopg2.Error, match="ROOTING_PHRASE_PRACTICE_SOURCE_INVALID"):
            cur.execute(
                "SELECT public.require_root_phrase_practice_source_live_v1("
                "gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),NULL,NULL)"
            )
        cur.execute("ROLLBACK TO SAVEPOINT invalid_practice")
        cur.execute("SELECT count(*) FROM public.root_phrase_product_actions")
        assert cur.fetchone()[0] == before


def test_d6_runtime_role_cannot_invoke_root_writers(db):
    with db.cursor() as cur:
        cur.execute(SQL)
        cur.execute("BEGIN")
        cur.execute("SAVEPOINT runtime_denial")
        cur.execute("SET LOCAL ROLE service_role")
        with pytest.raises(psycopg2.Error, match="permission denied"):
            cur.execute(
                "SELECT public.record_root_phrase_product_action_v2("
                "gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),"
                "gen_random_uuid(),0,'remove_current_root',NULL,NULL,NULL,NULL,"
                "NULL,NULL,NULL,NULL,NULL,NULL,"
                "'rooting-coverage-30-80-100-v1','runtime-denied')"
            )
        cur.execute("ROLLBACK TO SAVEPOINT runtime_denial")
