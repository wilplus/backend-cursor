"""
STORY    As a speaker, I want my Ideal Text to open as fast on the first
         visit after a pause as on the one right after it, so that the loop
         never feels slower for having waited.
OUTCOME
  O1  The connection the backend holds to Supabase stays open for the
      configured keep-alive, not httpx's five seconds, so a request after a
      pause does not pay a new TCP + TLS handshake before its first read.
PROVES   O1 -> test_the_supabase_connection_outlives_a_pause_between_requests
WHY      Founder's stopwatch, 2026-10-20: the two reads that open the Ideal
         Text enrichment took 250 ms each while every read behind them took
         40-70 ms; the difference was the handshake.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

try:
    from services.db import DatabaseService, config
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    _IMPORT_ERROR = e

pytestmark = pytest.mark.skipif(_IMPORT_ERROR is not None,
                                reason=f"needs app deps: {_IMPORT_ERROR}")


def test_the_supabase_connection_outlives_a_pause_between_requests():
    with patch.object(config, "SUPABASE_URL", "https://example.supabase.co"), \
            patch.object(config, "SUPABASE_SERVICE_ROLE_KEY", "eyJ.eyJ.sig"), \
            patch.object(config, "SUPABASE_HTTP_KEEPALIVE_SECONDS", 300):
        client = DatabaseService._build_supabase_client(
            object.__new__(DatabaseService))
    session = client.postgrest.session
    pool = session._transport._pool
    assert pool._keepalive_expiry == 300.0
    # The session still carries what the request needs to reach Supabase.
    assert str(session.base_url).startswith("https://example.supabase.co/rest/v1")
    assert session.headers.get("apikey") == "eyJ.eyJ.sig"
    session.close()
