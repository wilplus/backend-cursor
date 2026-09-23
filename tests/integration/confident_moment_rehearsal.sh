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
#   CONFIDENT_MOMENT_CHECKPOINTS               optional, space-separated
#                                              <released file>=<database> pairs:
#                                              right after that file applies, the
#                                              lane is cloned under that name
#                                              (scripts/rehearsal_tier.sh cuts the
#                                              canary and D4 lanes this way)
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

log="$(mktemp "${TMPDIR:-/tmp}/confident-moment-rehearsal.XXXXXX")"
ok=0; skipped=0

# The narrow prerequisite files are mutually exclusive alternatives: each is a
# standalone fixture that CREATEs overlapping base tables and sets
# `\set ON_ERROR_STOP on` itself. Composing them requires a preprocessed copy
# whose CREATEs are idempotent and whose error stop is off. They are copied as
# a set into one directory so their `\ir` includes still resolve.
fixture_dir="$(mktemp -d "${TMPDIR:-/tmp}/confident-moment-fixtures.XXXXXX")"
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
    checkpoint_after "$(basename "$1")"
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
# A chain checkpoint: the lane as it stands right after a named released file,
# cloned under a disposable name. Suites written against an earlier slice of
# the chain (later migrations install triggers their fixture helpers trip) run
# against a checkpoint, not the finished lane. Requested through
# CONFIDENT_MOMENT_CHECKPOINTS; an existing clone is kept, never rebuilt.
checkpoint_after() {
  local pair name
  for pair in ${CONFIDENT_MOMENT_CHECKPOINTS:-}; do
    [ "${pair%%=*}" = "$1" ] || continue
    name="${pair#*=}"
    case "$name" in
      willab_confident_moment_*) ;;
      *) echo "Refusing a non-disposable checkpoint name: $name" >&2; exit 2 ;;
    esac
    if [ "$(psql -X -tAc "SELECT 1 FROM pg_database WHERE datname='$name'" -d postgres 2>/dev/null)" = 1 ]; then
      printf '  checkpoint %s (exists; kept)\n' "$name"; continue
    fi
    if psql -q -d postgres -v ON_ERROR_STOP=1 -X -c "CREATE DATABASE \"$name\" TEMPLATE \"$DB\"" >>"$log" 2>&1; then
      printf '  checkpoint %s -> %s\n' "$1" "$name"
    else
      printf '  FAILED  checkpoint %s\n' "$name" >&2
      grep -m2 'ERROR:' "$log" | sed 's/^/          /' >&2
      exit 1
    fi
  done
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
  # Build the real 0297 RecordingAttempt -> Take boundary rather than retaining
  # the narrow three/four-column stand-ins from the MLC-2 prerequisite file.
  # At this point nothing else references those two stand-ins, so a disposable
  # released rehearsal can replace them without CASCADE.  The v2 session and
  # append-only helper represent objects already released before 0297.
  soft tests/integration/take_feedback_policy_v3_prerequisites.sql
  psql -q -d "$DB" -v ON_ERROR_STOP=1 \
    -c "ALTER TABLE public.v2_sessions
        ADD COLUMN IF NOT EXISTS project_id uuid" \
    -c "DROP TABLE public.takes" \
    -c "DROP TABLE public.recording_attempts" \
    -c "CREATE OR REPLACE FUNCTION public.reject_canonical_feedback_mutation()
        RETURNS trigger LANGUAGE plpgsql AS \$\$
        BEGIN
          RAISE EXCEPTION 'canonical feedback evidence is append-only';
        END;
        \$\$" >>"$log" 2>&1
  hard migrations/add_processing_jobs.sql
  hard migrations/add_recording_attempt_take_boundary.sql
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
  psql -q -d "$DB" -c "ALTER TABLE public.v2_sessions ADD COLUMN IF NOT EXISTS project_id uuid" >>"$log" 2>&1
  hard migrations/add_take_feedback_policy_v3_shadow.sql
  soft tests/integration/phase1_processing_prerequisites.sql
  hard migrations/add_phase1_processing_boundary.sql
  hard migrations/add_phase1_deletion_completion.sql
  hard migrations/add_take_feedback_policy_universal_v3_transition.sql
fi

soft tests/integration/mlc3_exercise_foundation_prerequisites.sql
hard migrations/add_mlc3_exercise_dark_foundation.sql

# B-4 (audit 2026-09-22). THE LANE HAD NO PRACTICE OBJECT TO PURGE, which is
# why nothing caught that `freeze_phase1_purge_inventory_v4` and
# `mark_phase1_storage_object_purged_v1` do not accept one. The orchestrator
# has emitted `source_relation = 'processing_practice_objects'` since 0334;
# both functions raise on it, so a subject with a single practice recording
# cannot be purged at all. The narrow practice tables 0334 references are
# already laid down by the fixture above; the released 0279 that defines them
# for real is NOT applied here, because it builds diagnostic_exercise first
# and that references public.journal_post — the whole Journal chain, a surface
# this lane does not carry and has no reason to.
hard migrations/add_practice_audio_objects.sql
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
    -c "CREATE UNIQUE INDEX IF NOT EXISTS confident_moment_narrow_speaker_split_identity_idx
        ON public.ml_speaker_split_assignments(speaker_id, split_policy_version)" \
    -c "ALTER TABLE public.projects ALTER COLUMN display_name DROP NOT NULL" \
    -c "ALTER TABLE public.ml_speakers ALTER COLUMN identity_version DROP NOT NULL" >>"$log" 2>&1
fi

# 0353 replaces the two purge writers, so it must land after BOTH of their
# current definitions: mark_phase1_storage_object_purged_v1 from
# add_phase1_deletion_completion.sql and freeze_phase1_purge_inventory_v4 from
# add_mlc3_exercise_dark_foundation.sql. The narrow lane applies the deletion
# file in the block above, which is why this sits below it rather than beside
# the practice registry.
hard migrations/deletion_reaches_practice_objects.sql

# 0354 replaces issue_phase1_provider_permit_v1 and
# resolve_phase1_acquisition_principal_v1, both from
# add_phase1_processing_boundary.sql, which the narrow lane also applies in the
# block above.
hard migrations/authorization_binds_to_acquirer.sql

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
# 0355 replaces record_mlc3_self_speaker_target_v1, which the file above
# defines — so it must land here, not at the end of the chain. The d4 lane is
# cloned from a checkpoint cut right after this pair, and the suite that
# exercises the speaker writer runs in that clone.
hard migrations/speaker_identity_the_table_accepts.sql
# 0356 adds accept_phase1_processing_authorization_v2 beside v1, which
# add_phase1_processing_boundary.sql defines and 0335 last replaced.
hard migrations/a_receipt_can_record_an_optional_yes.sql
# 0357 replaces get_phase1_processing_authorization_v1, from the boundary file.
hard migrations/status_knows_a_reacceptance.sql

# The pending migration is unnumbered and absent from the manifest; applying it
# twice is the apply/reapply idempotency check.
hard migrations/add_confident_moment_coaching_bundle_v1.sql
hard migrations/add_confident_moment_coaching_bundle_v1.sql

echo "Built $DB ($ok released migrations applied, $skipped fixture files)"
echo "  export CONFIDENT_MOMENT_REHEARSAL_DSN=postgresql://$PGUSER@$PGHOST:$PGPORT/$DB"
rm -f "$log"
