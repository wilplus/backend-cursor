"""Pinned Odyssey clip inference for the dedicated model process."""
from __future__ import annotations

import json
import wave
from functools import lru_cache
from io import BytesIO
from math import ceil, isfinite
from pathlib import Path
from typing import Any

import numpy as np

from services.min_content_gate import evaluate_min_content

MODEL = "3loi/SER-Odyssey-Baseline-WavLM-Multi-Attributes"
REVISION = "00d0e12ba9bf957f5aeea36e8663c8c61cb50ac9"
ENCODER = "microsoft/wavlm-large"
ENCODER_REVISION = "c1423ed94bb01d80a3f5ce5bc39f6026a0f4828c"
MODEL_VERSION = f"{MODEL}@{REVISION}/clip-v1"
DIMENSIONS = ("arousal", "dominance", "valence")
SAMPLE_RATE = 16_000
MAX_SECONDS = 30
MAX_WAV_BYTES = MAX_SECONDS * SAMPLE_RATE * 2 + 4096


class UnusableAudio(ValueError):
    """The clip has no usable speech in the supported recording format."""


def prepare_artifacts(directory: Path) -> None:
    """Fetch only the reviewed configuration and weights during image build."""
    from huggingface_hub import hf_hub_download

    for name in ("model.safetensors", "config.json", "README.md"):
        hf_hub_download(MODEL, name, revision=REVISION, local_dir=directory)
    encoder = hf_hub_download(ENCODER, "config.json", revision=ENCODER_REVISION)
    (directory / "wavlm.json").write_bytes(Path(encoder).read_bytes())


@lru_cache(maxsize=1)
def load_model(directory: Path) -> tuple[Any, dict, dict]:
    import torch
    from safetensors.torch import load_file
    from transformers import WavLMConfig, WavLMModel

    config = json.loads((directory / "config.json").read_text())
    if (tuple(config["id2label"][str(i)] for i in range(len(DIMENSIONS))) != DIMENSIONS
            or config["sampling_rate"] != SAMPLE_RATE or config["classifier_hidden_layers"] != 1):
        raise RuntimeError("Unexpected Odyssey checkpoint configuration")
    weights = load_file(str(directory / "model.safetensors"))
    prefix = "ssl_model."
    encoder_weights = {name[len(prefix):]: value for name, value in weights.items() if name.startswith(prefix)}
    head = {name: value for name, value in weights.items() if not name.startswith(prefix)}
    with torch.device("meta"):
        encoder = WavLMModel(WavLMConfig.from_json_file(directory / "wavlm.json"))
    encoder.load_state_dict(encoder_weights, strict=True, assign=True)
    return encoder.eval(), head, config


def _speech_audio(audio: bytes) -> np.ndarray:
    if len(audio) > MAX_WAV_BYTES:
        raise UnusableAudio("Clip is too large")
    try:
        with wave.open(BytesIO(audio), "rb") as recording:
            if (recording.getnchannels(), recording.getsampwidth(), recording.getframerate()) != (1, 2, SAMPLE_RATE):
                raise UnusableAudio("Expected 16 kHz mono PCM")
            frames = recording.getnframes()
            if not 0 < frames <= MAX_SECONDS * SAMPLE_RATE:
                raise UnusableAudio("Clip duration is out of range")
            samples = np.frombuffer(recording.readframes(frames), dtype="<i2")
            if len(samples) != frames:
                raise UnusableAudio("Incomplete clip")
    except (EOFError, wave.Error, ValueError) as error:
        raise UnusableAudio("Unreadable clip") from error
    pcm = samples.astype(np.float32) / 32768.0
    if not evaluate_min_content(pcm)["ok"]:
        raise UnusableAudio("Clip needs speech")
    return pcm


def _predict(encoder: Any, head: dict, waveform: Any) -> list[float]:
    from torch import cat, softmax, tanh
    from torch.nn.functional import layer_norm, linear, relu

    frames = encoder(waveform).last_hidden_state[0]
    attention = tanh(linear(frames, head["pool_model.sap_linear.weight"], head["pool_model.sap_linear.bias"]))
    weights = softmax(attention @ head["pool_model.attention"], dim=0)
    mean = (frames * weights).sum(dim=0)
    variance = (frames.square() * weights).sum(dim=0) - mean.square()
    pooled = cat((mean, variance.clamp(min=1e-5).sqrt()))
    hidden = linear(pooled, head["ser_model.fc.0.0.weight"], head["ser_model.fc.0.0.bias"])
    hidden = relu(layer_norm(hidden, hidden.shape, head["ser_model.fc.0.1.weight"], head["ser_model.fc.0.1.bias"]))
    return linear(hidden, head["ser_model.out.0.weight"], head["ser_model.out.0.bias"]).tolist()


def valid_scores(value: Any) -> bool:
    return (isinstance(value, dict) and set(value) == set(DIMENSIONS)
            and all(type(number) in (int, float) and isfinite(number) for number in value.values()))


def score(audio: bytes, directory: Path) -> dict[str, float]:
    """Score the provided clip. Speaker or reference identity is resolved upstream."""
    import torch

    pcm = _speech_audio(audio)
    encoder, head, config = load_model(directory)
    parts = np.array_split(pcm, ceil(len(pcm) / config["maxlen"]))
    outputs, lengths = [], []
    with torch.inference_mode():
        for part in parts:
            if evaluate_min_content(part)["ok"]:
                waveform = torch.from_numpy((part - config["mean"]) / (config["std"] + 1e-6)).unsqueeze(0)
                outputs.append(_predict(encoder, head, waveform))
                lengths.append(len(part))
    if not outputs:
        raise UnusableAudio("Clip needs speech")
    result = dict(zip(DIMENSIONS, np.average(outputs, axis=0, weights=lengths).tolist(), strict=True))
    if not valid_scores(result):
        raise RuntimeError("Unexpected Odyssey output")
    return result
