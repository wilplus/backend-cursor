"""
GUARD    The test suite refuses to start against a real Supabase project.
CATCHES
  C1  a `pytest` run in an environment that carries a production SUPABASE_URL
      (founder 2026-10-20: fixture values "arc-9", "owner-1" reached the live
      database this way) -- it stops before any test module imports.
  C2  the deliberate way through: WILLAB_TESTS_REAL_DB=1 lets a run against a
      disposable project proceed.
IF REMOVED  the next session that runs pytest plainly with production keys in
      its environment reads from, and can write to, production.
PROVES   C1, C2 -> test_a_real_supabase_url_stops_the_suite_unless_asked_for
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# Collection only: enough to run conftest.py, nothing else.
COLLECT = [sys.executable, "-m", "pytest", "--collect-only", "-q",
           "-p", "no:cacheprovider", "tests/test_db_transport_pool.py"]


def _collect(**extra: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if k not in ("SUPABASE_URL", "WILLAB_TESTS_REAL_DB")}
    env.update(extra, PYTHON_DOTENV_DISABLED="1")
    return subprocess.run(COLLECT, cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=120)


def test_a_real_supabase_url_stops_the_suite_unless_asked_for():
    real = "https://example-project.supabase.co"

    refused = _collect(SUPABASE_URL=real)
    assert refused.returncode != 0
    assert "refuses to run" in refused.stdout + refused.stderr

    allowed = _collect(SUPABASE_URL=real, WILLAB_TESTS_REAL_DB="1")
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr

    plain = _collect()  # no URL at all: the placeholder, as CI runs it
    assert plain.returncode == 0, plain.stdout + plain.stderr
