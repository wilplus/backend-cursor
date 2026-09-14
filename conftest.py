"""Root pytest conftest — CI-parity env + the shared fake-DB fixtures.

Two jobs:

1. ENV PARITY. The same placeholder env CI exports (tests.yml) is defaulted
   here, so a bare local `pytest` behaves exactly like CI instead of
   mass-skipping every module whose import guard trips on missing config.
   setdefault only — a real local .env/exported value always wins.

2. FIXTURES. The pytest-style face of tests/fakes.py, for new (and migrated)
   tests. unittest-style tests can't take fixtures — they import
   tests.fakes directly instead.
"""
import os

# Must run before any test module imports app/config/services.db.
os.environ.setdefault("JWT_SECRET", "ci-placeholder-secret")
os.environ.setdefault("SUPABASE_URL", "https://ci-placeholder.invalid")
os.environ.setdefault("SUPABASE_KEY", "ci-placeholder-key")
# services.db constructs a REAL supabase client at import (singleton), and
# supabase-py 2.6.0 validates the key is JWT-shaped — an arbitrary string
# raises at create_client. This is the public supabase local-dev demo
# service_role token (same one tests.yml uses for the probe job); the URL
# above is .invalid, so it can never connect to anything. Without this
# default, a bare `import services.db` only works when an early-alphabet
# test module happens to have stubbed sys.modules["supabase"] first —
# import-order roulette this conftest exists to end.
os.environ.setdefault(
    "SUPABASE_SERVICE_ROLE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImV4cCI6"
    "MTk4MzgxMjk5Nn0.EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU",
)

import importlib

# Claim the real optional heavyweights BEFORE any test module imports.
# Several unittest modules pre-seed EMPTY sys.modules placeholders for these
# (guarded by "if not already in sys.modules") so they can run without the
# full requirements installed. If such a placeholder lands first — purely a
# function of alphabetical collection order — every later import silently
# gets the empty fake, and importing the real app explodes on
# sentry_sdk.integrations.flask. With the real package importable (every CI
# run, any venv with requirements), take the name first; in a genuinely
# deps-free environment the per-file placeholder guards take over as before.
for _mod in ("supabase", "sentry_sdk", "sentry_sdk.integrations.flask"):
    try:
        importlib.import_module(_mod)
    except Exception:
        pass

import pytest  # noqa: E402

from tests.fakes import FakeSupabaseClient, swap_attr  # noqa: E402

# ── The rehearsal tier (audit Q-T2, founder decision 2026-09-14) ─────────────
#
# The tests/*_postgres.py suites run only against a DISPOSABLE local
# PostgreSQL built by scripts/rehearsal_tier.sh. Each module gates itself on a
# *_REHEARSAL_DSN variable with a module-level `skipif(..., reason="disposable
# ... rehearsal only")`. Left alone, an ordinary `pytest` reports those ~260
# cases as SKIPPED, which reads as "ran, chose not to" when the truth is
# "never runnable here". So:
#
#   default run              the tier is DESELECTED (pytest's own word for
#                            "not run"), never skipped, and the terminal
#                            summary says so with the command that runs it;
#   WILLAB_REHEARSAL=1       the tier is selected; the runner script has
#                            already exported every DSN, so the per-module
#                            skipif is inert. A missing DSN under
#                            WILLAB_REHEARSAL=1 is an ERROR, not a skip —
#                            the tier claims to have run only when it did.
#
# Membership is derived from the module's own skipif reason rather than from
# the file name: tests/test_rooting_coverage_policy_postgres.py reads SQL text
# and needs no database, so it stays in the unit tier despite its name.
_REHEARSAL_REASON = ("disposable", "rehearsal")


def _rehearsal_gate(module) -> tuple[bool, str] | None:
    """(dsn_present, reason) if the module is a DSN-gated rehearsal suite."""
    marks = getattr(module, "pytestmark", None)
    if marks is None:
        return None
    for mark in marks if isinstance(marks, list) else [marks]:
        reason = str(mark.kwargs.get("reason", ""))
        if mark.name == "skipif" and any(w in reason.lower() for w in _REHEARSAL_REASON):
            condition = mark.args[0] if mark.args else mark.kwargs.get("condition", False)
            return (not bool(condition), reason)
    return None


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "rehearsal: DSN-gated PostgreSQL rehearsal suite; deselected unless "
        "WILLAB_REHEARSAL=1 (see scripts/rehearsal_tier.sh)",
    )


def pytest_collection_modifyitems(config, items):
    tier_on = os.environ.get("WILLAB_REHEARSAL") == "1"
    kept, deselected, modules, missing = [], [], set(), set()
    for item in items:
        gate = _rehearsal_gate(item.module)
        if gate is None:
            kept.append(item)
            continue
        item.add_marker(pytest.mark.rehearsal)
        modules.add(item.module.__name__)
        if not tier_on:
            deselected.append(item)
            continue
        dsn_present, reason = gate
        if not dsn_present:
            missing.add(item.module.__name__)
        kept.append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept
    config._willab_rehearsal = {
        "tier_on": tier_on, "modules": sorted(modules),
        "deselected": len(deselected), "missing": sorted(missing),
    }
    if missing:
        # The module-level skipif would turn these into 250 quiet skips and a
        # green exit — exactly the "ran, chose not to" reading the tier exists
        # to end. Refuse to start instead (pytest exit status 4).
        raise pytest.UsageError(
            "WILLAB_REHEARSAL=1 but the rehearsal DSN is unset for: "
            + ", ".join(sorted(missing))
            + " — scripts/rehearsal_tier.sh exports every *_REHEARSAL_DSN; "
            "do not set WILLAB_REHEARSAL by hand."
        )


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    info = getattr(config, "_willab_rehearsal", None)
    if not info or not info["modules"]:
        return
    tr = terminalreporter
    if not info["tier_on"]:
        tr.write_sep("-", "rehearsal tier")
        tr.write_line(
            f"NOT RUN: {info['deselected']} PostgreSQL rehearsal tests in "
            f"{len(info['modules'])} modules (deselected, not skipped). "
            f"Run them with scripts/rehearsal_tier.sh, or "
            f"scripts/local_ci.sh --with-rehearsal."
        )
    else:
        tr.write_sep("-", "rehearsal tier")
        tr.write_line(
            f"RAN: {len(info['modules'])} PostgreSQL rehearsal modules against the "
            f"disposable cluster (WILLAB_REHEARSAL=1)."
        )


@pytest.fixture(scope="session")
def repo_scan():
    """The one-walk-per-session repo scanner (tests/repo_scan.py) for
    pytest-style fence tests; unittest modules import it directly."""
    from tests import repo_scan as scan

    return scan


@pytest.fixture
def fake_supabase():
    """A fresh FakeSupabaseClient; seed tables via .seed(table, rows)."""
    client = FakeSupabaseClient()

    def seed(table, rows):
        client._table_rows[table] = rows
        client.tables.pop(table, None)  # re-materialize with new rows
        return client

    client.seed = seed
    return client


@pytest.fixture
def swap_db_client(fake_supabase):
    """services.db.db.client → a FakeSupabaseClient for this test.

    Yields the fake client; the real client is restored afterward even on
    failure. Everything that reads through db.client — routes included —
    sees the fake's tables.
    """
    from services.db import db

    with swap_attr(db, "client", fake_supabase):
        yield fake_supabase


@pytest.fixture
def app_client():
    """The REAL Flask app (every blueprint registered) as a test client.

    This is the integration seam: requests go through routing, decorators,
    error handlers, and CORS exactly as in prod. Combine with swap_db_client
    and stub_verified_user to keep the outside world out.
    """
    import app as app_module

    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


@pytest.fixture
def stub_verified_user():
    """Make Bearer tokens verify as a fixed user WITHOUT touching the
    require_auth decorator itself — only token verification is stubbed, so
    the real 401 paths, header parsing, and request.user_id wiring still
    execute.

    Usage: stub_verified_user("user-1") then send
    ``Authorization: Bearer anything``.
    """
    import auth

    stack = []

    def _stub(user_id="test-user", email="test@example.com", **claims):
        payload = {"sub": user_id, "email": email, **claims}
        cm = swap_attr(auth, "verify_supabase_token", lambda _t: dict(payload))
        cm.__enter__()
        stack.append(cm)
        return payload

    yield _stub
    while stack:
        stack.pop().__exit__(None, None, None)
