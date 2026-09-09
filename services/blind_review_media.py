"""Opaque, normalized audio clips for pre-judgment coach playback."""
from __future__ import annotations

from io import BytesIO
import wave
from collections.abc import Callable
from typing import Any

import numpy as np

from services.audio_metrics import SAMPLE_RATE, decode_audio_to_pcm


_BOUND_FIELDS = (
    "assignment_id",
    "bucket",
    "object_key",
    "exact_bytes_sha256",
    "byte_size",
    "content_type",
    "start_offset_ms",
    "duration_ms",
)


def load_authorized_blind_clip(
    *,
    resolve: Callable[[], dict[str, Any] | None],
    load: Callable[[dict[str, Any]], bytes],
) -> bytes:
    """Read, normalize, then re-authorize the exact clip before release."""
    before = resolve()
    if before is None or any(field not in before for field in _BOUND_FIELDS):
        raise RuntimeError("BLIND_REVIEW_MEDIA_NOT_AUTHORIZED")
    body = load(before)
    from hashlib import sha256

    if (
        len(body) != int(before["byte_size"])
        or sha256(body).hexdigest() != before["exact_bytes_sha256"]
    ):
        raise RuntimeError("BLIND_REVIEW_MEDIA_BYTES_MISMATCH")
    rendered = render_blind_clip_wav(
        body,
        start_offset_ms=int(before["start_offset_ms"]),
        duration_ms=int(before["duration_ms"]),
    )
    after = resolve()
    if after is None or any(after.get(field) != before[field] for field in _BOUND_FIELDS):
        raise RuntimeError("BLIND_REVIEW_MEDIA_AUTHORITY_CHANGED")
    return rendered


def render_blind_clip_wav(
    audio_bytes: bytes, *, start_offset_ms: int, duration_ms: int,
) -> bytes:
    """Return only the assigned span as normalized mono PCM WAV bytes."""
    if (
        not audio_bytes
        or start_offset_ms < 0
        or duration_ms <= 0
        or duration_ms > 120_000
    ):
        raise ValueError("BLIND_REVIEW_CLIP_INVALID")
    samples = decode_audio_to_pcm(audio_bytes)
    if samples is None:
        raise RuntimeError("BLIND_REVIEW_AUDIO_DECODE_FAILED")
    start = (start_offset_ms * SAMPLE_RATE) // 1000
    length = (duration_ms * SAMPLE_RATE) // 1000
    selected = samples[start:start + length]
    if selected.size == 0:
        raise RuntimeError("BLIND_REVIEW_CLIP_EMPTY")
    pcm = (np.clip(selected, -1.0, 1.0) * 32767.0).astype("<i2")
    output = BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())
    return output.getvalue()
