"""
STORY    As a speaker whose Take is retried later, I want an expired permit
         replaced, so that a retry the next morning still processes my Take.
OUTCOME
  O1  An expired permit handed back for a repeated request is issued again
      under a new key derived from the old one, and the original record is
      kept.
PROVES   O1 -> ReissueTests::test_an_expired_replay_is_minted_again_under_a_derived_key
WHY      Founder's Take of 2026-10-02 failed every retry on a 15-hour-old permit.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

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


if __name__ == "__main__":
    unittest.main()
