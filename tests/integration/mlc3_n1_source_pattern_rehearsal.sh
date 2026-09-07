#!/usr/bin/env bash
# Disposable local PostgreSQL only. N1 is assigned as migration 0317 locally.
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${MLC3_REHEARSAL_DSN:?Supply a new empty local willab_m33_* fixture database}"
n1_python="${PRACTICE_TEST_PYTHON:-.venv-ci/bin/python}"
n1_psql="${PRACTICE_TEST_PSQL:-psql}"

"$n1_psql" "$MLC3_REHEARSAL_DSN" -X -v ON_ERROR_STOP=1 -q \
  -f tests/integration/mlc3_assignment_prerequisites.sql
"$n1_psql" "$MLC3_REHEARSAL_DSN" -X -v ON_ERROR_STOP=1 -q \
  -f migrations/add_mlc3_exercise_dark_foundation.sql
"$n1_psql" "$MLC3_REHEARSAL_DSN" -X -v ON_ERROR_STOP=1 -q \
  -f migrations/add_mlc3_dark_assignment_frames.sql
"$n1_psql" "$MLC3_REHEARSAL_DSN" -X -v ON_ERROR_STOP=1 -q \
  -f migrations/add_mlc3_dark_assignment_frames.sql
for n1_apply in 1 2; do
  "$n1_psql" "$MLC3_REHEARSAL_DSN" -X -v ON_ERROR_STOP=1 -q \
    -f migrations/add_mlc3_n1_source_pattern_provenance.sql
done

JWT_SECRET=ci-placeholder-secret \
SUPABASE_URL=https://ci-placeholder.invalid \
SUPABASE_KEY=ci-placeholder-key \
"$n1_python" -m pytest -q \
  tests/test_mlc3_n1_source_pattern_postgres.py --tb=short
