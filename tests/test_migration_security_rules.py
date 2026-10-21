"""
STORY    As a developer, I want every new table to switch on RLS and every new
         function to revoke EXECUTE from public, anon and authenticated, so
         that the browser's anon key can never read tables or call
         money-moving functions again.
OUTCOME
  O1  CI goes red on a new migration that creates a public table without
      ENABLE ROW LEVEL SECURITY in the same file.
  O2  CI goes red on a new function that does not revoke EXECUTE from PUBLIC.
  O3  CI goes red on a new function that is not itself revoked from anon AND
      authenticated (a REVOKE on that function naming both roles, or a DO
      block that revokes that function looping over both). Supabase grants
      both roles directly, so a PUBLIC revoke alone leaves them in.
  O4  A SECURITY DEFINER migration pins its search_path.
  O5  CI goes red on a new migration that creates a public table without
      granting service_role on it in the same file.
PROVES   O1 -> test_every_new_public_table_enables_rls_in_its_own_migration
         O2 -> test_every_created_function_revokes_execute_from_public
         O3 -> test_every_created_function_revokes_anon_and_authenticated
         O4 -> test_security_definer_functions_pin_their_search_path
         O5 -> test_every_new_public_table_grants_service_role_in_its_own_migration
WHY      2026-07-25: 57 tables shipped readable with the anon key
         (docs/RLS-AUDIT.md); RLS says nothing about functions, so the
         function rule arrived with the first .rpc() on 2026-08-03. The two
         frozen lists below describe FILES that predate a rule (applied
         migrations cannot be edited); they may only shrink. From 2026-10-30
         Supabase no longer grants a new public table to the Data API roles,
         so a table the backend reaches through PostgREST answers 42501 until
         a migration grants service_role on it.
"""
from __future__ import annotations

import functools
import os
import re
import unittest

MIGRATIONS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")

_CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?([a-zA-Z_]\w*)", re.I)
_ENABLE_RLS = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:public\.)?([a-zA-Z_]\w*)\s+"
    r"ENABLE\s+ROW\s+LEVEL\s+SECURITY", re.I)
_CREATE_FUNCTION = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:public\.)?([a-zA-Z_]\w*)\s*\(", re.I)
_SECURITY_DEFINER = re.compile(r"SECURITY\s+DEFINER", re.I)

# A migration may secure a whole family of objects with one DO block that loops
# over an ARRAY of names and EXECUTEs the DDL dynamically. The static patterns
# above cannot see through `format()`, so without this the loop reads as a
# migration that created twenty tables and protected none of them.
#
# Scoped deliberately: a name only counts when the SAME DO block both lists it
# and performs the dynamic statement. A bare ARRAY of names elsewhere in the
# file earns nothing, so this recognises the idiom without opening a loophole.
_DO_BLOCK = re.compile(r"DO\s+(\$[a-zA-Z_]*\$)(.*?)\1\s*;", re.I | re.S)
_QUOTED = re.compile(r"'([^']+)'")
_DYNAMIC_ENABLE_RLS = re.compile(
    r"EXECUTE\s+format\s*\(\s*'ALTER\s+TABLE\s+public\.%I\s+"
    r"ENABLE\s+ROW\s+LEVEL\s+SECURITY'", re.I)
_DYNAMIC_REVOKE = re.compile(
    r"EXECUTE\s+'REVOKE\s+ALL\s+ON\s+FUNCTION\s*'\s*\|\|", re.I)


@functools.lru_cache(maxsize=None)
def _manifest_order() -> list:
    path = os.path.join(os.path.dirname(MIGRATIONS), "migrations", "manifest.txt")
    with open(path, encoding="utf-8") as fh:
        return [line.rstrip("\n").split("\t")[1]
                for line in fh if "\t" in line]


@functools.lru_cache(maxsize=None)
def _created_and_revoked(name: str) -> frozenset:
    """Functions this migration both creates and revokes (read once)."""
    path = os.path.join(MIGRATIONS, name)
    if not os.path.exists(path):
        return frozenset()
    sql = _read(name)
    return frozenset(
        fn for fn in {f.lower() for f in _CREATE_FUNCTION.findall(sql)}
        if re.search(r"REVOKE\s+(?:ALL|EXECUTE)[\s\S]{0,200}?ON\s+FUNCTION\s+"
                     r"(?:public\.)?" + re.escape(fn) + r"\s*\(", sql, re.I))


@functools.lru_cache(maxsize=None)
def _revoked_by_an_earlier_migration(name: str) -> frozenset:
    """Functions an earlier manifest migration both created and revoked."""
    order = _manifest_order()
    if name not in order:
        return frozenset()
    done: set = set()
    for earlier in order[:order.index(name)]:
        done |= _created_and_revoked(earlier)
    return frozenset(done)


def _dynamic_names(sql: str, trigger: "re.Pattern") -> set:
    """Names secured by a DO block that loops an ARRAY and EXECUTEs `trigger`.

    Harvests every quoted literal in the block rather than trying to bound the
    ARRAY: these lists run to dozens of entries across many lines, and a
    bracket-delimited match silently truncates them — which is the same class
    of blind spot this helper exists to remove.
    """
    found = set()
    for _tag, body in _DO_BLOCK.findall(sql):
        if not trigger.search(body):
            continue
        for name in _QUOTED.findall(body):
            found.add(name.split("(")[0].replace("public.", "").strip().lower())
    return found


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


# ── Frozen: migrations whose functions name no anon/authenticated revoke of
# their own, applied after the 0242 sweep (lock_down_public_function_grants)
# and before the per-function rule (2026-10-19). Listed by FILE because an
# applied migration cannot change. NEVER ADD TO THIS LIST.
LEGACY_FILES_WITHOUT_ROLE_REVOKE = frozenset({
    "add_canonical_project_ownership.sql",
    "add_confident_moment_coaching_bundle_v1.sql",
    "add_mlc2_confidence_dark_contracts.sql",
    "add_mlc2_foundation.sql",
})
#: The 0242 sweep revoked every function that existed then from PUBLIC, anon
#: and authenticated; a migration before it in the manifest is covered by it.
_FUNCTION_SWEEP = "lock_down_public_function_grants.sql"
_ROLES = ("anon", "authenticated")
_REVOKE_ON_FUNCTION = re.compile(r"REVOKE\s+(?:ALL|EXECUTE)[^;]*?ON\s+FUNCTION", re.I)

# ── From 2026-10-30 Supabase stops granting a new `public` table to anon,
# authenticated and service_role. The backend reaches every table through
# PostgREST as service_role, so a new table without its own GRANT answers
# 42501, and a best-effort writer swallows that. Tables created up to this
# migration were granted by the old default when they ran in production, and
# Supabase leaves existing grants alone. A database rebuilt from these files
# after that date (new project, preview branch, `supabase db reset`) gets
# those older tables without grants.
_LAST_MIGRATION_BEFORE_GRANT_RULE = "the_founder_edits_wills_questions.sql"
_GRANT_ON_TABLE = re.compile(
    r"GRANT\s+[^;]*?\bON\s+(?:TABLE\s+)?(?!FUNCTION\b|SEQUENCE\b|SCHEMA\b|ALL\b)"
    r"([^;]*?)\s+TO\s+([^;]*);", re.I)
_DYNAMIC_GRANT_SERVICE_ROLE = re.compile(
    r"format\s*\(\s*'GRANT\s[^']*?\bON\s+(?:TABLE\s+)?public\.%I\s+"
    r"TO\s+service_role'", re.I)


def _granted_to_service_role(sql: str) -> set:
    """Tables this SQL grants service_role on: a static GRANT ... ON
    [TABLE] t[, t2] TO ... service_role, or the DO-block ARRAY loop that
    EXECUTEs format('GRANT ... ON public.%I TO service_role')."""
    granted = set()
    for tables, roles in _GRANT_ON_TABLE.findall(sql):
        if re.search(r"\bservice_role\b", roles, re.I):
            granted |= {t.strip().strip('"').lower().replace("public.", "")
                        for t in tables.split(",")}
    return granted | _dynamic_names(sql, _DYNAMIC_GRANT_SERVICE_ROLE)


@functools.lru_cache(maxsize=None)
def _read(name: str) -> str:
    with open(os.path.join(MIGRATIONS, name), encoding="utf-8",
              errors="replace") as fh:
        return _strip_comments(fh.read())


def _roles_revoked(sql: str, fn: str) -> set:
    """The roles (of anon/authenticated) this SQL revokes `fn` from: a static
    REVOKE ... ON FUNCTION fn(...) FROM <roles>; or a DO block that names fn,
    revokes a function, and names the role (the FOREACH role ... %I idiom)."""
    roles: set = set()
    for m in re.finditer(r"REVOKE\s+(?:ALL|EXECUTE)[^;]*?ON\s+FUNCTION\s+(?:public\.)?"
                         + re.escape(fn) + r"\s*\([^;]*?\bFROM\b([^;]*);", sql, re.I):
        roles |= {r for r in _ROLES if re.search(rf"\b{r}\b", m.group(1), re.I)}
    for _tag, body in _DO_BLOCK.findall(sql):
        if (_REVOKE_ON_FUNCTION.search(body)
                and re.search(rf"\b{re.escape(fn)}\b", body, re.I)):
            roles |= {r for r in _ROLES
                      if re.search(rf"'{r}'|\bFROM\s+{r}\b", body, re.I)}
    return roles


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
            secured |= _dynamic_names(sql, _DYNAMIC_ENABLE_RLS)
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


class NewTablesGrantServiceRoleTests(unittest.TestCase):
    """RULE 3 — Supabase, from 2026-10-30: no automatic Data API grant on a
    new public table. No allowlist: the rule starts after the last migration
    that ran under the old default."""

    def test_every_new_public_table_grants_service_role_in_its_own_migration(self):
        order = _manifest_order()
        last_before = order.index(_LAST_MIGRATION_BEFORE_GRANT_RULE)
        offenders = []
        for name in _sql_files():
            # A file outside the manifest never runs; migrate.py verify fails
            # CI on it already.
            if name not in order or order.index(name) <= last_before:
                continue
            sql = _read(name)
            created = {t.lower() for t in _CREATE_TABLE.findall(sql)}
            for table in sorted(created - _granted_to_service_role(sql)):
                offenders.append(f"{name}: {table}")

        self.assertEqual(offenders, [], (
            "New public table(s) created without a grant to service_role.\n"
            "Since 2026-10-30 Supabase grants a new public table to no one, "
            "so the backend's PostgREST calls on it answer 42501 permission "
            "denied. Add to the same migration, with only the privileges the "
            "backend uses:\n\n"
            "    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.<table> "
            "TO service_role;\n\n"
            "Do not grant anon or authenticated: the browser reaches tables "
            "only through Flask (docs/RLS-AUDIT.md).\n"
            f"Offenders: {offenders}"))


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
            dynamic = _dynamic_names(sql, _DYNAMIC_REVOKE)
            for fn in sorted(self._functions_in(sql)):
                if fn in dynamic:
                    continue
                if fn in _revoked_by_an_earlier_migration(name):
                    # CREATE OR REPLACE preserves the existing ACL, so
                    # replacing a function an earlier migration already
                    # revoked re-opens nothing. Only counted when that earlier
                    # migration both CREATEs and REVOKEs it, so a brand-new
                    # function still has to carry its own REVOKE.
                    continue
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
        """Revoking PUBLIC is not sufficient on Supabase: its default
        privileges grant anon/authenticated on functions in `public`
        DIRECTLY, and a direct grant survives a REVOKE aimed at PUBLIC. A role
        name elsewhere in the file (a table revoke, the word "Canonical") is
        not a revoke of this function."""
        order = _manifest_order()
        sweep = order.index(_FUNCTION_SWEEP)
        offenders = []
        for name in _sql_files():
            if name in LEGACY_FILES_WITHOUT_ROLE_REVOKE:
                continue
            if name in order and order.index(name) < sweep:
                continue
            sql = _read(name)
            earlier = [e for e in order[:order.index(name)]] if name in order else []
            for fn in sorted(self._functions_in(sql)):
                roles = _roles_revoked(sql, fn)
                for prior in earlier:
                    if len(roles) == len(_ROLES):
                        break
                    if not os.path.exists(os.path.join(MIGRATIONS, prior)):
                        continue
                    prior_sql = _read(prior)
                    if fn in self._functions_in(prior_sql):
                        # CREATE OR REPLACE keeps the ACL an earlier
                        # migration set on the same function.
                        roles |= _roles_revoked(prior_sql, fn)
                missing = [r for r in _ROLES if r not in roles]
                if missing:
                    offenders.append(f"{name}: {fn} not revoked from {', '.join(missing)}")

        self.assertEqual(offenders, [], (
            "Function(s) not revoked from anon/authenticated. Add, guarded on "
            "pg_roles:\n    REVOKE ALL ON FUNCTION public.<name>(<types>) "
            f"FROM anon, authenticated;\nOffenders: {offenders}"))

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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
