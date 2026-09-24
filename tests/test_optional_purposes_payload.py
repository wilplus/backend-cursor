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

import pathlib
import re

import pytest

from services.processing_authorization import (
    ProcessingAuthorizationError,
    _optional_purposes,
)

SERVICE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "services" / "processing_authorization.py"
)


class TestAbsenceIsNotRefusal:

    def test_a_missing_field_is_an_empty_choice(self):
        """An older client sends no field at all. It must still be able to
        accept the policy — it simply chooses nothing optional."""
        assert _optional_purposes({}) == []

    def test_an_explicit_empty_list_is_the_same(self):
        assert _optional_purposes({"optional_purposes": []}) == []

    def test_a_non_dict_payload_is_an_empty_choice(self):
        assert _optional_purposes(None) == []
        assert _optional_purposes("nonsense") == []


class TestAMalformedChoiceIsRefused:
    """Consent recorded from a payload we could not read is not consent."""

    @pytest.mark.parametrize("bad", [
        "personalized_exercise_recommendation",   # a bare string, not a list
        17,
        {"personalized_exercise_recommendation": True},
        True,
    ])
    def test_the_field_must_be_a_list(self, bad):
        with pytest.raises(ProcessingAuthorizationError) as caught:
            _optional_purposes({"optional_purposes": bad})
        assert caught.value.code == "OPTIONAL_PURPOSES_INVALID"
        assert caught.value.status == 422

    @pytest.mark.parametrize("bad", [
        ["ok", 3],
        ["ok", None],
        [""],
        ["   "],
        [["nested"]],
    ])
    def test_every_entry_must_be_a_non_empty_string(self, bad):
        with pytest.raises(ProcessingAuthorizationError) as caught:
            _optional_purposes({"optional_purposes": bad})
        assert caught.value.code == "OPTIONAL_PURPOSES_INVALID"


class TestWhatItPassesThrough:

    def test_entries_are_trimmed(self):
        got = _optional_purposes({"optional_purposes": [
            "  personalized_exercise_recommendation  ",
            "individual_learning_profile",
        ]})
        assert got == [
            "personalized_exercise_recommendation",
            "individual_learning_profile",
        ]

    def test_order_and_duplicates_are_left_to_the_rpc(self):
        """Not deduplicated here on purpose: the RPC canonicalises (btrim,
        DISTINCT, ORDER BY) and that canonical form is what the evidence hash
        is computed over. Doing it twice, differently, is how a receipt ends
        up hashing something other than what it stored."""
        got = _optional_purposes({"optional_purposes": ["b", "a", "b"]})
        assert got == ["b", "a", "b"]

    def test_an_unknown_purpose_passes_shape_and_fails_at_the_rpc(self):
        """Shape is all this layer judges. `not_a_real_purpose` is well-formed
        and must reach the RPC, which refuses it against the live policy."""
        assert _optional_purposes(
            {"optional_purposes": ["not_a_real_purpose"]}
        ) == ["not_a_real_purpose"]


class TestTheAcceptanceWriterIsV2:
    """v1 writes receipt rows only WHERE required_for_core_service, so under
    v1 an optional purpose can never reach a receipt at all. Reverting this
    call would not fail loudly — every acceptance would keep succeeding and
    every optional yes would be silently dropped."""

    def test_the_service_calls_v2(self):
        source = SERVICE.read_text(encoding="utf-8")
        assert 'rpc(\n                "accept_phase1_processing_authorization_v2"' in source \
            or "accept_phase1_processing_authorization_v2" in source

    def test_it_no_longer_calls_v1(self):
        source = SERVICE.read_text(encoding="utf-8")
        calls = re.findall(r'"(accept_phase1_processing_authorization_v\d)"', source)
        assert calls, "the acceptance RPC call vanished"
        assert "accept_phase1_processing_authorization_v1" not in calls, (
            "the service is writing acceptances through v1 again; optional "
            "purposes would be accepted by the screen and dropped by the "
            "writer, with no error anywhere"
        )

    def test_the_array_is_passed(self):
        source = SERVICE.read_text(encoding="utf-8")
        assert '"p_optional_purposes"' in source, (
            "the v2 argument is not being passed, so the default empty array "
            "applies and every optional yes is lost"
        )


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

    @pytest.mark.parametrize("attested", [None, False, "true", 1])
    def test_it_refuses_an_acceptance_that_never_attested(self, attested):
        service, client = self._service()
        payload = self._payload()
        if attested is None:
            payload.pop("age_18_attested")
        else:
            payload["age_18_attested"] = attested
        with pytest.raises(ProcessingAuthorizationError) as caught:
            service.accept("principal-1", payload)
        assert caught.value.code == "AGE_ATTESTATION_REQUIRED"
        assert client.calls == [], (
            "the writer must not be reached at all — a receipt asserting an "
            "attestation nobody made is exactly what this guard prevents"
        )

    def test_the_recorded_value_is_the_one_that_was_checked(self):
        service, client = self._service()
        service.accept("principal-1", self._payload())
        assert len(client.calls) == 1
        assert client.calls[0][1]["p_age_18_attested"] is True
