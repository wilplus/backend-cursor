"""
GUARD      The database transport is a pool of HTTP/1 connections, kept warm
           once per gunicorn thread, so the app opens fast.
CATCHES    A supabase/httpx upgrade or a config edit that brings back the one
           shared HTTP/2 socket, shrinks the pool, or pings slower than the
           pool drops idle connections.
IF REMOVED Boot requests queue behind the slowest one again (founder
           2026-10-16: fast calls took 4.00 s on the socket, 0.07 s on the
           pool) and nobody notices until speakers do.
PROVES     test_every_postgrest_session_is_a_pool_of_http1_connections
             reads private httpx pool attributes ON PURPOSE as an upgrade
             tripwire; expect it to break on a library upgrade
           test_the_keep_warm_ping_comes_before_the_pool_drops_an_idle_connection
             a constant comparison (ping interval < keepalive expiry)
           test_the_keep_warm_ping_warms_one_connection_per_lane
             one ping per gunicorn thread, sent in parallel
"""
from services import db_transport


def test_every_postgrest_session_is_a_pool_of_http1_connections():
    from supabase import create_client
    db_transport.install()
    client = create_client("https://example.supabase.co", "eyJ.eyJ.sig")
    for session in (client.postgrest.session, client.schema("public").session):
        pool = session._transport._pool
        assert pool._http2 is False
        assert pool._max_connections == db_transport.POOL_SIZE >= 8
        assert pool._keepalive_expiry == db_transport.KEEPALIVE_S


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
