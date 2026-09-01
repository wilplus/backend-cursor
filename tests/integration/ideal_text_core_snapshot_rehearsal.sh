#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${IDEAL_CORE_REHEARSAL_DSN:?Supply a new empty local database DSN}"
ideal_psql="${IDEAL_CORE_TEST_PSQL:-psql}"
"$ideal_psql" "$IDEAL_CORE_REHEARSAL_DSN" -X -v ON_ERROR_STOP=1 -q \
  -f tests/integration/ideal_text_core_snapshot_prerequisites.sql
for apply in 1 2; do
  "$ideal_psql" "$IDEAL_CORE_REHEARSAL_DSN" -X -v ON_ERROR_STOP=1 -q \
    -f migrations/add_ideal_text_core_snapshot.sql
  "$ideal_psql" "$IDEAL_CORE_REHEARSAL_DSN" -X -v ON_ERROR_STOP=1 -q \
    -f migrations/fix_ideal_text_core_pgcrypto_search_path.sql
done
"$ideal_psql" "$IDEAL_CORE_REHEARSAL_DSN" -X -v ON_ERROR_STOP=1 -q \
  -f tests/integration/ideal_text_core_snapshot_rehearsal.sql
