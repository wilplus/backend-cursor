#!/bin/sh
# Railway migration entrypoint — run pending migrations, then exit.
#
# HOW TO USE IT
#   As a Railway pre-deploy command on the web service:
#       sh bin/railway-migrate.sh
#   Railway runs a pre-deploy command to completion before routing traffic to
#   the new deployment, which is exactly the semantics migrations want: the
#   schema lands before the code that needs it, and a non-zero exit stops the
#   deploy instead of shipping a backend into a database it can't talk to.
#
#   Also fine as a one-off ("Run command" in the Railway shell) when applying
#   a migration outside a deploy.
#
# WHY IT IS NOT WIRED INTO bin/railway-web.sh BY DEFAULT
#   CLAUDE.md: "Never break the live loop." A migration step on the gunicorn
#   boot path can crash-loop the whole record -> transcribe -> coach -> read
#   loop over a bad ALTER. Separating them means the worst case is "the schema
#   change didn't land", not "the app is down". bin/railway-web.sh has an
#   opt-in hook (MIGRATE_ON_BOOT=1) that can never fail the boot, for
#   environments where a pre-deploy command isn't available.
#
# EXIT CODES (from scripts/migrate.py)
#   0  applied, or nothing pending
#   1  a migration failed, or one was refused (destructive without an
#      explicit flag) -> the deploy should stop
#   2  cannot run here: no DATABASE_URL, or psycopg2 missing
#
#   Code 2 is treated as SUCCESS below unless MIGRATE_REQUIRED=1. Not every
#   service in this project has a Postgres URL (see docs/RLS-AUDIT.md: the
#   founder's own environment has no DATABASE_URL), and those services must
#   still deploy. Set MIGRATE_REQUIRED=1 on the service that owns migrations
#   to turn a missing database into a hard failure there.

set -e

cd "$(dirname "$0")/.."

echo "[migrate] $(date -u '+%Y-%m-%dT%H:%M:%SZ') starting"

# Structural check first. It needs no database, so a malformed manifest fails
# fast and loudly rather than midway through applying files.
if ! python3 scripts/migrate.py verify; then
  echo "[migrate] manifest verification FAILED — not applying anything."
  exit 1
fi

MIGRATION_ACTOR="${MIGRATION_ACTOR:-railway-deploy}"
export MIGRATION_ACTOR

set +e
python3 scripts/migrate.py apply
STATUS=$?
set -e

case "$STATUS" in
  0)
    echo "[migrate] done."
    ;;
  2)
    if [ "$MIGRATE_REQUIRED" = "1" ]; then
      echo "[migrate] no database reachable and MIGRATE_REQUIRED=1 — failing the deploy."
      exit 1
    fi
    echo "[migrate] no database reachable — skipping (set MIGRATE_REQUIRED=1 to make this fatal)."
    STATUS=0
    ;;
  *)
    echo "[migrate] FAILED with exit $STATUS."
    echo "[migrate] Run 'python3 scripts/migrate.py status' to see where it stopped."
    ;;
esac

exit "$STATUS"
