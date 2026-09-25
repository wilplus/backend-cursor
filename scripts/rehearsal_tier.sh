#!/usr/bin/env bash
#
# rehearsal_tier.sh — run the tests/*_postgres.py suites against a DISPOSABLE
# local PostgreSQL that this script builds and destroys.
#
# WHY THIS EXISTS (audit Q-T2, founder decision 2026-09-14). Ten test modules
# only run against a database; each gates itself on its own *_REHEARSAL_DSN and,
# with the variable unset, reported ~260 cases as SKIPPED on every run — "ran,
# chose not to" when the truth was "never runnable here". conftest.py now
# DESELECTS them by default and reports them as NOT RUN; this script is the one
# documented way to run them, and scripts/local_ci.sh calls it when a change
# touches a migration or an MLC-3 storage path (the trigger is the change, not
# discipline).
#
# WHAT IT BUILDS. One throwaway cluster on a Unix socket under /tmp/willab-*
# (the fixtures refuse any other host), one template database built by the
# checked-in recipe tests/integration/confident_moment_rehearsal.sh (narrow
# lane: every prerequisites file, then every released migration from MLC-2
# through 0327, applied twice for idempotency), then one CLONE of that
# template per lane, named with the prefix each suite's fixture demands:
#
#   willab_m33_*                MLC3_REHEARSAL_DSN                dark assignments, N1, RPQ
#   willab_service_*            MLC3_FIRST_CLIENT_REHEARSAL_DSN   First-Client Service D2
#   willab_d3_*                 COACH_GUIDANCE_REHEARSAL_DSN      Coach Guidance D3, inline authoring D5
#   willab_d3_*  (own clone)    MLC3_CANARY_READINESS_REHEARSAL_DSN founder canary readiness
#   willab_ga_*  (as TEMPLATE)  MLC3_GENERAL_USER_REHEARSAL_DSN   General-User Service D4 (clones per test)
#   willab_confident_moment_*   CONFIDENT_MOMENT_REHEARSAL_DSN    Confident Moment coaching bundle
#
# Nothing here touches a real environment: no network listener, no real
# credentials, the cluster lives under mktemp and is removed on exit.
#
#   scripts/rehearsal_tier.sh             build, run every suite, tear down
#   scripts/rehearsal_tier.sh --keep      leave the cluster up and print the DSNs
#   scripts/rehearsal_tier.sh --dry-run   print what would run, build nothing
#
# Exit 0: every rehearsal module ran and passed. Anything else: the tier did
# not run to green, and local_ci.sh treats that as RED when the tier is
# required.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 2

KEEP=0; DRY=0; BUILD_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --keep)       KEEP=1 ;;
    --dry-run)    DRY=1 ;;
    --build-only) BUILD_ONLY=1; KEEP=1 ;;
    -h|--help) sed -n '2,40p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

PY="${REHEARSAL_PYTHON:-$REPO/.venv-ci/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3)"
PG_BIN="${PG_BIN:-}"
if [ -z "$PG_BIN" ]; then
  for d in /usr/lib/postgresql/*/bin /opt/homebrew/opt/postgresql@16/bin /usr/local/pgsql/bin; do
    [ -x "$d/initdb" ] && PG_BIN="$d"
  done
fi
if [ -z "$PG_BIN" ] || [ ! -x "$PG_BIN/initdb" ]; then
  echo "rehearsal tier: no PostgreSQL server binaries found (initdb). Install postgresql-16 or set PG_BIN." >&2
  exit 2
fi
export PATH="$PG_BIN:$PATH"
PORT="${REHEARSAL_PGPORT:-55432}"

# PostgreSQL refuses to run as root; on a root shell delegate the server
# processes to the postgres system user (present wherever the server package
# is installed). Everything else runs as the caller.
# AS_PG and WALLCLOCK may be empty, so they expand as ${X[@]+"${X[@]}"}:
# macOS's /bin/bash is 3.2, where "${X[@]}" of an empty array under `set -u`
# is an "unbound variable" error and the tier died before initdb.
AS_PG=()
if [ "$(id -u)" = 0 ]; then
  id postgres >/dev/null 2>&1 || { echo "rehearsal tier: running as root and no 'postgres' user to delegate to" >&2; exit 2; }
  AS_PG=(runuser -u postgres --)
fi

MODULES=$(ls tests/test_*_postgres.py tests/test_confident_moment_production_fixtures.py | sort)
if [ "$DRY" = 1 ]; then
  echo "rehearsal tier would build a cluster with $PG_BIN and run:"
  for m in $MODULES; do echo "  $m"; done
  exit 0
fi

SOCK="$(mktemp -d /tmp/willab-rehearsal.XXXXXX)"   # fixtures require /tmp/willab-*
DATA="$SOCK/data"; LOG="$SOCK/postgres.log"
[ ${#AS_PG[@]} -gt 0 ] && chown postgres "$SOCK"

teardown() {
  if [ "$KEEP" = 1 ]; then
    echo "cluster kept at $SOCK (stop with: ${AS_PG[*]:+${AS_PG[*]} }$PG_BIN/pg_ctl -D $DATA stop)"
    return
  fi
  ${AS_PG[@]+"${AS_PG[@]}"} "$PG_BIN/pg_ctl" -D "$DATA" -m fast -w stop >/dev/null 2>&1 || true
  rm -rf "$SOCK"
}
trap teardown EXIT

echo "→ rehearsal tier: disposable cluster at $SOCK (port $PORT, socket only)"
${AS_PG[@]+"${AS_PG[@]}"} "$PG_BIN/initdb" -D "$DATA" -U postgres --auth=trust -E UTF8 --locale=C >"$SOCK/initdb.log" 2>&1 \
  || { echo "initdb failed:" >&2; tail -20 "$SOCK/initdb.log" >&2; exit 1; }
${AS_PG[@]+"${AS_PG[@]}"} "$PG_BIN/pg_ctl" -D "$DATA" -l "$LOG" -w \
  -o "-c listen_addresses='' -c unix_socket_directories=$SOCK -c port=$PORT -c fsync=off -c synchronous_commit=off -c full_page_writes=off" start >/dev/null 2>&1 \
  || { echo "postgres failed to start:" >&2; tail -20 "$LOG" >&2; exit 1; }

export PGHOST="$SOCK" PGPORT="$PORT" PGUSER=postgres
dsn() { echo "postgresql://postgres@/$1?host=$SOCK&port=$PORT"; }

# ── Lanes ─────────────────────────────────────────────────────────────────────
# Each suite was written against the migration chain AS IT STOOD at its own
# slice; later migrations install triggers its fixture helpers trip. So lanes
# are checkpoints of one chain, not clones of the final schema. Every recipe
# below was verified by execution on 2026-09-14 (docs/REHEARSAL-TIER.md).
PSQL=(psql -X -q -v ON_ERROR_STOP=1)
sql_file() {  # sql_file <db> <file>   (released files apply twice: idempotency)
  "${PSQL[@]}" -d "$1" -f "$2" >"$SOCK/apply.log" 2>&1 \
    || { echo "  FAILED applying $2 to $1:" >&2; grep -m3 ERROR "$SOCK/apply.log" >&2; exit 1; }
}
clone() { "${PSQL[@]}" -d postgres -c "CREATE DATABASE \"$1\" TEMPLATE \"$2\"" >/dev/null \
    || { echo "  clone $1 failed" >&2; exit 1; }; }

echo "→ building the MLC-3 chain (assignment prerequisites → 0313 → 0314 → 0317 → RPQ prerequisites → 0318–0321)"
CHAIN=willab_m33_chain
"${PSQL[@]}" -d postgres -c "CREATE DATABASE $CHAIN" >/dev/null
sql_file $CHAIN tests/integration/mlc3_assignment_prerequisites.sql
for m in add_mlc3_exercise_dark_foundation add_mlc3_dark_assignment_frames add_mlc3_n1_source_pattern_provenance; do
  sql_file $CHAIN migrations/$m.sql; sql_file $CHAIN migrations/$m.sql
done
sql_file $CHAIN tests/integration/rpq_restoration_prerequisites.sql
for m in add_feedback_v3_serving_restoration add_mlc3_practice_foundation_restoration \
         add_mlc3_fresh_offer_and_paired_review_restoration add_rooting_phrase_qualification_v1; do
  sql_file $CHAIN migrations/$m.sql; sql_file $CHAIN migrations/$m.sql
done
clone willab_m33_rehearsal $CHAIN                       # dark assignments, N1, RPQ
sql_file $CHAIN migrations/add_coach_guidance_delivery_d3.sql
sql_file $CHAIN migrations/add_coach_guidance_delivery_d3.sql
clone willab_d3_rehearsal $CHAIN                        # Coach Guidance D3
sql_file $CHAIN migrations/add_mlc3_first_client_service_d2.sql
sql_file $CHAIN migrations/add_mlc3_first_client_service_d2.sql
clone willab_service_rehearsal $CHAIN                   # First-Client Service D2

echo "→ building the Confident Moment lanes via tests/integration/confident_moment_rehearsal.sh"
# Two checkpoints are cut from the same builds (the recipe's
# CONFIDENT_MOMENT_CHECKPOINTS hook; docs/REHEARSAL-TIER-PENDING-LANE-RECIPES.md):
#   released, right after 0325 add_mlc3_founder_canary_security_closure.sql → canary
#   narrow,   right after 0326 add_mlc3_general_user_service_d4.sql         → D4 template
# Neither suite runs on the finished chain: from 0326 on the canary audit's
# required-RPC list names a function 0326 deliberately revoked (7/9 there), and
# D5/D4 helpers trip triggers installed after their own slice.
CKPT_narrow="add_mlc3_general_user_service_d4.sql=willab_confident_moment_narrow_0326"
CKPT_released="add_mlc3_founder_canary_security_closure.sql=willab_confident_moment_released_0325"
for lane in narrow released; do
  ck="CKPT_$lane"
  if ! CONFIDENT_MOMENT_PGHOST="$SOCK" CONFIDENT_MOMENT_PGPORT="$PORT" CONFIDENT_MOMENT_PGUSER=postgres \
       CONFIDENT_MOMENT_CHECKPOINTS="${!ck}" \
       bash tests/integration/confident_moment_rehearsal.sh "$lane" "willab_confident_moment_$lane" >"$SOCK/$lane.log" 2>&1; then
    echo "  $lane lane FAILED:" >&2; tail -20 "$SOCK/$lane.log" >&2; exit 1
  fi
  grep -E "^Built|^  checkpoint" "$SOCK/$lane.log" | sed 's/^/  /'
done

# canary: released @0325 with the two required purposes made operational.
# scripts/check_mlc3_founder_canary_readiness.py counts exactly
# personalized_exercise_recommendation and coach_review WHERE operational AND
# authorizes_processing; the recipe seeds all six purposes false, so the test
# that disables coach_review and expects 1 could never move off 0. CHECK
# processing_purpose_operational_invariant demands the five control columns
# whenever authorizes_processing is true, so the booleans alone are rejected.
clone willab_d3_canary willab_confident_moment_released_0325
"${PSQL[@]}" -d willab_d3_canary -c "UPDATE public.processing_purpose_registry
   SET operational = true, authorizes_processing = true,
       capability_version = 'rehearsal-capability-v1', reviewed_at = now(),
       retention_control_version = 'rehearsal-retention-v1',
       deletion_control_version = 'rehearsal-deletion-v1',
       rights_control_version = 'rehearsal-rights-v1'
 WHERE id IN ('personalized_exercise_recommendation', 'coach_review')" >"$SOCK/apply.log" 2>&1 \
  || { echo "  canary purpose seed failed:" >&2; grep -m3 ERROR "$SOCK/apply.log" >&2; exit 1; }

# D4: narrow @0326 as the TEMPLATE the suite clones per test, plus the two
# relaxations its fixture helpers need: a default on ml_judgments.id, and the
# MLC-2 / phase-1 append-only guards disabled. The suite asserts nothing about
# immutability (none of "append-only", "append_only", "immutable" occurs in
# it); those guards are exercised by the MLC-2 suites in their own lane, and
# tests/test_mlc3_first_client_service_postgres.py already relaxes them the
# same way in _age_authorization_checks. Disposable-only.
relax_append_only() {  # relax_append_only <db>
  "${PSQL[@]}" -d "$1" \
    -c "ALTER TABLE public.ml_judgments ALTER COLUMN id SET DEFAULT gen_random_uuid()" \
    -c "DO \$\$ DECLARE r record; BEGIN
          FOR r IN SELECT t.tgrelid::regclass AS rel, t.tgname
                     FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
                    WHERE NOT t.tgisinternal
                      AND p.proname IN ('reject_mlc2_immutable_mutation',
                                        'reject_phase1_immutable_mutation')
          LOOP EXECUTE format('ALTER TABLE %s DISABLE TRIGGER %I', r.rel, r.tgname); END LOOP;
        END \$\$" >"$SOCK/apply.log" 2>&1 \
    || { echo "  relaxations on $1 failed:" >&2; grep -m3 ERROR "$SOCK/apply.log" >&2; exit 1; }
}
clone willab_ga_template willab_confident_moment_narrow_0326
relax_append_only willab_ga_template

# freeze: the two functions that decide whether a speaker's judgement is
# ACCEPTED — claim_ideal_text_feedback_set_v1 (what was served) and
# record_take_feedback_response_v1 (was this item served). No lane installed
# either, so the tier ran green while testing none of the path the founder was
# blocked on, and three merges argued about it from reading alone. Its own
# chain, not a clone: these migrations predate the MLC-3 fork and the lanes
# above carry triggers they never expected.
echo "→ building the freeze/answer chain (prerequisites → 0308 → 0310 → 0333 → 0339 → 0346 → 0347 → 0349)"
FREEZE=willab_freeze_rehearsal
"${PSQL[@]}" -d postgres -c "CREATE DATABASE $FREEZE" >/dev/null
sql_file $FREEZE tests/integration/take_feedback_freeze_prerequisites.sql
for m in add_take_review_lifecycle add_feedback_manager_and_part_commits \
         add_atomic_take_feedback_response add_acknowledged_praise_response \
         answer_a_v3_item_against_the_freeze_that_served_it \
         the_frozen_set_records_the_policy_that_served \
         the_exposure_record_takes_the_v3_selection; do
  sql_file $FREEZE migrations/$m.sql; sql_file $FREEZE migrations/$m.sql
done

# bake: the stored bookmark set and the rule that decides whether it is still
# true. 0345 shipped that rule with no lane at all, and the two writers it
# forgot (both answer routes) went unnoticed until the founder's bookmarks
# came back after a reload on an item he had already judged. Its own chain
# from the core-snapshot prerequisites, because the bake binds to a published
# snapshot and to nothing else in the MLC-3 fork.
echo "→ building the bake chain (core-snapshot prerequisites → 0290 → bake prerequisites → 0345 → 0351)"
BAKE=willab_bake_rehearsal
"${PSQL[@]}" -d postgres -c "CREATE DATABASE $BAKE" >/dev/null
sql_file $BAKE tests/integration/ideal_text_core_snapshot_prerequisites.sql
sql_file $BAKE tests/integration/ideal_text_feedback_bake_prerequisites.sql
for m in add_ideal_text_core_snapshot fix_ideal_text_core_pgcrypto_search_path \
         add_ideal_text_feedback_bake \
         the_bake_knows_about_answers_and_its_own_start; do
  sql_file $BAKE migrations/$m.sql; sql_file $BAKE migrations/$m.sql
done

# model-gate: the table a promoted model name lands in, and the trigger that
# decides whether it may land at all. Its own two-file chain because
# `runtime_config` predates every fork above it (0051) and the guard needs
# nothing else — no fixture, no principal, no take. What it proves is the
# thing a Python test cannot: that the DATABASE refuses the write, which is
# the half of LEGACY-1 a psql session holding the service-role key can reach.
echo "→ building the model-gate chain (0051 → 0352)"
MODELGATE=willab_model_gate_rehearsal
"${PSQL[@]}" -d postgres -c "CREATE DATABASE $MODELGATE" >/dev/null
for role in anon authenticated service_role; do
  "${PSQL[@]}" -d "$MODELGATE" \
    -c "DO \$\$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='$role') THEN CREATE ROLE $role NOLOGIN; END IF; END \$\$" >/dev/null
done
for m in add_runtime_model_config guard_runtime_config_model_keys; do
  sql_file $MODELGATE migrations/$m.sql; sql_file $MODELGATE migrations/$m.sql
done

# lane name | DSN variable | database | modules
LANES=(
  "m33|MLC3_REHEARSAL_DSN|willab_m33_rehearsal|tests/test_mlc3_dark_assignments_postgres.py tests/test_mlc3_n1_source_pattern_postgres.py tests/test_rooting_phrase_qualification_postgres.py"
  "d3|COACH_GUIDANCE_REHEARSAL_DSN|willab_d3_rehearsal|tests/test_coach_guidance_delivery_d3_postgres.py"
  "service|MLC3_FIRST_CLIENT_REHEARSAL_DSN|willab_service_rehearsal|tests/test_mlc3_first_client_service_postgres.py"
  "confident-moment narrow|CONFIDENT_MOMENT_REHEARSAL_DSN|willab_confident_moment_narrow|tests/test_confident_moment_coaching_bundle_postgres.py"
  "confident-moment released|CONFIDENT_MOMENT_REHEARSAL_DSN|willab_confident_moment_released|tests/test_confident_moment_production_fixtures.py tests/test_d11_writer_markers_installed_postgres.py tests/test_phase1_deletion_completion_postgres.py tests/test_phase1_processing_postgres.py tests/test_mlc3_self_speaker_identity_postgres.py tests/test_optional_consent_postgres.py tests/test_reacceptance_signal_postgres.py tests/test_consent_choices_postgres.py tests/test_account_deletion_starts_postgres.py tests/test_practice_without_the_tick_postgres.py tests/test_bundled_era_erasure_postgres.py tests/test_project_deletion_postgres.py"
  "canary|MLC3_CANARY_READINESS_REHEARSAL_DSN|willab_d3_canary|tests/test_mlc3_founder_canary_readiness_postgres.py"
  "d4|MLC3_GENERAL_USER_REHEARSAL_DSN|willab_ga_template|tests/test_mlc3_general_user_service_d4_postgres.py"
  "freeze|TAKE_FEEDBACK_FREEZE_REHEARSAL_DSN|willab_freeze_rehearsal|tests/test_take_feedback_freeze_postgres.py"
  "bake|IDEAL_TEXT_FEEDBACK_BAKE_REHEARSAL_DSN|willab_bake_rehearsal|tests/test_ideal_text_feedback_bake_postgres.py"
  "model-gate|RUNTIME_MODEL_GATE_REHEARSAL_DSN|willab_model_gate_rehearsal|tests/test_runtime_config_model_guard_postgres.py"
)
# Suites with no GREEN recipe. Reported NOT RUN, never skipped, never run as
# "expected to fail"; see docs/REHEARSAL-TIER.md "Pending lanes".
PENDING=(
  "tests/test_mlc3_coach_inline_authoring_d5_postgres.py|D5: narrow @0324 + the D4 relaxations reaches 11/12; the last failure is an assertion, not a fixture gap (tests/test_mlc3_coach_inline_authoring_d5_postgres.py:782 — prepare_coach_inline_blind_batch_v1 returns 1 item, 2 expected), a question for D5's owner; recipe in docs/REHEARSAL-TIER-PENDING-LANE-RECIPES.md"
)

if [ "$KEEP" = 1 ]; then
  for lane in "${LANES[@]}"; do IFS='|' read -r _ var db _ <<<"$lane"; echo "export $var='$(dsn "$db")'"; done
fi

if [ "$BUILD_ONLY" = 1 ]; then
  echo "built only (--build-only); cluster kept at $SOCK"
  exit 0
fi

# ── Run the tier, one pytest invocation per lane (two lanes share a DSN name,
#    and each suite must see only its own database). ─────────────────────────
echo "→ running the rehearsal lanes"
# Every lane gets a wall clock. The suites race real connections, and a race
# test that deadlocks itself (seen once in three runs on 2026-09-14: the
# coaching-bundle suite's render/withdrawal ordering test, holding a render
# transaction open while joining the thread it blocks) otherwise stalls the
# tier — and the CI job — forever. The slowest lane runs ~40 s; 900 s is a
# hang, not a slow machine. Override with REHEARSAL_LANE_TIMEOUT=<seconds>.
LANE_TIMEOUT="${REHEARSAL_LANE_TIMEOUT:-900}"
if command -v timeout >/dev/null 2>&1; then WALLCLOCK=(timeout -k 15 "$LANE_TIMEOUT")
elif command -v gtimeout >/dev/null 2>&1; then WALLCLOCK=(gtimeout -k 15 "$LANE_TIMEOUT")   # macOS coreutils
else WALLCLOCK=(); echo "  (no timeout(1) on this machine — lanes run without a wall clock)"; fi
STATUS=0; SUMMARY=()
for lane in "${LANES[@]}"; do
  IFS='|' read -r name var db modules <<<"$lane"
  env WILLAB_REHEARSAL=1 JWT_SECRET=ci-placeholder-secret \
      SUPABASE_URL=https://ci-placeholder.invalid SUPABASE_KEY=ci-placeholder-key \
      "$var=$(dsn "$db")" \
      ${WALLCLOCK[@]+"${WALLCLOCK[@]}"} \
      "$PY" -m pytest $modules -p no:cacheprovider -q --tb=short >"$SOCK/lane.log" 2>&1
  rc=$?
  line="$(grep -E "passed|failed|error" "$SOCK/lane.log" | tail -1)"
  if [ "$rc" = 0 ]; then
    SUMMARY+=("  pass  $name: $line")
  elif [ "$rc" = 124 ] || [ "$rc" = 137 ]; then
    STATUS=1
    SUMMARY+=("  FAIL  $name: timed out after ${LANE_TIMEOUT}s — a hung test, not a slow one ($(tr -cd '.' <"$SOCK/lane.log" | wc -c) passed before the stall)")
  else
    STATUS=1
    SUMMARY+=("  FAIL  $name: $line")
    grep -E "^(FAILED|ERROR) " "$SOCK/lane.log" | head -20
    grep -E "^E  " "$SOCK/lane.log" | sort | uniq -c | sort -rn | head -5
  fi
done
echo "── rehearsal tier ─────────────────────────────────────────"
printf '%s\n' "${SUMMARY[@]}"
for p in "${PENDING[@]}"; do IFS='|' read -r mod why <<<"$p"; echo "  NOT RUN  $(basename "$mod"): $why"; done
if [ "$STATUS" = 0 ]; then echo "rehearsal tier: GREEN (verified lanes); ${#PENDING[@]} suites NOT RUN, listed above"
else echo "rehearsal tier: RED"; fi
exit "$STATUS"
