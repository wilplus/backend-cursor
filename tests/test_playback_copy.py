"""
STORY    As a speaker on iPhone or Safari, I want my recordings to play back,
         and the playback copy deleted with the recording, so that I can hear
         myself and deletion leaves nothing. (Record -> next Take: hearing
         the Take; and deletion.)
OUTCOME
  O1  A stored short recording gets its Safari-safe copy (.playback.m4a,
      audio/mp4) beside it at upload; the original is untouched.
  O2  The player is handed the original until the copy exists, and the copy
      from then on (an old recording's copy is made on first play).
  O3  Deleting a recording deletes its copy FIRST; if the copy cannot be
      deleted, the original is not touched (fail closed).
  O4  A video recording or a non-recording file has no copy and keeps its
      original.
PROVES   O1 -> test_an_upload_makes_the_playback_copy
         O2 -> test_the_player_gets_the_copy_once_it_exists
         O3 -> test_deleting_a_recording_deletes_its_copy_first
               test_a_copy_that_cannot_be_deleted_stops_the_deletion
         O4 -> test_no_copy_for_video_or_non_recordings
WHY      Founder 2026-10-10: playback silent on the iPhone and on Safari.
         ffmpeg is stood in for (an audio file becomes b"m4a", a video None):
         this file pins our wiring, not the encoder.
"""
from __future__ import annotations

import hashlib
from unittest import mock

import pytest

from services import lab_audio_storage
from services import playback_copy as pc
from services.audio_ref_resolver import resolve_playable_ref

KEY = "willab_lab/s/r.webm"
COPY = "willab_lab/s/r.playback.m4a"


class _NotFound(Exception):
    response = {"Error": {"Code": "404"}}


class FakeR2:
    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.calls: list = []
        self.refuse_delete: set = set()

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise _NotFound()
        return {}

    def get_object(self, Bucket, Key):
        body = self.objects[(Bucket, Key)]
        return {"Body": mock.Mock(read=lambda: body)}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.calls.append(("put", Key, ContentType))
        self.objects[(Bucket, Key)] = Body

    def delete_object(self, Bucket, Key):
        self.calls.append(("delete", Key))
        if Key in self.refuse_delete:
            raise RuntimeError("provider refused")
        self.objects.pop((Bucket, Key), None)


@pytest.fixture
def r2(monkeypatch):
    pc.reset_for_tests()
    client = FakeR2()
    monkeypatch.setattr(pc, "_enabled", lambda: True)
    monkeypatch.setattr(pc, "_r2_client", lambda: client)
    monkeypatch.setattr(pc, "transcode_to_m4a",
                        lambda data, timeout=0: None if data.startswith(b"video") else b"m4a")
    yield client
    pc.reset_for_tests()


def test_an_upload_makes_the_playback_copy(r2, monkeypatch):
    monkeypatch.setattr(lab_audio_storage, "lab_audio_segregated", lambda: True)
    monkeypatch.setattr(lab_audio_storage, "lab_audio_bucket", lambda: "b")
    monkeypatch.setattr(lab_audio_storage, "_client", lambda: r2)
    assert lab_audio_storage.put_lab_audio_bytes(KEY, b"opus audio", "audio/webm") == "b"
    assert r2.calls == [("put", KEY, "audio/webm"), ("put", COPY, "audio/mp4")]
    assert r2.objects == {("b", KEY): b"opus audio", ("b", COPY): b"m4a"}


def test_the_player_gets_the_copy_once_it_exists(r2, monkeypatch):
    monkeypatch.setattr("services.coach_video_storage.presigned_get_coach_object",
                        lambda bucket, key, expires_in=0: f"https://signed/{bucket}/{key}")
    scheduled: list = []
    monkeypatch.setattr(pc, "schedule_playback_copy", lambda b, k: scheduled.append((b, k)))
    r2.objects[("b", KEY)] = b"opus audio"  # recorded before copies existed

    assert resolve_playable_ref(f"s3://b/{KEY}") == f"https://signed/b/{KEY}"
    assert scheduled == [("b", KEY)]
    assert pc.make_playback_copy(*scheduled[0]) is True  # the background work
    assert resolve_playable_ref(f"s3://b/{KEY}") == f"https://signed/b/{COPY}"


def _purge(monkeypatch, client):
    body = b"opus audio"
    client.objects[("b", KEY)] = body
    monkeypatch.setattr(lab_audio_storage, "_client", lambda: client)
    monkeypatch.setattr(lab_audio_storage, "get_exact_storage_object_bytes",
                        lambda key, bucket, storage_provider: client.objects[(bucket, key)])
    monkeypatch.setattr(lab_audio_storage, "verify_lab_audio_object_absent",
                        lambda key, bucket, storage_provider: (bucket, key) not in client.objects)
    return lab_audio_storage.delete_verified_lab_audio_object(
        KEY, bucket="b", storage_provider="r2",
        expected_sha256=hashlib.sha256(body).hexdigest())


def test_deleting_a_recording_deletes_its_copy_first(r2, monkeypatch):
    r2.objects[("b", COPY)] = b"m4a"
    assert _purge(monkeypatch, r2) is True
    assert r2.calls == [("delete", COPY), ("delete", KEY)]
    assert not r2.objects


def test_a_copy_that_cannot_be_deleted_stops_the_deletion(r2, monkeypatch):
    r2.refuse_delete.add(COPY)
    with pytest.raises(RuntimeError, match="provider refused"):
        _purge(monkeypatch, r2)
    assert ("b", KEY) in r2.objects


def test_no_copy_for_video_or_non_recordings(r2):
    pc.copy_on_upload("b", "willab_lab/s/v.webm", b"video stream")
    assert pc.playable_key("b", "willab_lab/s/v.webm") == "willab_lab/s/v.webm"
    pc.copy_on_upload("b", "willab_presentations/d.pdf", b"%PDF")
    pc.delete_playback_copy(r2, "b", "willab_presentations/d.pdf")
    assert r2.calls == [] and not r2.objects
