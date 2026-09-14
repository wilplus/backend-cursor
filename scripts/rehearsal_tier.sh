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
AS_PG=()
if [ "$(id -u)" = 0 ]; then
  id postgres >/dev/null 2>&1 || { echo "rehearsal tier: running as root and no 'postgres' user to delegate to" >&2; exit 2; }
  AS_PG=(runuser -u postgres --)
fi

MODULES=$(ls tests/test_*_postgres.py | sort)
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
    echo "cluster kept at $SOCK (stop with: ${AS_PG[*]} $PG_BIN/pg_ctl -D $DATA stop)"
    return
  fi
  "${AS_PG[@]}" "$PG_BIN/pg_ctl" -D "$DATA" -m fast -w stop >/dev/null 2>&1 || true
  rm -rf "$SOCK"
}
trap teardown EXIT

echo "→ rehearsal tier: disposable cluster at $SOCK (port $PORT, socket only)"
"${AS_PG[@]}" "$PG_BIN/initdb" -D "$DATA" -U postgres --auth=trust -E UTF8 --locale=C >"$SOCK/initdb.log" 2>&1 \
  || { echo "initdb failed:" >&2; tail -20 "$SOCK/initdb.log" >&2; exit 1; }
"${AS_PG[@]}" "$PG_BIN/pg_ctl" -D "$DATA" -l "$LOG" -w \
  -o "-c listen_addresses='' -c unix_socket_directories=$SOCK -c port=$PORT -c fsync=off -c synchronous_commit=off -c full_page_writes=off" start >/dev/null 2>&1 \
  || { echo "postgres failed to start:" >&2; tail -20 "$LOG" >&2; exit 1; }

export PGHOST="$SOCK" PGPORT="$PORT" PGUSER=postgres
dsn() { echo "postgresql://postgres@/$1?host=$SOCK&port=$PORT"; }

# ── The template: the checked-in Confident Moment narrow-lane recipe ─────────
TEMPLATE="willab_confident_moment_narrow"
echo "→ building template $TEMPLATE via tests/integration/confident_moment_rehearsal.sh narrow"
if ! CONFIDENT_MOMENT_PGHOST="$SOCK" CONFIDENT_MOMENT_PGPORT="$PORT" CONFIDENT_MOMENT_PGUSER=postgres \
     bash tests/integration/confident_moment_rehearsal.sh narrow "$TEMPLATE" >"$SOCK/template.log" 2>&1; then
  echo "template build FAILED:" >&2; tail -30 "$SOCK/template.log" >&2; exit 1
fi
grep -E "^Built|FAILED" "$SOCK/template.log" | sed 's/^/  /'

# ── One clone per lane prefix. The D4 suite clones its own template per test. ─
clone() {  # clone <name>
  psql -X -q -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$1\" TEMPLATE \"$TEMPLATE\"" >/dev/null \
    || { echo "clone $1 failed" >&2; exit 1; }
}
for db in willab_m33_rehearsal willab_service_rehearsal willab_d3_rehearsal willab_d3_canary willab_ga_template; do
  clone "$db"
done

export MLC3_REHEARSAL_DSN="$(dsn willab_m33_rehearsal)"
export MLC3_FIRST_CLIENT_REHEARSAL_DSN="$(dsn willab_service_rehearsal)"
export COACH_GUIDANCE_REHEARSAL_DSN="$(dsn willab_d3_rehearsal)"
export MLC3_CANARY_READINESS_REHEARSAL_DSN="$(dsn willab_d3_canary)"
export MLC3_GENERAL_USER_REHEARSAL_DSN="$(dsn willab_ga_template)"
export CONFIDENT_MOMENT_REHEARSAL_DSN="$(dsn "$TEMPLATE")"

if [ "$KEEP" = 1 ]; then
  for v in MLC3_REHEARSAL_DSN MLC3_FIRST_CLIENT_REHEARSAL_DSN COACH_GUIDANCE_REHEARSAL_DSN \
           MLC3_CANARY_READINESS_REHEARSAL_DSN MLC3_GENERAL_USER_REHEARSAL_DSN CONFIDENT_MOMENT_REHEARSAL_DSN; do
    echo "export $v='${!v}'"
  done
fi

if [ "$BUILD_ONLY" = 1 ]; then
  echo "built only (--build-only); cluster kept at $SOCK"
  exit 0
fi

# ── Run the tier. The CI placeholder env keeps import-time guards quiet. ──────
echo "→ running the rehearsal suites"
WILLAB_REHEARSAL=1 \
JWT_SECRET=ci-placeholder-secret \
SUPABASE_URL=https://ci-placeholder.invalid \
SUPABASE_KEY=ci-placeholder-key \
"$PY" -m pytest -m rehearsal $MODULES -p no:cacheprovider -q --tb=short "${REHEARSAL_PYTEST_ARGS[@]:-}"
STATUS=$?
if [ "$STATUS" = 0 ]; then
  echo "rehearsal tier: GREEN"
else
  echo "rehearsal tier: RED (pytest exit $STATUS)"
fi
exit "$STATUS"
