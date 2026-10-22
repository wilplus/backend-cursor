"""
GUARD      The database transport is a pool of HTTP/1 connections, kept warm
           once per gunicorn thread, so the app opens fast.
CATCHES    A supabase/httpx upgrade, a config edit or a session rebuilt in
           services/db.py that brings back the one shared HTTP/2 socket,
           shrinks the pool, or pings slower than the pool drops idle
           connections.
IF REMOVED Boot requests queue behind the slowest one again (founder
           2026-10-16: fast calls took 4.00 s on the socket, 0.07 s on the
           pool) and nobody notices until speakers do.
PROVES     test_every_postgrest_session_is_a_pool_of_http1_connections
             reads private httpx pool attributes ON PURPOSE as an upgrade
             tripwire; expect it to break on a library upgrade. Built with
             both key types: supabase-py 2.6.0 refused a new secret key
             (sb_secret_…) at create_client, so the leaked legacy key could
             not be replaced (Railway incident, 2026-10-22)
           test_a_service_key_is_sent_the_way_supabase_accepts_it
             the hand-built calls (auth admin, storage, realtime, RPC): a
             legacy JWT also goes as the Bearer token, a secret key never
           test_the_keep_warm_ping_comes_before_the_pool_drops_an_idle_connection
             a constant comparison (ping interval < keepalive expiry)
           test_the_keep_warm_ping_warms_one_connection_per_lane
             one ping per gunicorn thread, sent in parallel
"""
import pytest

from services import db_transport

LEGACY_KEY = "eyJ.eyJ.sig"
# A made-up key in the new format, built at runtime so GitHub push protection
# does not read it as a leaked Supabase secret.
SECRET_KEY = "sb_" + "secret_" + "x" * 31


@pytest.mark.parametrize("key", [LEGACY_KEY, SECRET_KEY])
def test_every_postgrest_session_is_a_pool_of_http1_connections(key):
    """Built the way the app builds it (services.db), so a session swap there
    is caught too: 2026-10-20 one rebuilt it as the shared HTTP/2 socket."""
    from unittest.mock import patch
    from services.db import DatabaseService, config
    with patch.object(config, "SUPABASE_URL", "https://example.supabase.co"), \
            patch.object(config, "SUPABASE_SERVICE_ROLE_KEY", key):
        client = DatabaseService._build_supabase_client(
            object.__new__(DatabaseService))
    for session in (client.postgrest.session, client.schema("public").session):
        pool = session._transport._pool
        assert pool._http2 is False
        assert pool._max_connections == db_transport.POOL_SIZE >= 8
        assert pool._keepalive_expiry == db_transport.KEEPALIVE_S
        # It still carries what a request needs to reach Supabase.
        assert str(session.base_url).startswith("https://example.supabase.co/rest/v1")
        assert session.headers.get("apikey") == key


def test_a_service_key_is_sent_the_way_supabase_accepts_it():
    from services.secrets import supabase_key_headers
    assert supabase_key_headers(LEGACY_KEY) == {
        "apikey": LEGACY_KEY, "Authorization": f"Bearer {LEGACY_KEY}"}
    assert supabase_key_headers(SECRET_KEY) == {"apikey": SECRET_KEY}


def test_the_keep_warm_ping_comes_before_the_pool_drops_an_idle_connection():
    """Founder 2026-10-18: a ping slower than the pool's own cut-off keeps
    nothing warm; the first request after a quiet spell reconnects anyway."""
    from services import warm_connections
    assert 0 < warm_connections.PING_EVERY_S < db_transport.KEEPALIVE_S


def test_the_keep_warm_ping_warms_one_connection_per_lane(monkeypatch):
    """The app opens with several requests at once; one warm connection
    serves one of them, so the ping reads once per gunicorn thread, together."""
    import threading
    from services import warm_connections
    monkeypatch.setenv("GUNICORN_THREADS", "3")
    # Every ping waits for the other two: pings sent one after another would
    # never all arrive, and the barrier would break instead.
    together = threading.Barrier(3, timeout=5)
    seen: list = []

    def ping():
        together.wait()
        seen.append(True)

    monkeypatch.setattr(warm_connections, "_ping_once", ping)
    warm_connections._ping_every_lane()
    assert len(seen) == 3 and not together.broken
