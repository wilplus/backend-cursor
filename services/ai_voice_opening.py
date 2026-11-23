"""Polish an AI demo with a long quiet gap between a greeting and its next word."""
import subprocess

import numpy as np

from services.ai_voice_prompt import starts_with_greeting
from services.ai_voice_validator import _timed_words, _tokens
from services.ffmpeg_audio_extract import resolve_ffmpeg_executable


def polish(audio, sentence, selection, heard, verdict):
    failures = set(verdict["failed_checks"])
    if (not selection.get("opening_emphasis") or not starts_with_greeting(sentence)
            or "opening_gap" not in failures
            or failures - {"opening_gap", "opening_pace", "not_stressed"}
            or verdict["measurements"].get("word_error_rate") != 0):
        return None
    words = _timed_words(heard)
    greeting = _tokens(sentence.split(maxsplit=1)[0])
    # The approved calibration is for a single-word greeting.
    if (len(words) < 3 or [w["t"] for w in words] != _tokens(sentence)
            or words[0]["t"] != greeting[0]
            or not sentence.split()[0].endswith((".", "!"))):
        return None
    exe = resolve_ffmpeg_executable()
    if not exe:
        return None
    rate = 44100
    def convert(args, data):
        return subprocess.run([exe, "-v", "error", *args, "pipe:1"], input=data,
                              capture_output=True, check=True, timeout=12).stdout
    try:
        pcm = np.frombuffer(convert(["-i", "pipe:0", "-ac", "1", "-ar", str(rate),
                                     "-f", "f32le"], audio), dtype="<f4")
        word_end = round(words[1]["end"] * rate)
        if not 0 < word_end < pcm.size:
            return None
        # Use the waveform because word timestamps can include the pause.
        frame = 441
        frames = pcm[:word_end // frame * frame].reshape(-1, frame)
        quiet = np.max(np.abs(frames), axis=1) < 0.006
        edges = np.flatnonzero(np.diff(np.r_[False, quiet, False]))
        gaps = [(a*frame, b*frame) for a,b in edges.reshape(-1, 2)
                if b-a >= 30 and a >= 15 and b*frame < word_end
                and a*frame/rate <= words[1]["start"] + 0.12
                and b*frame/rate >= words[0]["end"] - 0.12]
        if len(gaps) != 1:
            return None
        a,b = gaps[0]
        samples = pcm.copy()
        ramp = round(.015*rate)
        samples[a:a+ramp] *= np.linspace(1, 0, ramp)
        samples[b-ramp:b] *= np.linspace(0, 1, ramp)
        emphasis = np.minimum(np.arange(word_end-b), np.arange(word_end-b)[::-1])
        samples[b:word_end] *= 10 ** (2.6/20 * np.clip(emphasis/(.06*rate), 0, 1))
        samples = np.concatenate((samples[:a+ramp], np.zeros(round(.07*rate), dtype="<f4"),
                                  samples[b-ramp:]))
        # Same small pitch change as the approved render, with duration restored.
        return convert(["-f", "f32le", "-ac", "1", "-ar", str(rate), "-i", "pipe:0",
                        "-af", "asetrate=42968,aresample=44100,atempo=1.02635",
                        "-c:a", "libmp3lame", "-b:a", "160k", "-f", "mp3"],
                       samples.astype("<f4").tobytes())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
