"""
STORY    As a coach, I want the blind packet I rate to carry no transcript,
         score, rank, model guess or judgement, so that my rating is my own.
OUTCOME
  O1  A packet carrying any such hint is refused.
PROVES   O1 -> test_blind_packet_rejects_answer_or_selection_hints
WHY      Never-rule 2: no coach sees the machine's guess before answering.
"""

import uuid

import pytest

from services.mlc2_confidence_blind import (
    RATING_CHOICES,
    validate_blind_packet,
)
from services.mlc2_foundation import Mlc2ContractError

# ── merged from tests/test_mlc2_confidence_blind.py (audit Q-T9) ──

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


@pytest.mark.parametrize("field", [
    "transcript", "score", "rank", "model", "prediction", "judgment",
])
def test_blind_packet_rejects_answer_or_selection_hints(field):
    packet = _packet()
    packet[field] = "leak"
    with pytest.raises(Mlc2ContractError, match="allowlist"):
        validate_blind_packet(packet)
