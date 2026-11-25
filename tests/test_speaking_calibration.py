"""
STORY: The founder calibrates an owned speaking moment after listening to it.
OUTCOME: See acoustic cues after labeling, reuse only the exact retry and run the stronger chat model.
PROVES: test_review_stays_blind_until_the_founder_labels_the_clip, test_wrong_moment_cannot_use_the_recorded_retry_receipt,
    test_chat_uses_astra_and_only_passes_delivery_descriptions, test_reasoning_model_request_keeps_legacy_chat_parameters_out.
"""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from services import speaking_calibration
from services.llm import operational_chat_complete
from services.llm_config import SPEC_CALIBRATION_CHAT_STRONG
from services.refusal import Refusal

MOMENT = {"id": "moment", "duration_ms": 5000, "metrics": {"wpm": 178}, "transcript": "One question."}


def test_review_stays_blind_until_the_founder_labels_the_clip():
    db = object()
    with patch.object(speaking_calibration, "_read", return_value=(1, {})):
        assert speaking_calibration.get(db, "owner", "take", MOMENT)["cues"] == {}
    with patch.object(speaking_calibration, "_read", return_value=(2, {"moment": {"label": "rushed"}})):
        assert speaking_calibration.get(db, "owner", "take", MOMENT)["cues"] == {"wpm": 178}


def test_wrong_moment_cannot_use_the_recorded_retry_receipt():
    receipt = speaking_calibration._serializer().dumps(
        {"owner": "owner", "take": "take", "snippet": "other", "cues": {}},
    )
    with pytest.raises(Refusal, match="INVALID_RETRY"):
        speaking_calibration._retry({"receipt": receipt}, "owner", "take", "moment")


def test_chat_uses_astra_and_only_passes_delivery_descriptions():
    approved = {"revision": 1, "record": {"label": "flat", "values": {"pitch": 1}},
                "cues": {"f0_mean": 100, "f0_sd": 25}}
    with (patch.object(speaking_calibration, "get", return_value=approved),
          patch("services.llm.chat_complete", return_value=SimpleNamespace(text="Try a gentle lift.")) as complete):
        reply = speaking_calibration.reply(
            object(), "owner", "take", MOMENT, {"history": [], "model": "strong", "question": "Try a little warmer?"},
        )
    assert reply == {"reply": "Try a gentle lift."}
    assert complete.call_args.kwargs["spec"] == SPEC_CALIBRATION_CHAT_STRONG
    sent = json.loads(complete.call_args.kwargs["user"])
    assert sent["original_delivery"] == {"pitch": "natural rise and fall"}
    assert sent["observation"]["values"] == {"pitch": 1}


def test_reasoning_model_request_keeps_legacy_chat_parameters_out():
    client = Mock()
    operational_chat_complete(client, model="gpt-6.2-astra", messages=[], temperature=1,
                              max_tokens=2400, reasoning_effort="medium")
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["max_completion_tokens"] == 2400 and kwargs["reasoning_effort"] == "medium"
    assert "temperature" not in kwargs and "max_tokens" not in kwargs
