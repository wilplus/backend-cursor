import copy
import uuid

import pytest

from services.mlc2_confidence_blind import (
    RATING_CHOICES,
    validate_blind_packet,
)
from services.mlc2_foundation import Mlc2ContractError


def _packet() -> dict:
    return {
        "packet_version": "confidence-blind-packet-v1",
        "clip": {
            "clip_id": str(uuid.uuid4()),
            "audio_object_id": str(uuid.uuid4()),
            "audio_sha256": "a" * 64,
            "start_ms": 120,
            "end_ms": 980,
        },
        "taxonomy": {
            "version": "confidence-five-state-v1",
            "choices": list(RATING_CHOICES),
        },
    }


def test_blind_packet_accepts_only_audio_coordinates_and_taxonomy():
    packet = _packet()
    validated = validate_blind_packet(packet)
    assert validated == packet
    packet["clip"]["start_ms"] = 999
    assert validated["clip"]["start_ms"] == 120


@pytest.mark.parametrize("field", [
    "transcript", "score", "rank", "model", "prediction", "judgment",
])
def test_blind_packet_rejects_answer_or_selection_hints(field):
    packet = _packet()
    packet[field] = "leak"
    with pytest.raises(Mlc2ContractError, match="allowlist"):
        validate_blind_packet(packet)


def test_blind_packet_rejects_taxonomy_drift_and_bad_coordinates():
    packet = _packet()
    packet["taxonomy"]["choices"] = ["yes", "no"]
    with pytest.raises(Mlc2ContractError, match="five-state"):
        validate_blind_packet(packet)
    packet = copy.deepcopy(_packet())
    packet["clip"]["end_ms"] = packet["clip"]["start_ms"]
    with pytest.raises(Mlc2ContractError, match="coordinates"):
        validate_blind_packet(packet)
