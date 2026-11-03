"""
STORY    As a speaker, I want my Take's transcript ready sooner after Stop,
         with the same words on the same clock, so that the Ideal Text and
         the feedback come sooner.
OUTCOME
  O1  With the setting on, a long Take is transcribed in parts at once, cut
      in its pauses, and its words and segments come back in order on the
      Take's own clock (N406).
  O2  A part that fails gives the one whole-file call, as always; with the
      setting off, a Take is always the one call.
PROVES   O1 -> test_a_long_take_in_parts_keeps_its_words_on_its_clock
         O2 -> test_a_failed_part_or_the_setting_off_is_the_one_call
WHY      Founder, the Claude Code chat, 3 November 2026: "build it behind a
         setting" (N406).
"""
import numpy as np
import pytest

from services import parallel_transcription as pt
from services.recording_transcription import transcribe_take_audio

RATE = 16000


def _speech(seconds: float) -> np.ndarray:
    """A voice-like hum with a short pause every 10 seconds."""
    t = np.arange(int(seconds * RATE)) / RATE
    hum = 0.3 * np.sin(2 * np.pi * 220 * t)
    hum[(t % 10.0) > 9.4] = 0.0
    return hum.astype(np.float32)


class _Adapter:
    def __init__(self, fail_parts: bool = False):
        self.calls: list[str] = []
        self.fail_parts = fail_parts

    def transcribe_audio(self, audio, filename, **_):
        self.calls.append(filename)
        if filename == "part.wav":
            if self.fail_parts:
                raise RuntimeError("provider hiccup")
            seconds = (len(audio) - 44) / 2 / RATE
            return {"text": "a part", "duration": seconds, "language": "en",
                    "segments": [{"start": 0.0, "end": seconds, "text": "a part"}],
                    "words": [{"word": "a", "start": 0.5, "end": 0.7},
                              {"word": "part", "start": seconds - 1.0, "end": seconds - 0.5}]}
        return {"text": "whole", "duration": 1.0, "language": "en",
                "segments": [], "words": [{"word": "whole", "start": 0.0, "end": 1.0}]}


@pytest.fixture
def take(monkeypatch):
    pcm = _speech(200.0)
    monkeypatch.setattr("services.audio_metrics.decode_audio_to_pcm", lambda _b: pcm)
    return pcm


def _run(adapter, parallel):
    return transcribe_take_audio(
        adapter, b"take", b"take", "take.webm", vocabulary=None, language=None,
        usage_surface="whisper_spoken", usage_user_id="u", usage_session_id="s",
        parallel=parallel)


def test_a_long_take_in_parts_keeps_its_words_on_its_clock(take):
    adapter = _Adapter()
    result = _run(adapter, True)
    assert adapter.calls == ["part.wav"] * 4
    starts = [w["start"] for w in result["words"]]
    assert starts == sorted(starts) and starts[-1] < 200.0
    # Every cut landed in a pause, so no part began or ended mid-sound.
    for cut in pt.cut_points(take, RATE):
        assert (cut % 10.0) > 9.4
    assert result["language"] == "en"
    assert 195.0 < result["duration"] <= 200.0
    assert set(result) == {"text", "duration", "language", "segments", "words"}


def test_a_failed_part_or_the_setting_off_is_the_one_call(take, monkeypatch):
    failing = _Adapter(fail_parts=True)
    assert _run(failing, True)["text"] == "whole"
    assert failing.calls[-1] == "take.webm"
    off = _Adapter()
    monkeypatch.setattr("config.Config.PARALLEL_TRANSCRIPTION_ENABLED", False)
    assert _run(off, None)["text"] == "whole" and off.calls == ["take.webm"]
