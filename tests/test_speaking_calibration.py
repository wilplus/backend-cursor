"""
STORY: The founder calibrates an owned speaking moment after listening to it.
OUTCOME: See acoustic cues after labeling, reuse only the exact retry and run the stronger chat model.
PROVES: test_review_stays_blind_until_the_founder_labels_the_clip, test_wrong_moment_cannot_use_the_recorded_retry_receipt,
    test_chat_uses_astra_and_only_passes_delivery_descriptions, test_reasoning_model_request_keeps_legacy_chat_parameters_out,
    test_a_revoice_sends_the_recording_for_speech_to_speech, test_a_revoice_refuses_before_any_provider_call (N706).
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


def test_a_revoice_sends_the_recording_for_speech_to_speech():
    import httpx

    from services.elevenlabs_client import ElevenLabsClient
    seen = {}

    def handler(request):
        seen["path"], seen["query"] = request.url.path, dict(request.url.params)
        seen["body"] = request.read()
        return httpx.Response(200, content=b"mp3-bytes", headers={"content-type": "audio/mpeg"})

    client = ElevenLabsClient(api_key="test-key-not-real", base_url="https://api.test",
                              transport=httpx.MockTransport(handler))
    speech = client.convert(voice_id="voice-1", audio=b"webm-bytes", filename="line.webm", content_type="audio/webm")
    assert speech.audio == b"mp3-bytes"
    assert seen["path"] == "/v1/speech-to-speech/voice-1"
    assert seen["query"] == {"output_format": "mp3_44100_128"}
    assert b"webm-bytes" in seen["body"] and b"eleven_multilingual_sts_v2" in seen["body"]


def test_a_revoice_refuses_before_any_provider_call():
    upload = SimpleNamespace(read=lambda _n: b"audio", filename="line.webm", mimetype="audio/webm")
    voices = Mock()
    with patch("services.ai_voice_clip.principal_for", return_value="p"), \
            patch("services.ai_voice_clip._voices", return_value=voices), \
            patch("services.ai_voice_clone.available_to", return_value=True), \
            patch("services.ai_voice_clip._practice_allowed", return_value=None):
        with patch("services.ai_voice_clone.voice_for", return_value=None), pytest.raises(Refusal, match="VOICE_UNAVAILABLE"):
            speaking_calibration.revoice(Mock(), "u", "take", MOMENT, upload)
        with patch("services.ai_voice_clone.voice_for", return_value="v"), \
                patch("services.ai_voice_limits.clip_refusal", return_value="monthly"), \
                pytest.raises(Refusal, match="AI_VOICE_LIMIT"):
            speaking_calibration.revoice(Mock(), "u", "take", MOMENT, upload)
        voices.convert.assert_not_called()
        with patch("services.ai_voice_clone.voice_for", return_value="v"), \
                patch("services.ai_voice_limits.clip_refusal", return_value=None):
            voices.convert.return_value = SimpleNamespace(audio=b"mp3")
            assert speaking_calibration.revoice(Mock(), "u", "take", MOMENT, upload) == b"mp3"
