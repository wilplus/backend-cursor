from io import BytesIO
import threading
import wave

import numpy as np
import pytest

from services import blind_review_media


def test_blind_clip_contains_only_the_requested_normalized_span(monkeypatch):
    samples = np.linspace(-0.5, 0.5, 32_000, dtype=np.float32)
    monkeypatch.setattr(
        blind_review_media, "decode_audio_to_pcm", lambda _body: samples,
    )

    rendered = blind_review_media.render_blind_clip_wav(
        b"opaque-source", start_offset_ms=500, duration_ms=250,
    )

    with wave.open(BytesIO(rendered), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getframerate() == 16_000
        assert audio.getnframes() == 4_000


@pytest.mark.parametrize(
    ("start_offset_ms", "duration_ms"),
    [(-1, 100), (0, 0), (0, 120_001)],
)
def test_blind_clip_rejects_invalid_ranges(start_offset_ms, duration_ms):
    with pytest.raises(ValueError, match="BLIND_REVIEW_CLIP_INVALID"):
        blind_review_media.render_blind_clip_wav(
            b"opaque-source",
            start_offset_ms=start_offset_ms,
            duration_ms=duration_ms,
        )


def _media_row():
    return {
        "assignment_id": "assignment-1",
        "bucket": "private-audio",
        "object_key": "opaque-source.webm",
        "exact_bytes_sha256": (
            "54798a371f3b33867fd3441adc7694626cf453c009534ce58f42f7c44438cb2b"
        ),
        "byte_size": 6,
        "content_type": "audio/webm",
        "start_offset_ms": 500,
        "duration_ms": 250,
    }


def test_authority_change_while_storage_read_waits_returns_no_audio(monkeypatch):
    state = {"row": _media_row()}
    read_started = threading.Event()
    read_allowed = threading.Event()
    monkeypatch.setattr(
        blind_review_media,
        "render_blind_clip_wav",
        lambda *_args, **_kwargs: b"normalized",
    )

    def load(_row):
        read_started.set()
        assert read_allowed.wait(timeout=5)
        return b"audio!"

    result: list[BaseException] = []

    def run():
        try:
            blind_review_media.load_authorized_blind_clip(
                resolve=lambda: state["row"], load=load,
            )
        except BaseException as error:
            result.append(error)

    worker = threading.Thread(target=run)
    worker.start()
    assert read_started.wait(timeout=5)
    state["row"] = None
    read_allowed.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert len(result) == 1
    assert "BLIND_REVIEW_MEDIA_AUTHORITY_CHANGED" in str(result[0])


def test_unchanged_authority_returns_normalized_exact_span(monkeypatch):
    row = _media_row()
    monkeypatch.setattr(
        blind_review_media,
        "render_blind_clip_wav",
        lambda *_args, **_kwargs: b"normalized",
    )
    assert blind_review_media.load_authorized_blind_clip(
        resolve=lambda: dict(row), load=lambda _row: b"audio!",
    ) == b"normalized"
