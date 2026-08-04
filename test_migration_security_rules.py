"""The two standing security rules for migrations, enforced instead of remembered.

docs/RLS-AUDIT.md · migrations/add_rls_all_public_tables.sql ·
migrations/lock_down_public_function_grants.sql

WHY THIS FILE EXISTS
--------------------
The 2026-07-25 incident was not a clever attack. It was a DEFAULT: Supabase
grants `anon`/`authenticated` access to `public`, the FE ships the anon key
inlined in the browser bundle, and 57 tables shipped without anyone typing the
one line that closes it. The founder ran the sweep the same day, and the audit
ends with a standing rule — "every new public table gets ENABLE ROW LEVEL
SECURITY in the same migration that creates it."

A standing rule that only a human checks is a rule that holds until the week
someone is busy. This file is that rule with teeth, plus the second one that
2026-08-03 introduced.

RULE 1 — TABLES GET RLS.
    RLS is the ONLY control on the direct-PostgREST path; no amount of
    API-side owner checking defends it, because that path never reaches Flask.

RULE 2 — FUNCTIONS GET THEIR EXECUTE REVOKED.
    New with the first `.rpc()` in this repo (add_token_charge_rpc.sql), and it
    is a genuinely different door: RLS is table-level and says NOTHING about
    functions. PostgREST publishes every function in the exposed schema at
    /rest/v1/rpc/<name>, and Postgres grants EXECUTE to PUBLIC by default. A
    money-moving function created without a REVOKE is the 2026-07-25 exposure
    again, through a door the sweep does not cover.

THE LEGACY ALLOWLIST IS FROZEN.
    47 migration files create tables without enabling RLS in the file. They
    are listed below so this gate is green on the day it lands: a red-on-day-1
    gate gets ignored, and an ignored gate protects nothing. The list may only
    ever SHRINK. Anything new that fails is a real finding.

    46 of the 47 are covered in PRODUCTION by the dynamic sweep the founder ran
    on 2026-07-25 — docs/RLS-AUDIT.md names them — so the gap is in the FILES,
    not the database. (Git dates do not show this: repo history starts
    2026-07-27, after the sweep. The audit's own table is the evidence.)

    THE ONE EXCEPTION, and the first thing this gate caught:
    `add_processing_jobs.sql` (0239) landed 2026-08-03 with the durable
    Redis/RQ queue (#322) — AFTER the sweep, and absent from the audit. It was
    genuinely exposed. Closed by migrations/add_rls_processing_jobs.sql rather
    than by editing 0239, because 0239 is already manifested and editing an
    applied file trips the runner's checksum drift detection. Its entry stays
    below because the entry describes the FILE accurately; the database is
    fixed. Do not read a frozen entry as "this table is safe" — read it as
    "this file predates the rule."

Run: python3 -m unittest test_migration_security_rules
"""
from __future__ import annotations

import os
import re
import unittest

MIGRATIONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")

_CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?([a-zA-Z_]\w*)", re.I)
_ENABLE_RLS = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:public\.)?([a-zA-Z_]\w*)\s+"
    r"ENABLE\s+ROW\s+LEVEL\s+SECURITY", re.I)
_CREATE_FUNCTION = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:public\.)?([a-zA-Z_]\w*)\s*\(", re.I)
_SECURITY_DEFINER = re.compile(r"SECURITY\s+DEFINER", re.I)


def _sql_files() -> list:
    return sorted(f for f in os.listdir(MIGRATIONS) if f.endswith(".sql"))


def _strip_comments(sql: str) -> str:
    """Line comments only.

    Enough here and deliberately not more: every migration in this repo carries
    a long `--` header, and several quote example DDL inside it. Block comments
    are not used, and a full SQL parser would be a dependency to make a
    regex-shaped gate feel rigorous without catching anything extra.
    """
    return "\n".join(line.split("--")[0] for line in sql.splitlines())


# ── Frozen legacy set — (file, table) pairs that predate the standing rule.
# Covered in production by the 2026-07-25 sweep. NEVER ADD TO THIS LIST.
# Removing an entry (by adding the ALTER TABLE ... ENABLE ROW LEVEL SECURITY
# line to that migration) is always welcome.
LEGACY_TABLES_WITHOUT_RLS = frozenset({
    ("add_admin_annotations_log.sql", "admin_annotations_log"),
    ("add_admin_copilot_foundation.sql", "acoustic_labels"),
    ("add_admin_copilot_foundation.sql", "admin_annotation_events"),
    ("add_admin_copilot_foundation.sql", "admin_student_send_drafts"),
    ("add_admin_copilot_foundation.sql", "student_profile"),
    ("add_annotation_export_pipeline.sql", "admin_annotation_export_runs"),
    ("add_arc_context_documents.sql", "arc_context_documents"),
    ("add_arc_invite_codes.sql", "arc_invite_codes"),
    ("add_arc_purchases.sql", "arc_purchases"),
    ("add_best_presentation_cache.sql", "best_presentation_cache"),
    ("add_best_presentation_edits.sql", "best_presentation_edits"),
    ("add_candidate_windows.sql", "candidate_windows"),
    ("add_casual_voice_benchmarks.sql", "casual_voice_benchmarks"),
    ("add_charisma_snippet_pipeline.sql", "charisma_snippets"),
    ("add_charisma_snippets_table.sql", "charisma_snippets"),
    ("add_coaching_attempt_annotations.sql", "coaching_attempt_annotations"),
    ("add_coaching_attempts_table.sql", "coaching_attempts"),
    ("add_coaching_directives_queue.sql", "coaching_directives_queue"),
    ("add_coaching_sessions_table.sql", "coaching_sessions"),
    ("add_copilot_reference_upload_jobs.sql", "copilot_reference_upload_jobs"),
    ("add_copilot_video_pipeline.sql", "admin_uploaded_reference_videos"),
    ("add_copilot_video_pipeline.sql", "model_training_runs"),
    ("add_dad_jokes_table.sql", "dad_jokes"),
    ("add_foundation_discriminators.sql", "chat_question_pool"),
    ("add_funnel_config.sql", "funnel_config"),
    ("add_processing_jobs.sql", "processing_jobs"),
    ("add_recording_feelings.sql", "recording_feelings"),
    ("add_recording_reviews.sql", "recording_review_annotations"),
    ("add_recording_reviews.sql", "recording_reviews"),
    ("add_rejected_takes.sql", "rejected_takes"),
    ("add_runtime_model_config.sql", "runtime_config"),
    ("add_snippet_labels_table.sql", "snippet_labels"),
    ("add_stress_snippet_labeling_pipeline.sql", "stress_snippets"),
    ("add_user_audits.sql", "user_audits"),
    ("add_user_consent_events_table.sql", "user_consent_events"),
    ("add_user_consents_table.sql", "user_consents"),
    ("add_user_sniper_profile.sql", "session_sniper_metrics"),
    ("add_user_sniper_profile.sql", "user_sniper_profile"),
    ("add_user_uploaded_files.sql", "user_uploaded_files"),
    ("add_v2_student_coaching_memory.sql", "v2_student_coaching_memory"),
    ("interview_admin_upgrade.sql", "user_settings"),
    ("v1_planned_session.sql", "admin_session_overrides"),
    ("v1_planned_session.sql", "content_exposures"),
    ("v1_planned_session.sql", "session_command_options"),
    ("v2_all_in_one.sql", "v2_exercises"),
    ("v2_all_in_one.sql", "v2_metric_definitions"),
    ("v2_all_in_one.sql", "v2_metric_questions"),
    ("v2_all_in_one.sql", "v2_metric_questions_pool"),
    ("v2_all_in_one.sql", "v2_post_recording_questions_pool"),
    ("v2_all_in_one.sql", "v2_reports"),
    ("v2_all_in_one.sql", "v2_sessions"),
    ("v2_all_in_one.sql", "v2_speaker_profiles"),
    ("v2_all_in_one.sql", "v2_student_overrides"),
    ("v2_all_in_one.sql", "v2_tasks"),
    ("v2_all_in_one.sql", "v2_universal_questions"),
    ("v2_all_in_one.sql", "v2_warm_up_task_pool"),
    ("v2_all_in_one.sql", "v2_warm_up_tasks"),
    ("v2_flow.sql", "v2_exercises"),
    ("v2_flow.sql", "v2_metric_definitions"),
    ("v2_flow.sql", "v2_post_recording_questions_pool"),
    ("v2_flow.sql", "v2_reports"),
    ("v2_flow.sql", "v2_sessions"),
    ("v2_flow.sql", "v2_student_overrides"),
    ("v2_flow.sql", "v2_tasks"),
    ("v2_flow.sql", "v2_universal_questions"),
    ("v2_focus_questions.sql", "v2_focus_question_pool"),
    ("v2_focus_questions.sql", "v2_focus_questions"),
    ("v2_focus_tasks.sql", "v2_focus_task_pool"),
    ("v2_focus_tasks.sql", "v2_focus_tasks"),
    ("v2_homework_flow.sql", "v2_metric_questions"),
    ("v2_homework_flow.sql", "v2_warm_up_tasks"),
    ("v2_metric_questions_pool.sql", "v2_metric_questions_pool"),
    ("v2_metric_questions_table_only.sql", "v2_metric_questions"),
    ("v2_schema_unified.sql", "v2_exercises"),
    ("v2_schema_unified.sql", "v2_metric_definitions"),
    ("v2_schema_unified.sql", "v2_metric_questions"),
    ("v2_schema_unified.sql", "v2_post_recording_questions"),
    ("v2_schema_unified.sql", "v2_reports"),
    ("v2_schema_unified.sql", "v2_sessions"),
    ("v2_schema_unified.sql", "v2_speaker_profiles"),
    ("v2_schema_unified.sql", "v2_student_overrides"),
    ("v2_schema_unified.sql", "v2_tasks"),
    ("v2_schema_unified.sql", "v2_warm_up_task_pool"),
    ("v2_schema_unified.sql", "v2_warm_up_tasks"),
    ("v2_speaker_profiles.sql", "v2_speaker_profiles"),
    ("v2_student_post_recording_questions.sql",
     "v2_student_post_recording_questions"),
    ("v2_warm_up_task_pool.sql", "v2_warm_up_task_pool"),
})


class NewTablesEnableRlsTests(unittest.TestCase):
    """RULE 1 — docs/RLS-AUDIT.md, "Standing rule going forward"."""

    def test_every_new_public_table_enables_rls_in_its_own_migration(self):
        offenders = []
        for name in _sql_files():
            with open(os.path.join(MIGRATIONS, name), encoding="utf-8",
                      errors="replace") as fh:
                sql = _strip_comments(fh.read())
            created = {t.lower() for t in _CREATE_TABLE.findall(sql)}
            secured = {t.lower() for t in _ENABLE_RLS.findall(sql)}
            for table in sorted(created - secured):
                if (name, table) not in LEGACY_TABLES_WITHOUT_RLS:
                    offenders.append(f"{name}: {table}")

        self.assertEqual(offenders, [], (
            "New public table(s) created without RLS in the same migration.\n"
            "Until the sweep is re-run, that table is readable — and often "
            "writable — by anyone holding the anon key from the browser "
            "bundle (docs/RLS-AUDIT.md). Add to the same migration:\n\n"
            "    ALTER TABLE public.<table> ENABLE ROW LEVEL SECURITY;\n\n"
            "No policy is needed: the backend uses the service-role key and "
            "bypasses RLS. Do NOT add these to LEGACY_TABLES_WITHOUT_RLS — "
            "that list is frozen history, not an opt-out.\n"
            f"Offenders: {offenders}"))

    def test_the_legacy_allowlist_only_ever_shrinks(self):
        """Every entry must still describe a real (file, table) pair.

        A stale entry means someone fixed a migration — in which case delete
        the line — or renamed a file, which would silently re-open the hole for
        the new name."""
        stale = []
        for fname, table in sorted(LEGACY_TABLES_WITHOUT_RLS):
            path = os.path.join(MIGRATIONS, fname)
            if not os.path.exists(path):
                stale.append(f"{fname} (file is gone)")
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                sql = _strip_comments(fh.read())
            created = {t.lower() for t in _CREATE_TABLE.findall(sql)}
            secured = {t.lower() for t in _ENABLE_RLS.findall(sql)}
            if table not in created or table in secured:
                stale.append(f"{fname}: {table} (now compliant or renamed)")

        self.assertEqual(stale, [], (
            "Stale entries in LEGACY_TABLES_WITHOUT_RLS — delete them so the "
            f"list keeps meaning what it says: {stale}"))


class NewFunctionsRevokeExecuteTests(unittest.TestCase):
    """RULE 2 — migrations/lock_down_public_function_grants.sql.

    No allowlist here on purpose. The rule arrived with the first function in
    the repo, so there is no legacy to grandfather and never should be.
    """

    def _functions_in(self, sql: str) -> set:
        return {f.lower() for f in _CREATE_FUNCTION.findall(sql)}

    def test_every_created_function_revokes_execute_from_public(self):
        offenders = []
        for name in _sql_files():
            with open(os.path.join(MIGRATIONS, name), encoding="utf-8",
                      errors="replace") as fh:
                sql = _strip_comments(fh.read())
            for fn in sorted(self._functions_in(sql)):
                revoke = re.search(
                    r"REVOKE\s+(?:ALL|EXECUTE)[\s\S]{0,200}?ON\s+FUNCTION\s+"
                    r"(?:public\.)?" + re.escape(fn) + r"\s*\(", sql, re.I)
                if not (revoke and re.search(
                        r"FROM\s+PUBLIC", sql[revoke.start():revoke.start() + 400],
                        re.I)):
                    offenders.append(f"{name}: {fn}")

        self.assertEqual(offenders, [], (
            "Function(s) created without revoking EXECUTE from PUBLIC.\n"
            "Postgres grants EXECUTE on a new function to PUBLIC by default "
            "and PostgREST publishes it at /rest/v1/rpc/<name>, so anyone with "
            "the anon key from the browser bundle can call it. RLS does not "
            "cover this — it is table-level. Add to the same migration:\n\n"
            "    REVOKE ALL ON FUNCTION public.<name>(<types>) FROM PUBLIC;\n"
            "    -- plus anon / authenticated, guarded on pg_roles\n"
            "    GRANT EXECUTE ON FUNCTION public.<name>(<types>) "
            "TO service_role;\n\n"
            f"Offenders: {offenders}"))

    def test_every_created_function_revokes_anon_and_authenticated(self):
        """Revoking PUBLIC is not sufficient on Supabase.

        Supabase's ALTER DEFAULT PRIVILEGES grants anon/authenticated on
        functions in `public` DIRECTLY, and a direct grant survives a REVOKE
        aimed at PUBLIC. Both roles have to be named."""
        offenders = []
        for name in _sql_files():
            with open(os.path.join(MIGRATIONS, name), encoding="utf-8",
                      errors="replace") as fh:
                sql = _strip_comments(fh.read())
            if not self._functions_in(sql):
                continue
            for role in ("anon", "authenticated"):
                if not re.search(r"REVOKE[\s\S]{0,600}?\b" + role + r"\b",
                                 sql, re.I) and role not in sql:
                    offenders.append(f"{name}: {role} never revoked")

        self.assertEqual(offenders, [], (
            "Function migration does not revoke anon/authenticated. "
            f"{offenders}"))

    def test_security_definer_functions_pin_their_search_path(self):
        """SECURITY DEFINER runs as the OWNER — it bypasses RLS for whoever
        calls it, which turns a leaked anon key into full write access even
        with the grants locked down. If one is ever genuinely needed, it must
        at minimum pin search_path so a caller cannot shadow `public` with a
        temp schema and have the function resolve to tables they control."""
        offenders = []
        for name in _sql_files():
            with open(os.path.join(MIGRATIONS, name), encoding="utf-8",
                      errors="replace") as fh:
                sql = _strip_comments(fh.read())
            if _SECURITY_DEFINER.search(sql) and not re.search(
                    r"SET\s+search_path", sql, re.I):
                offenders.append(name)

        self.assertEqual(offenders, [], (
            "SECURITY DEFINER function without SET search_path — a search-path "
            f"hijack away from running as the owner: {offenders}"))


_CREATE_FN_BLOCK = re.compile(
    # Params span multiple lines in every real migration here, so the group
    # must cross newlines — an earlier `(.*?)` matched ZERO functions and made
    # the scan below pass vacuously. test_the_scan_is_not_vacuous exists
    # because of that.
    r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:public\.)?(\w+)\s*\("
    r"([\s\S]*?)\)\s*RETURNS[\s\S]*?\$(\w*)\$([\s\S]*?)\$\3\$", re.I)

# Columns that are UUID in the schema but arrive from PostgREST as TEXT.
# `uuid_col = text_param` has no operator and raises 42883 at RUNTIME —
# CREATE FUNCTION succeeds, the first call fails.
_UUID_COLUMNS = {"v2_student_details": "user_id"}

# Files that carry the bug and are FIXED BY A LATER MIGRATION rather than
# edited in place. Editing an applied .sql changes its sha256 and trips the
# runner's drift detection (docs/MIGRATIONS.md), so the broken original has to
# stay exactly as it shipped.
#
# This is not an opt-out. An entry here is a claim that a later migration
# CREATE OR REPLACEs the same function correctly, and
# test_superseded_files_are_actually_superseded enforces that claim.
SUPERSEDED_UUID_TEXT_FILES = {
    "add_token_charge_rpc.sql": "fix_token_charge_uuid_cast.sql",
}


class UuidTextComparisonTests(unittest.TestCase):
    """The bug that made token_charge inert in production for its whole life.

    migrations/add_token_charge_rpc.sql compared `v2_student_details.user_id`
    (UUID) to a `text` parameter. Postgres has no `uuid = text` operator, so it
    raised SQLSTATE 42883 on the first call — but plpgsql resolves SQL at first
    EXECUTION, not at CREATE, so the migration applied cleanly and reported
    success. The app then read 42883 as "function not installed" and silently
    fell back to the legacy path. Nothing looked wrong for its entire lifetime.

    No unit double can catch this: services/db is faked in tests and the fake
    has no column types. Neither can a live-Postgres run against a hand-written
    fixture — the #328 fixture declared user_id as TEXT, which is precisely why
    a "verified against live PostgreSQL" claim was wrong. The only thing that
    catches it cheaply is reading the SQL against the DECLARED schema.
    """

    def test_no_function_compares_a_uuid_column_to_a_text_parameter(self):
        offenders = []
        for name in _sql_files():
            if name in SUPERSEDED_UUID_TEXT_FILES:
                continue
            with open(os.path.join(MIGRATIONS, name), encoding="utf-8",
                      errors="replace") as fh:
                sql = _strip_comments(fh.read())
            for fn, params, _tag, body in _CREATE_FN_BLOCK.findall(sql):
                text_params = {
                    m.group(1)
                    for m in re.finditer(r"(\w+)\s+text\b", params, re.I)
                }
                if not text_params:
                    continue
                # Scope per STATEMENT, not per function body. token_ledger.user_id
                # is TEXT while v2_student_details.user_id is UUID, and both are
                # touched by the same function — so `user_id = p_user_id` is
                # correct in one statement and a runtime error in the next.
                # Checking the whole body cannot tell them apart.
                for stmt in body.split(";"):
                    for table, col in _UUID_COLUMNS.items():
                        if table not in stmt:
                            continue
                        for p in text_params:
                            if re.search(r"\b" + re.escape(col) + r"\s*=\s*"
                                         + re.escape(p) + r"\b(?!\s*::)", stmt):
                                offenders.append(
                                    f"{name}: {fn}() — {table}.{col} (uuid) "
                                    f"= {p} (text)")
                            # ...and the dynamic-SQL form: USING <text_param>.
                            if (re.search(r"\b" + re.escape(col) + r"\s*=\s*\$\d", stmt)
                                    and re.search(r"USING\s+" + re.escape(p) + r"\b", stmt)):
                                offenders.append(
                                    f"{name}: {fn}() — EXECUTE ... {col} = $n "
                                    f"USING {p} (text)")

        self.assertEqual(sorted(set(offenders)), [], (
            "A function compares a UUID column to a TEXT parameter. Postgres "
            "has no `uuid = text` operator: CREATE succeeds and the FIRST CALL "
            "raises 42883, so this ships looking healthy and fails silently "
            "forever after.\n\n"
            "Fix: cast once at the top of the function, guarded —\n\n"
            "    BEGIN\n"
            "        v_uid := p_user_id::uuid;\n"
            "    EXCEPTION WHEN invalid_text_representation THEN\n"
            "        RETURN <degraded result>;\n"
            "    END;\n\n"
            "then use v_uid for that table. See "
            "migrations/fix_token_charge_uuid_cast.sql.\n"
            f"Offenders: {sorted(set(offenders))}"))

    def test_superseded_files_are_actually_superseded(self):
        """An exemption is only honest if the fix really exists, really comes
        LATER in the manifest, and really redefines the same function."""
        with open(os.path.join(MIGRATIONS, "manifest.txt"), encoding="utf-8") as fh:
            order = [ln.split("\t")[-1].strip() for ln in fh
                     if ln.strip() and not ln.startswith("#")]

        for broken, fixer in SUPERSEDED_UUID_TEXT_FILES.items():
            self.assertIn(broken, order, f"{broken} is not in the manifest")
            self.assertIn(fixer, order, f"{fixer} is not in the manifest")
            self.assertLess(order.index(broken), order.index(fixer),
                            f"{fixer} must run AFTER {broken}")

            def fns(fname):
                with open(os.path.join(MIGRATIONS, fname), encoding="utf-8") as fh2:
                    return {f for f, _p, _t, _b in
                            _CREATE_FN_BLOCK.findall(_strip_comments(fh2.read()))}

            shared = fns(broken) & fns(fixer)
            self.assertTrue(shared, (
                f"{fixer} does not redefine any function from {broken}, so the "
                "exemption is unearned"))

    def test_the_scan_is_not_vacuous(self):
        """A scan that matches nothing reports "no offenders" forever.

        The first version of _CREATE_FN_BLOCK used `(.*?)` for the parameter
        list, which cannot cross newlines — and every real function here
        declares its parameters one per line. It matched ZERO functions, so
        the offender check passed while reading nothing at all. Exactly the
        failure mode this repo keeps hitting: a check that can only report
        success is not a check.
        """
        seen = []
        for name in _sql_files():
            with open(os.path.join(MIGRATIONS, name), encoding="utf-8",
                      errors="replace") as fh:
                sql = _strip_comments(fh.read())
            seen += [f"{name}:{fn}" for fn, _p, _t, _b in _CREATE_FN_BLOCK.findall(sql)]

        self.assertGreaterEqual(len(seen), 3, (
            "The function-block regex matched fewer functions than this repo "
            "is known to define — the uuid/text scan is reading nothing. "
            f"Matched: {seen}"))
        joined = " ".join(seen)
        for expected in ("token_charge", "stripe_checkout_grant_credits",
                         "credits_increment"):
            self.assertIn(expected, joined,
                          f"{expected}() is defined in migrations but the scan "
                          "does not see it")

    def test_the_check_actually_catches_the_original_bug(self):
        """A guard nobody has watched fail is a comment. This feeds it the
        exact shape 0241 shipped with and requires a hit."""
        sql = """
        CREATE OR REPLACE FUNCTION public.probe(p_user_id text)
        RETURNS jsonb LANGUAGE plpgsql AS $fn$
        BEGIN
            PERFORM 1 FROM public.v2_student_details
             WHERE user_id = p_user_id FOR UPDATE;
            RETURN '{}'::jsonb;
        END;
        $fn$;
        """
        blocks = _CREATE_FN_BLOCK.findall(sql)
        self.assertTrue(blocks, "the function-block regex stopped matching")
        _fn, params, _tag, body = blocks[0]
        self.assertIn("p_user_id", params)
        self.assertRegex(body, r"\buser_id\s*=\s*p_user_id\b(?!\s*::)")


class TokenChargeFunctionTests(unittest.TestCase):
    """The specific function this rule arrived with. Spot checks, not a parser —
    these are the properties whose absence would be silent and expensive."""

    def setUp(self):
        path = os.path.join(MIGRATIONS, "add_token_charge_rpc.sql")
        self.assertTrue(os.path.exists(path), "add_token_charge_rpc.sql is gone")
        with open(path, encoding="utf-8") as fh:
            self.raw = fh.read()
        self.sql = _strip_comments(self.raw)

    def test_it_is_security_invoker(self):
        self.assertRegex(self.sql, r"SECURITY\s+INVOKER")
        self.assertNotRegex(self.sql, r"SECURITY\s+DEFINER")

    def test_it_locks_the_account_row_before_deciding_anything(self):
        """The lock is the fix for the probe/debit race. Without FOR UPDATE
        this is the old TOCTOU with extra steps."""
        self.assertRegex(self.sql, r"FOR\s+UPDATE")
        lock = self.sql.upper().index("FOR UPDATE")
        for later in ("INSERT INTO PUBLIC.TOKEN_LEDGER", "EXECUTE FORMAT"):
            self.assertLess(lock, self.sql.upper().index(later),
                            f"{later} happens before the row lock")

    def test_the_ledger_insert_cannot_swallow_a_conflict(self):
        """ON CONFLICT DO NOTHING here would let the debit stand with no row —
        reinstating exactly the half-state this function removes."""
        self.assertNotRegex(self.sql, r"ON\s+CONFLICT")

    def test_it_grants_execute_to_service_role_only(self):
        self.assertRegex(self.sql, r"GRANT\s+EXECUTE[\s\S]{0,200}service_role")
        self.assertRegex(self.sql, r"REVOKE\s+ALL[\s\S]{0,200}FROM\s+PUBLIC")
        for role in ("anon", "authenticated"):
            self.assertIn(role, self.sql, f"{role} is never revoked")

    def test_it_is_replayable(self):
        """Migrations in this repo are idempotent; re-running must be a no-op."""
        self.assertRegex(self.sql, r"CREATE\s+OR\s+REPLACE\s+FUNCTION")

    def test_the_python_caller_and_the_function_agree_on_the_parameters(self):
        """A renamed parameter is a runtime-only failure: PostgREST reports it
        as "function not found", which this codebase treats as "not migrated"
        and silently answers from the legacy non-atomic path. It would look
        like nothing was wrong."""
        import services.token_account as ta
        declared = set(re.findall(r"\b(p_[a-z_]+)\b",
                                  self.sql[:self.sql.index("AS $fn$")]))
        with open(os.path.join(os.path.dirname(MIGRATIONS),
                               "services", "token_account.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        block = src[src.index("db.client.rpc("):]
        passed = set(re.findall(r'"(p_[a-z_]+)"', block[:block.index("})")]))
        self.assertEqual(passed, declared,
                         "services/token_account.py and add_token_charge_rpc.sql "
                         "disagree on the parameter list")
        self.assertEqual(ta._CHARGE_RPC, "token_charge")


if __name__ == "__main__":
    unittest.main()
