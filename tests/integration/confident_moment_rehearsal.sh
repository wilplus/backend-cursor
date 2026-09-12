#!/usr/bin/env bash
# Confident Moment Coaching Bundle — disposable rehearsal fixture builder.
#
# Verification infrastructure only. This builds throwaway local databases; it
# is never a production migration and applies nothing to a real environment.
#
# Two lanes exist because the suite's evidence needs both, and neither alone is
# sufficient:
#
#   released  Built from this repository's own released migrations. This is the
#             lane that catches schema-shaped drift — it is how the D11 trigger
#             registry was found to name two relations that do not exist
#             (`coach_ideal_text` / `user_ideal_edits`), which made the pending
#             migration unable to apply to production. Test helpers cannot run
#             here: they assume narrow fixture table shapes.
#
#   narrow    The tests/integration/*_prerequisites.sql narrow copies are laid
#             down FIRST, so their shapes win over the released CREATE TABLE IF
#             NOT EXISTS statements that follow, then a widen file adds the
#             released columns back as NULLABLE trailing columns. This is the
#             shape the behavioural helpers were written against (e.g. a
#             five-column processing_policy_versions inserted positionally), and
#             therefore the only lane that can execute the concurrency and
#             authorization race tests. Released files still run, for their
#             functions and triggers; a short, explicit relaxation block then
#             restores the narrow constraints the helpers assume.
#
# Usage:
#   tests/integration/confident_moment_rehearsal.sh released [dbname]
#   tests/integration/confident_moment_rehearsal.sh narrow   [dbname]
#
# Environment:
#   CONFIDENT_MOMENT_PGHOST / PGPORT / PGUSER  libpq connection to a DISPOSABLE
#                                              local cluster (never production)
#   CONFIDENT_MOMENT_TEST_PYTHON               python with pytest + psycopg2
#
# The database name must start with willab_confident_moment_ — the pytest
# fixture refuses anything else.
set -uo pipefail
cd "$(dirname "$0")/../.."

LANE="${1:?Supply a lane: released | narrow}"
DB="${2:-willab_confident_moment_${LANE}}"
case "$DB" in
  willab_confident_moment_*) ;;
  *) echo "Refusing a non-disposable database name: $DB" >&2; exit 2 ;;
esac

export PGHOST="${CONFIDENT_MOMENT_PGHOST:-127.0.0.1}"
export PGPORT="${CONFIDENT_MOMENT_PGPORT:-55432}"
export PGUSER="${CONFIDENT_MOMENT_PGUSER:-postgres}"
export LC_ALL=C LANG=C

log="$(mktemp -t confident-moment-rehearsal)"
ok=0; skipped=0

# The narrow prerequisite files are mutually exclusive alternatives: each is a
# standalone fixture that CREATEs overlapping base tables and sets
# `\set ON_ERROR_STOP on` itself. Composing them requires a preprocessed copy
# whose CREATEs are idempotent and whose error stop is off. They are copied as
# a set into one directory so their `\ir` includes still resolve.
fixture_dir="$(mktemp -d -t confident-moment-fixtures)"
trap 'rm -rf "$fixture_dir" "$log"' EXIT
for source_file in tests/integration/*.sql; do
  sed -e 's/^\\set ON_ERROR_STOP on/\\set ON_ERROR_STOP off/' \
      -e 's/\bCREATE TABLE \(IF NOT EXISTS \)\?/CREATE TABLE IF NOT EXISTS /g' \
      -e 's/\bCREATE INDEX \(IF NOT EXISTS \)\?/CREATE INDEX IF NOT EXISTS /g' \
      -e 's/\bCREATE UNIQUE INDEX \(IF NOT EXISTS \)\?/CREATE UNIQUE INDEX IF NOT EXISTS /g' \
      "$source_file" > "$fixture_dir/$(basename "$source_file")"
done

# A released migration must apply cleanly; a narrow prerequisite copy is one of
# several mutually exclusive alternatives, so it is applied best-effort and the
# statements that collide with an already-present definition are skipped.
hard() {
  : > "$log"
  if psql -q -d "$DB" -v ON_ERROR_STOP=1 -X -f "$1" >"$log" 2>&1; then
    ok=$((ok + 1)); printf '  ok      %s\n' "$(basename "$1")"
  else
    printf '  FAILED  %s\n' "$(basename "$1")" >&2
    grep -m2 'ERROR:' "$log" | sed 's/^/          /' >&2
    exit 1
  fi
}
soft() {
  psql -q -d "$DB" -X -f "$fixture_dir/$(basename "$1")" >>"$log" 2>&1
  skipped=$((skipped + 1)); printf '  fixture %s\n' "$(basename "$1")"
}

echo "Building $LANE lane in $DB"
createdb "$DB" 2>/dev/null || echo "  (database already exists; reusing)"
psql -q -d "$DB" -v ON_ERROR_STOP=1 \
  -c "CREATE SCHEMA IF NOT EXISTS extensions" \
  -c "CREATE EXTENSION IF NOT EXISTS pgcrypto SCHEMA extensions" \
  -c "CREATE EXTENSION IF NOT EXISTS pgcrypto" \
  -c "CREATE SCHEMA IF NOT EXISTS auth" \
  -c "CREATE TABLE IF NOT EXISTS auth.users(
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), email text,
        raw_user_meta_data jsonb DEFAULT '{}'::jsonb,
        created_at timestamptz DEFAULT now())" \
  -c "ALTER DATABASE $DB SET search_path=public,extensions" >>"$log" 2>&1
for role in anon authenticated service_role; do
  psql -q -d "$DB" -c "DO \$\$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='$role') THEN CREATE ROLE $role NOLOGIN; END IF; END \$\$" >>"$log" 2>&1
done
psql -q -d "$DB" -c "GRANT USAGE ON SCHEMA auth,extensions TO anon,authenticated,service_role" >>"$log" 2>&1

hard migrations/add_coach_users_table.sql

if [ "$LANE" = "narrow" ]; then
  # Narrow copies are laid down FIRST so their shapes win: every released
  # CREATE TABLE below is IF NOT EXISTS and therefore skips them. The widen
  # file then adds, as NULLABLE trailing columns, whatever the released files
  # reference. Column order and nullability of the narrow copies are untouched,
  # so the positional INSERTs in the behavioural helpers keep working.
  soft tests/integration/mlc2_rehearsal_prerequisites.sql
  soft tests/integration/mlc3_exercise_foundation_prerequisites.sql
  soft tests/integration/mlc3_assignment_prerequisites.sql
  soft tests/integration/rpq_restoration_prerequisites.sql
  soft tests/integration/ideal_text_core_snapshot_prerequisites.sql
  soft tests/integration/confident_moment_narrow_widen.sql
  # The narrow copies define this with a different return type than MLC-2 does.
  psql -q -d "$DB" -c "DROP FUNCTION IF EXISTS public.assign_ml_speaker_split_v1(uuid,text)" >>"$log" 2>&1
else
  soft tests/integration/mlc2_rehearsal_prerequisites.sql
fi

hard migrations/add_mlc2_foundation.sql
hard migrations/add_mlc2_confidence_dark_contracts.sql
hard migrations/add_mlc2_confidence_producer_dark_integration.sql
hard migrations/add_mlc2_confidence_canary_readiness.sql
hard migrations/add_mlc2_consent_configuration.sql
hard migrations/fix_mlc2_pgcrypto_search_path.sql

if [ "$LANE" = "released" ]; then
  # Real phase-1 tables. These replace the narrow copies the helpers expect,
  # which is exactly why this lane runs schema checks and not behaviour.
  soft tests/integration/take_feedback_policy_v3_prerequisites.sql
  psql -q -d "$DB" -c "ALTER TABLE public.v2_sessions ADD COLUMN IF NOT EXISTS project_id uuid" >>"$log" 2>&1
  hard migrations/add_take_feedback_policy_v3_shadow.sql
  soft tests/integration/phase1_processing_prerequisites.sql
  hard migrations/add_phase1_processing_boundary.sql
  hard migrations/add_phase1_deletion_completion.sql
  hard migrations/add_take_feedback_policy_universal_v3_transition.sql
fi

soft tests/integration/mlc3_exercise_foundation_prerequisites.sql
hard migrations/add_mlc3_exercise_dark_foundation.sql
soft tests/integration/mlc3_assignment_prerequisites.sql
hard migrations/add_mlc3_dark_assignment_frames.sql
soft tests/integration/rpq_restoration_prerequisites.sql
soft tests/integration/ideal_text_core_snapshot_prerequisites.sql

# owner_principals.user_id references auth.users, which is a stub in a
# disposable cluster (real Supabase owns that table). The behavioural helpers
# mint principals with synthetic user ids, so the constraint is a fixture
# artifact rather than a property under test. Disposable-only.
psql -q -d "$DB" -c "ALTER TABLE public.owner_principals
    DROP CONSTRAINT IF EXISTS owner_principals_user_id_fkey" >>"$log" 2>&1

# Columns the narrow copies omit but the released ideal-text/feedback chain
# reads. Additive and disposable-only.
psql -q -d "$DB" -c "ALTER TABLE public.v2_sessions
    ADD COLUMN IF NOT EXISTS project_id uuid,
    ADD COLUMN IF NOT EXISTS take_index integer DEFAULT 1,
    ADD COLUMN IF NOT EXISTS recording_kind text DEFAULT 'spoken',
    ADD COLUMN IF NOT EXISTS paired_session_id uuid,
    ADD COLUMN IF NOT EXISTS analysis_state text DEFAULT 'ready',
    ADD COLUMN IF NOT EXISTS coach_review_assigned_to uuid" >>"$log" 2>&1
psql -q -d "$DB" -c "ALTER TABLE public.evidence_spans
    ADD COLUMN IF NOT EXISTS audio_ref text,
    ADD COLUMN IF NOT EXISTS take_id uuid,
    ADD COLUMN IF NOT EXISTS technical_metadata jsonb,
    ADD COLUMN IF NOT EXISTS task_type text" >>"$log" 2>&1

if [ "$LANE" = "narrow" ]; then
  # The narrow processing_purpose_registry copy omits columns the released
  # phase-1 file writes. Additive, disposable-only, and it makes the d4 helper
  # _enable_coach_review_for_fixture take its richer branch.
  hard migrations/add_processing_jobs.sql
  soft tests/integration/confident_moment_narrow_widen.sql
  psql -q -d "$DB" -c "ALTER TABLE public.processing_purpose_registry
      ADD COLUMN IF NOT EXISTS phase text,
      ADD COLUMN IF NOT EXISTS operational boolean NOT NULL DEFAULT false,
      ADD COLUMN IF NOT EXISTS authorizes_processing boolean NOT NULL DEFAULT false,
      ADD COLUMN IF NOT EXISTS capability_version text,
      ADD COLUMN IF NOT EXISTS reviewed_at timestamptz,
      ADD COLUMN IF NOT EXISTS retention_control_version text,
      ADD COLUMN IF NOT EXISTS deletion_control_version text,
      ADD COLUMN IF NOT EXISTS rights_control_version text" >>"$log" 2>&1
  # The D11 writer registry requires accept_phase1_processing_authorization_v1
  # and the purge writers. This file creates its tables with
  # CREATE TABLE IF NOT EXISTS and only adds RLS to existing ones, so applying
  # it AFTER the narrow fixtures installs the released functions while leaving
  # the narrow table shapes the behavioural helpers depend on untouched.
  hard migrations/add_phase1_processing_boundary.sql
  hard migrations/add_phase1_deletion_completion.sql
fi

if [ "$LANE" = "narrow" ]; then
  # The narrow fixture copies never carried these released constraints; this
  # lane only acquires them because phase-1 is applied above for its writer
  # functions. The behavioural helpers mint one active policy and one speaker
  # per context, so restore the narrow shape they were written against. The
  # released lane keeps all of them — production-shaped checking happens there.
  psql -q -d "$DB" \
    -c "DROP INDEX IF EXISTS public.processing_one_active_policy_idx" \
    -c "ALTER TABLE public.projects ALTER COLUMN display_name DROP NOT NULL" \
    -c "ALTER TABLE public.ml_speakers ALTER COLUMN identity_version DROP NOT NULL" >>"$log" 2>&1
fi

hard migrations/add_ideal_text_core_snapshot.sql
hard migrations/fix_ideal_text_core_pgcrypto_search_path.sql
hard migrations/add_mlc3_n1_source_pattern_provenance.sql
hard migrations/add_canonical_feedback_data_contract.sql
hard migrations/add_feedback_v3_serving_restoration.sql
hard migrations/add_mlc3_practice_foundation_restoration.sql
hard migrations/add_mlc3_fresh_offer_and_paired_review_restoration.sql
hard migrations/add_rooting_phrase_qualification_v1.sql
hard migrations/add_coach_guidance_delivery_d3.sql
hard migrations/add_mlc3_first_client_service_d2.sql
hard migrations/add_mlc3_coach_inline_exercise_authoring_d5.sql
hard migrations/add_mlc3_founder_canary_security_closure.sql
hard migrations/add_mlc3_general_user_service_d4.sql

# The pending migration is unnumbered and absent from the manifest; applying it
# twice is the apply/reapply idempotency check.
hard migrations/pending/add_confident_moment_coaching_bundle_v1.sql
hard migrations/pending/add_confident_moment_coaching_bundle_v1.sql

echo "Built $DB ($ok released migrations applied, $skipped fixture files)"
echo "  export CONFIDENT_MOMENT_REHEARSAL_DSN=postgresql://$PGUSER@$PGHOST:$PGPORT/$DB"
rm -f "$log"
