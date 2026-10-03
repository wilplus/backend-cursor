"""An expired permit handed back by a replayed key is minted again.

THE BUG (founder's Take of 2026-10-02, job 060abbc9…): the attempt died in
the database incident; the sweeper re-ran it the next morning; the permit
RPC, idempotent on its key, returned the permit the first run had minted 15
hours earlier, and ``record_provider_event('started')`` raised
PROVIDER_PERMIT_INVALID on every retry until the attempts ran out. The
record → process loop must survive a retry (LIVE LOOP).

Run: python3 -m unittest tests.test_provider_permit_reissue
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from services import processing_authorization as pa

PRINCIPAL = "11111111-1111-1111-1111-111111111111"


def _iso(delta_seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat()


class _Result:
    def __init__(self, data):
        self.data = data


class _Call:
    def __init__(self, client, name, params):
        self.client, self.name, self.params = client, name, params

    def execute(self):
        self.client.calls.append((self.name, dict(self.params)))
        if self.name != "issue_phase1_provider_permit_v1":
            return _Result([])
        key = self.params["p_idempotency_key"]
        if key in self.client.permits:
            return _Result([self.client.permits[key]])
        row = {"permit_id": f"permit-{len(self.client.permits) + 1}",
               "provider": self.params["p_provider"],
               "operation_kind": self.params["p_operation_kind"],
               "expires_at": _iso(900)}
        self.client.permits[key] = row
        return _Result([row])


class _Client:
    def __init__(self, permits=None):
        self.calls = []
        self.permits = dict(permits or {})

    def rpc(self, name, params):
        return _Call(self, name, params)


class _Db:
    def __init__(self, client):
        self.client = client


def _service(client):
    return pa.ProcessingAuthorizationService(_Db(client), mode="enforce")


def _issue(service, key):
    return service.issue_provider_permit(
        acquisition_principal_id=PRINCIPAL, take_id="take-1",
        recording_id="rec-1", provider="cloudflare_r2",
        operation_kind="audio_download",
        minimum_data_manifest={"content": ["immutable_audio_object"]},
        idempotency_key=key)


class ReissueTests(unittest.TestCase):
    def test_a_live_permit_is_returned_as_is(self):
        client = _Client()
        permit = _issue(_service(client), "audio-download:job:1:abc")
        self.assertEqual(permit["permit_id"], "permit-1")
        self.assertEqual(len(client.calls), 1)

    def test_an_expired_replay_is_minted_again_under_a_derived_key(self):
        stale = {"permit_id": "permit-old", "provider": "cloudflare_r2",
                 "operation_kind": "audio_download", "expires_at": _iso(-15 * 3600)}
        client = _Client(permits={"audio-download:job:1:abc": stale})
        permit = _issue(_service(client), "audio-download:job:1:abc")
        self.assertEqual(permit["permit_id"], "permit-2")
        self.assertEqual(len(client.calls), 2)
        second_key = client.calls[1][1]["p_idempotency_key"]
        self.assertTrue(second_key.startswith("audio-download:job:1:abc:reissue:"))
        # The original key keeps its record; the derived one is new.
        self.assertEqual(client.permits["audio-download:job:1:abc"], stale)

    def test_a_reissue_never_loops(self):
        # Even if the derived key somehow replays an expired permit, the
        # second mint is returned as is rather than minting a third.
        class _AlwaysStale(_Client):
            def rpc(self, name, params):
                call = _Call(self, name, params)
                if name == "issue_phase1_provider_permit_v1":
                    self.permits[params["p_idempotency_key"]] = {
                        "permit_id": "stale", "expires_at": _iso(-60)}
                return call
        client = _AlwaysStale()
        permit = _issue(_service(client), "k")
        self.assertEqual(permit["permit_id"], "stale")
        self.assertEqual(len(client.calls), 2)

    def test_an_unreadable_expiry_reads_as_live(self):
        self.assertFalse(pa._permit_expired({"expires_at": "soon"}))
        self.assertFalse(pa._permit_expired({}))
        self.assertTrue(pa._permit_expired({"expires_at": _iso(-1)}))
        self.assertFalse(pa._permit_expired({"expires_at": _iso(60)}))

    def test_the_gate_off_issues_nothing(self):
        client = _Client()
        service = pa.ProcessingAuthorizationService(_Db(client), mode="off")
        self.assertIsNone(_issue(service, "k"))
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
