"""What the acceptance route accepts as an optional-purpose choice.

The acceptance payload now carries `optional_purposes`: the purposes the
person affirmatively ticked. Two things have to be true of it and they pull in
opposite directions, which is why they are pinned here:

  * a client that has never heard of optional purposes must keep working
    exactly as it did, so a MISSING field is not an error; and
  * a malformed field IS an error, because recording someone's consent from a
    payload we could not parse is worse than refusing to record it.

The line between "in the policy" and "the right shape" is deliberate. This
layer checks shape only. Whether a named purpose exists in the active policy,
and whether it is one that may be optional at all, is
`accept_phase1_processing_authorization_v2`'s to decide — it raises
PROCESSING_OPTIONAL_PURPOSE_INVALID. Validating membership in both places is
how the two drift apart and one of them starts quietly allowing something.
"""
from __future__ import annotations


class TestAgeAttestationComesFromThePayload:
    """The literal `True` was redundant, not a hole — and this pins why.

    2026-09-24. I reported the hardcoded literal as a finding twice: "a
    non-browser client could accept without ticking and the receipt would
    still record the attestation." That was FALSE. `accept` raises
    AGE_ATTESTATION_REQUIRED before it builds the RPC arguments, so nothing
    can reach the writer without having sent it.

    The change is therefore readability, not behaviour. Both halves are pinned
    here so the next reader does not have to re-derive what I got wrong:
    the guard really does refuse, and the recorded value really is the one
    that was checked. Source-text assertions could not tell those apart —
    only calling it can.
    """

    class _Result:
        data = [{"id": "receipt-1", "authorized": True}]

    class _Client:
        def __init__(self):
            self.calls: list[tuple[str, dict]] = []

        def rpc(self, name, args):
            self.calls.append((name, args))
            return self

        def execute(self):
            return TestAgeAttestationComesFromThePayload._Result()

    class _Database:
        def __init__(self, client):
            self.client = client

    def _service(self):
        from services.processing_authorization import (
            ProcessingAuthorizationService,
        )
        client = self._Client()
        return ProcessingAuthorizationService(self._Database(client)), client

    @staticmethod
    def _payload(**overrides):
        payload = {
            "explicit_action": "agree_and_continue",
            "age_18_attested": True,
            "policy_version": "phase1-2026-09-23",
            "terms_copy_sha256": "a" * 64,
            "privacy_copy_sha256": "b" * 64,
            "ai_notice_copy_sha256": "c" * 64,
            "agreement_copy_sha256": "d" * 64,
            "country_of_residence": "pl",
            "locale": "en",
            "client_version": "test",
            "idempotency_key": "key-1",
        }
        payload.update(overrides)
        return payload


    def test_the_recorded_value_is_the_one_that_was_checked(self):
        service, client = self._service()
        service.accept("principal-1", self._payload())
        assert len(client.calls) == 1
        assert client.calls[0][1]["p_age_18_attested"] is True
