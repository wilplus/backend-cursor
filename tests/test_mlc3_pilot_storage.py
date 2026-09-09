from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from services.mlc3_pilot_storage import ReservedObject, store_exact_object
from services import coach_video_storage, user_media_storage


class MemoryStorage:
    def __init__(self, *, fail_after_write: bool = False, corrupt_read: bool = False):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.fail_after_write = fail_after_write
        self.corrupt_read = corrupt_read

    def put(self, *, bucket: str, key: str, body: bytes, content_type: str) -> None:
        del content_type
        self.objects[(bucket, key)] = body
        if self.fail_after_write:
            raise TimeoutError("provider acknowledgement lost")

    def get(self, *, bucket: str, key: str) -> bytes:
        body = self.objects[(bucket, key)]
        return body + b"corrupt" if self.corrupt_read else body


def harness(storage: MemoryStorage):
    calls: list[str] = []
    reserved_rows: list[ReservedObject] = []

    def reserve(*, exact_bytes_sha256: str, byte_size: int, content_type: str):
        row = ReservedObject(
            recovery_id="recovery-1",
            bucket="private-practice",
            object_key="pilot/object.webm",
            exact_bytes_sha256=exact_bytes_sha256,
            byte_size=byte_size,
            content_type=content_type,
        )
        reserved_rows.append(row)
        calls.append("reserved")
        return row

    def started(row: ReservedObject):
        assert row is reserved_rows[0]
        calls.append("write_started")

    def acknowledged(row: ReservedObject):
        assert row is reserved_rows[0]
        calls.append("write_acknowledged")

    def finalize(*, recovery: ReservedObject, verification_method: str):
        assert recovery is reserved_rows[0]
        assert verification_method == "read_after_write_sha256"
        calls.append("finalized")
        return "media-1"

    return calls, reserved_rows, reserve, started, acknowledged, finalize


def test_verified_upload_orders_durable_recovery_before_storage():
    storage = MemoryStorage()
    calls, rows, reserve, started, acknowledged, finalize = harness(storage)
    result = store_exact_object(
        body=b"practice-audio",
        content_type="audio/webm",
        reserve=reserve,
        finalize=finalize,
        storage=storage,
        record_write_started=started,
        record_write_acknowledged=acknowledged,
    )
    assert calls == ["reserved", "write_started", "write_acknowledged", "finalized"]
    assert rows and result.media_object_id == "media-1"


def test_lost_provider_acknowledgement_leaves_recovery_unresolved():
    storage = MemoryStorage(fail_after_write=True)
    calls, rows, reserve, started, acknowledged, finalize = harness(storage)
    with pytest.raises(TimeoutError):
        store_exact_object(
            body=b"stored-before-timeout",
            content_type="audio/webm",
            reserve=reserve,
            finalize=finalize,
            storage=storage,
            record_write_started=started,
            record_write_acknowledged=acknowledged,
        )
    assert calls == ["reserved", "write_started"]
    assert rows and storage.objects


def test_corrupt_read_never_finalizes():
    storage = MemoryStorage(corrupt_read=True)
    calls, rows, reserve, started, acknowledged, finalize = harness(storage)
    with pytest.raises(RuntimeError, match="READ_AFTER_WRITE_MISMATCH"):
        store_exact_object(
            body=b"practice-audio",
            content_type="audio/webm",
            reserve=reserve,
            finalize=finalize,
            storage=storage,
            record_write_started=started,
            record_write_acknowledged=acknowledged,
        )
    assert calls == ["reserved", "write_started"]


def test_reservation_identity_mismatch_fails_before_provider_write():
    storage = MemoryStorage()
    calls, rows, reserve, started, acknowledged, finalize = harness(storage)

    def wrong_reserve(**kwargs):
        return replace(reserve(**kwargs), object_key="other", byte_size=99)

    with pytest.raises(RuntimeError, match="RESERVATION_CONFLICT"):
        store_exact_object(
            body=b"practice-audio",
            content_type="audio/webm",
            reserve=wrong_reserve,
            finalize=finalize,
            storage=storage,
            record_write_started=started,
            record_write_acknowledged=acknowledged,
        )
    assert calls == ["reserved"]
    assert rows and not storage.objects


def test_verified_replay_reads_existing_object_without_rewriting_it():
    storage = MemoryStorage(fail_after_write=True)
    calls, rows, reserve, started, acknowledged, finalize = harness(storage)
    storage.objects[("private-practice", "pilot/object.webm")] = (
        b"practice-audio"
    )

    def replay_reserve(**kwargs):
        row = replace(reserve(**kwargs), write_required=False)
        rows[0] = row
        return row

    result = store_exact_object(
        body=b"practice-audio",
        content_type="audio/webm",
        reserve=replay_reserve,
        finalize=finalize,
        storage=storage,
        record_write_started=started,
        record_write_acknowledged=acknowledged,
    )
    assert result.media_object_id == "media-1"
    assert calls == ["reserved", "write_acknowledged", "finalized"]


def test_service_user_media_fails_closed_without_r2(monkeypatch):
    config = SimpleNamespace(
        R2_ACCOUNT_ID="", R2_ACCESS_KEY_ID="", R2_SECRET_ACCESS_KEY="",
        R2_USER_MEDIA_BUCKET="", R2_BUCKET_NAME="",
        COACH_FEEDBACK_VIDEO_BUCKET="legacy",
    )
    monkeypatch.setattr(user_media_storage, "_config", lambda: config)
    with pytest.raises(RuntimeError, match="MLC3_R2_USER_MEDIA_NOT_CONFIGURED"):
        user_media_storage.put_user_media_r2_bytes(
            "practice.webm", b"audio", "audio/webm",
        )
    with pytest.raises(RuntimeError, match="MLC3_R2_USER_MEDIA_NOT_CONFIGURED"):
        user_media_storage.presigned_get_user_media_r2(
            "practice.webm", bucket="legacy",
        )


def test_service_coach_media_fails_closed_without_r2(monkeypatch):
    config = SimpleNamespace(
        R2_ACCOUNT_ID="", R2_ACCESS_KEY_ID="", R2_SECRET_ACCESS_KEY="",
        R2_BUCKET_NAME="", COACH_FEEDBACK_VIDEO_BUCKET="legacy",
    )
    monkeypatch.setattr(coach_video_storage, "_cfg", config)
    with pytest.raises(RuntimeError, match="MLC3_R2_COACH_MEDIA_NOT_CONFIGURED"):
        coach_video_storage.put_coach_object_r2_bytes(
            "legacy", "exercise.mp4", b"video", "video/mp4",
        )
    with pytest.raises(RuntimeError, match="MLC3_R2_COACH_MEDIA_NOT_CONFIGURED"):
        coach_video_storage.presigned_get_coach_object_r2(
            "legacy", "exercise.mp4",
        )
