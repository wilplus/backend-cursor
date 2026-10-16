"""The database transport is a connection pool, not one shared socket.

Founder 2026-10-16: fourteen boot requests arriving together all took the
time of the slowest one, because every thread multiplexed on one HTTP/2
socket. A local load test (one 4 s call + seven 50 ms calls on 8 threads)
showed the fast calls taking 4.00 s on that socket and 0.07 s on the pool.
This pins the pool so a library upgrade cannot quietly bring the socket back.
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
