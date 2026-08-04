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
