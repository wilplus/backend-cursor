#!/usr/bin/env bash
#
# local_ci.sh — run the `checks` job from .github/workflows/tests.yml on this
# machine, with the SAME interpreter and the SAME pinned tools.
#
# WHY THIS EXISTS (founder 2026-08-11). This repo is private, so its Actions
# minutes come out of the account allowance, and the allowance ran out at
# ~15:30 UTC on 2026-08-11. Every run since then has failed at runner
# allocation: two red X's, zero billable ms, and no logs to download at all
# (HTTP 404 — the job never started, so there is nothing to log). Minutes
# reset with the billing month; until then the merge gate is simply absent.
#
# The founder's ruling was DO NOT UPGRADE — "I trust your local testing
# discipline... as long as your local gates (pytest, ruff, mypy) are green.
# Document the overrides in the squash commits." That trust is only worth
# what the local run actually is, and an ad-hoc `pytest && ruff && mypy`
# typed from memory is NOT the CI job:
#
#   · the system python here is 3.11, CI pins 3.12.1;
#   · a system mypy is whatever was installed last (1.19.1 on this box),
#     CI pins mypy==2.3.0 — different majors disagree about real code;
#   · the quarantine list is six --ignore flags long, and forgetting one
#     turns a green run into a red one for environmental reasons, which is
#     exactly the noise that teaches people to ignore the gate;
#   · `mypy .` against the system site-packages sees different stubs than
#     `mypy .` against requirements.txt.
#
# So this script does not approximate the job. It builds the job's
# environment (.venv-ci, python 3.12, pinned ruff/mypy, requirements.txt)
# and runs the job's steps in the job's order with the job's env vars.
# test_local_ci_mirror.py fails if this file and the workflow drift apart.
#
#   ./scripts/local_ci.sh                # the `checks` job
#   ./scripts/local_ci.sh --with-evals   # + the live-model probes (needs a key)
#   ./scripts/local_ci.sh --no-setup     # skip dependency install, reuse .venv-ci
#
# Exit 0 means every gate CI would have run passed here. Anything else and
# the branch is not mergeable — the quota outage is not a licence to merge
# red, it is a licence to merge on THIS evidence instead of GitHub's.

set -uo pipefail

# ── The CI pins. Keep these identical to .github/workflows/tests.yml ──────
# (test_local_ci_mirror.py is the thing that makes "keep identical" real.)
CI_PYTHON="3.12.1"
CI_RUFF="ruff==0.15.8"
CI_MYPY="mypy==2.3.0"

# QUARANTINE — integration-tier modules that need live Supabase / network.
# Byte-for-byte the workflow's --ignore list.
QUARANTINE=(
  test_admin_student_profile_regressions.py
  test_guest_funnel.py
  test_homework_regressions.py
  test_score_unification.py
  test_sentry.py
  test_auth_request.py
)

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO/.venv-ci"
PY="$VENV/bin/python"

WITH_EVALS=0
DO_SETUP=1
for arg in "$@"; do
  case "$arg" in
    --with-evals) WITH_EVALS=1 ;;
    --no-setup)   DO_SETUP=0 ;;
    -h|--help)    sed -n '2,40p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

cd "$REPO" || exit 1

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
dim()  { printf '\033[2m%s\033[0m\n' "$*"; }

# ── The environment ───────────────────────────────────────────────────────
if [ "$DO_SETUP" = 1 ]; then
  MINOR="${CI_PYTHON%.*}"                       # 3.12.1 → 3.12
  BASE="$(command -v "python$MINOR" || true)"
  if [ -z "$BASE" ]; then
    echo "python$MINOR not found — CI runs $CI_PYTHON and this gate is only"
    echo "meaningful on the same minor. Install it, then re-run." >&2
    exit 2
  fi
  if [ ! -x "$PY" ]; then
    bold "→ building .venv-ci on $("$BASE" --version)"
    if command -v uv >/dev/null 2>&1; then
      uv venv --python "$BASE" "$VENV" >/dev/null || exit 2
    else
      "$BASE" -m venv "$VENV" || exit 2
    fi
  fi
  bold "→ installing the CI pins"
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$PY" -q \
      -r requirements.txt pytest "$CI_RUFF" "$CI_MYPY" || exit 2
  else
    "$PY" -m pip install -q --upgrade pip || exit 2
    "$PY" -m pip install -q -r requirements.txt pytest "$CI_RUFF" "$CI_MYPY" || exit 2
  fi
fi

if [ ! -x "$PY" ]; then
  echo ".venv-ci missing — run without --no-setup once." >&2
  exit 2
fi

# The patch level is allowed to differ (a local 3.12.9 is a fair stand-in for
# CI's 3.12.1); the MINOR is not, because that is where syntax and stdlib
# behaviour actually move.
HAVE="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [ "$HAVE" != "${CI_PYTHON%.*}" ]; then
  echo "venv is python $HAVE, CI is ${CI_PYTHON%.*} — refusing to call this a mirror." >&2
  exit 2
fi

# ── The steps, in the job's order ─────────────────────────────────────────
# Migrations first, deliberately, and for the same reason CI does it: it is
# the cheapest gate and the only one whose failure means "this would have
# broken prod on the next container start" (MIGRATE_ON_BOOT=1 — merging a
# migration IS running it).
NAMES=(); RESULTS=(); FAILED=0

step() {                                        # step <name> <cmd...>
  local name="$1"; shift
  bold "→ $name"
  if "$@"; then
    NAMES+=("$name"); RESULTS+=("pass")
  else
    NAMES+=("$name"); RESULTS+=("FAIL"); FAILED=1
  fi
}

step "Verify migration manifest" "$PY" scripts/migrate.py verify --verbose
step "Migration runner unit tests" "$PY" -m unittest test_migrations -v
step "Ruff (lint)" "$VENV/bin/ruff" check .
step "Mypy (type-check)" "$VENV/bin/mypy" .

# Minimal placeholder env, same as the workflow: enough that import-time
# guards don't hard-crash, and useless for reaching anything real.
IGNORES=(); for m in "${QUARANTINE[@]}"; do IGNORES+=("--ignore=$m"); done
step "Run unit-tier tests" env \
  JWT_SECRET=ci-placeholder-secret \
  SUPABASE_URL=https://ci-placeholder.invalid \
  SUPABASE_KEY=ci-placeholder-key \
  "$PY" -m pytest "${IGNORES[@]}" -p no:cacheprovider -q

# ── The evals job (opt-in: live model calls, pennies per run) ─────────────
# CI skips these GREEN when the key is absent, so an unkeyed local run is
# not a failure — but it IS a gap, and the summary says so rather than
# letting a partial run read as a full one.
EVALS="skipped (--with-evals not passed)"
if [ "$WITH_EVALS" = 1 ]; then
  if [ -z "${OPENAI_API_KEY:-}" ]; then
    EVALS="SKIPPED — OPENAI_API_KEY not set"
  else
    EVALS="ran"
    export JWT_SECRET=ci-placeholder-secret
    export SUPABASE_URL=https://ci-placeholder.invalid
    export SUPABASE_KEY=ci-placeholder-key
    # A well-formed FAKE service-role JWT: supabase-py validates the shape at
    # client construction and raises on an arbitrary string. Same token the
    # workflow uses; it connects to nothing (the URL is invalid).
    export SUPABASE_SERVICE_ROLE_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0.EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU"
    step "Master-doc probe" "$PY" tests/evals/master_doc_probe.py
    step "Golden evals for changed prompts" "$PY" tests/evals/run_prompt_evals.py --all
  fi
fi

# ── The summary, written to be pasted ────────────────────────────────────
echo
bold "── local CI ──────────────────────────────────────────────"
for i in "${!NAMES[@]}"; do
  printf '  %-4s %s\n' "${RESULTS[$i]}" "${NAMES[$i]}"
done
dim "  evals: $EVALS"
echo

if [ "$FAILED" != 0 ]; then
  bold "RED — do not merge."
  exit 1
fi

SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
bold "GREEN — every gate the \`checks\` job runs passed here."
echo
dim "For the squash commit (the founder's documented-override rule):"
cat <<EOF

  CI override: GitHub Actions minutes exhausted for the month; the two
  jobs fail at runner allocation (no logs, zero billable ms), not on this
  code. Verified locally at $SHA via scripts/local_ci.sh on python
  ${CI_PYTHON%.*} with the pinned $CI_RUFF / $CI_MYPY: migrations, migration
  runner, ruff, mypy and the unit tier all green. Evals: $EVALS.
EOF
