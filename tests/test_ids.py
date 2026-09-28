"""One rule for ids in requests (audit D1, founder decision 2026-09-26):
the standard 8-4-4-4-12 hex form, any letter case, handed back lowercase."""
from __future__ import annotations

import uuid

import pytest

from utils.ids import is_uuid, parse_uuid

CANON = "abcdefab-cdef-abcd-efab-cdefabcdefab"


@pytest.mark.parametrize("raw", [CANON, CANON.upper(), f"  {CANON}  ",
                                 "AbCdEfAb-CdEf-AbCd-EfAb-CdEfAbCdEfAb"])
def test_any_letter_case_is_accepted_and_returned_lowercase(raw):
    assert parse_uuid(raw, "id") == CANON
    assert is_uuid(raw)


def test_a_uuid_object_is_accepted():
    value = uuid.UUID(CANON)
    assert parse_uuid(value, "id") == CANON


@pytest.mark.parametrize("raw", [
    None, "", 1, True, [CANON], {"id": CANON},
    "{" + CANON + "}", "urn:uuid:" + CANON, CANON.replace("-", ""),
    CANON[:-1], CANON + "0", "not-a-uuid",
])
def test_anything_else_is_refused_with_the_field_name(raw):
    with pytest.raises(ValueError, match="^owner_id must be a UUID$"):
        parse_uuid(raw, "owner_id")
    assert not is_uuid(raw)


def test_the_seven_old_helpers_now_share_the_one_rule():
    from routes import recordings
    from routes.v2 import (
        coach_guidance_delivery, common, confident_moment_bundles,
        mlc3_first_client_coach, mlc3_first_client_service,
    )
    from services import mlc2_confidence

    for module in (coach_guidance_delivery, confident_moment_bundles,
                   mlc3_first_client_coach, mlc3_first_client_service):
        assert module._uuid is parse_uuid, module.__name__
    assert common._is_valid_uuid is is_uuid
    assert recordings._is_valid_uuid is is_uuid
    assert mlc2_confidence._uuid(CANON.upper(), "id") == CANON
    with pytest.raises(mlc2_confidence.Mlc2ContractError):
        mlc2_confidence._uuid("nope", "id")
