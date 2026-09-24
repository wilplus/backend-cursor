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
