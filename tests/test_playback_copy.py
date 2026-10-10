"""The Safari-safe playback copy (founder 2026-10-10: playback silent on the
iPhone and on Safari on the Mac). services/playback_copy.py."""
from __future__ import annotations

import shutil
import subprocess
from unittest import mock

import pytest

from services import playback_copy as pc


class _NotFound(Exception):
    response = {"Error": {"Code": "404"}}


class FakeClient:
    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.calls: list = []

    def head_object(self, Bucket, Key):
        self.calls.append(("head", Bucket, Key))
        if (Bucket, Key) not in self.objects:
            raise _NotFound()
        return {}

    def get_object(self, Bucket, Key):
        self.calls.append(("get", Bucket, Key))
        body = self.objects[(Bucket, Key)]
        return {"Body": mock.Mock(read=lambda: body)}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.calls.append(("put", Bucket, Key, ContentType))
        self.objects[(Bucket, Key)] = Body

    def delete_object(self, Bucket, Key):
        self.calls.append(("delete", Bucket, Key))
        self.objects.pop((Bucket, Key), None)


@pytest.fixture(autouse=True)
def _clean():
    pc.reset_for_tests()
    with mock.patch.object(pc, "_enabled", return_value=True):
        yield
    pc.reset_for_tests()


def test_only_spoken_webm_recordings_get_a_copy_key():
    assert pc.playback_key("willab_lab/s1/recording_ab.webm") == \
        "willab_lab/s1/recording_ab.playback.m4a"
    assert pc.playback_key("confidence-practice/u/p/a1.webm") == \
        "confidence-practice/u/p/a1.playback.m4a"
    assert pc.playback_key("willab_presentations/deck.pdf") is None
    assert pc.playback_key("coach-feedback/v.webm") is None
    assert pc.playback_key("willab_lab/s1/recording.m4a") is None
    assert pc.playback_key(None) is None


def test_the_player_gets_the_copy_once_it_exists():
    client = FakeClient({("b", "willab_lab/s/r.playback.m4a"): b"m4a"})
    with mock.patch.object(pc, "_r2_client", return_value=client), \
            mock.patch.object(pc, "schedule_playback_copy") as schedule:
        assert pc.playable_key("b", "willab_lab/s/r.webm") == \
            "willab_lab/s/r.playback.m4a"
        # Cached: a second read asks storage nothing.
        assert pc.playable_key("b", "willab_lab/s/r.webm") == \
            "willab_lab/s/r.playback.m4a"
    assert [c[0] for c in client.calls] == ["head"]
    schedule.assert_not_called()


def test_a_missing_copy_serves_the_original_and_is_made_behind():
    client = FakeClient()
    with mock.patch.object(pc, "_r2_client", return_value=client), \
            mock.patch.object(pc, "schedule_playback_copy") as schedule:
        assert pc.playable_key("b", "willab_lab/s/r.webm") == "willab_lab/s/r.webm"
    schedule.assert_called_once_with("b", "willab_lab/s/r.webm")


def test_off_or_not_a_recording_leaves_the_key_alone():
    with mock.patch.object(pc, "_r2_client") as client:
        assert pc.playable_key("b", "willab_presentations/d.pdf") == \
            "willab_presentations/d.pdf"
        with mock.patch.object(pc, "_enabled", return_value=False):
            assert pc.playable_key("b", "willab_lab/s/r.webm") == "willab_lab/s/r.webm"
    client.assert_not_called()


def test_making_the_copy_writes_audio_mp4_beside_the_original():
    client = FakeClient({("b", "willab_lab/s/r.webm"): b"webm-bytes"})
    with mock.patch.object(pc, "_r2_client", return_value=client), \
            mock.patch.object(pc, "transcode_to_m4a", return_value=b"m4a-bytes"):
        assert pc.make_playback_copy("b", "willab_lab/s/r.webm") is True
    assert client.objects[("b", "willab_lab/s/r.playback.m4a")] == b"m4a-bytes"
    assert ("put", "b", "willab_lab/s/r.playback.m4a", "audio/mp4") in client.calls
    assert client.objects[("b", "willab_lab/s/r.webm")] == b"webm-bytes"


def test_a_video_or_unreadable_file_gets_no_copy_and_is_not_retried():
    client = FakeClient({("b", "willab_lab/s/r.webm"): b"video"})
    with mock.patch.object(pc, "_r2_client", return_value=client), \
            mock.patch.object(pc, "transcode_to_m4a", return_value=None):
        assert pc.make_playback_copy("b", "willab_lab/s/r.webm") is False
        assert pc.playable_key("b", "willab_lab/s/r.webm") == "willab_lab/s/r.webm"
    assert not any(c[0] == "put" for c in client.calls)


def test_deleting_a_recording_deletes_its_copy_first():
    client = FakeClient()
    pc.delete_playback_copy(client, "b", "willab_lab/s/r.webm")
    assert client.calls == [("delete", "b", "willab_lab/s/r.playback.m4a")]
    client.calls.clear()
    pc.delete_playback_copy(client, "b", "willab_presentations/d.pdf")
    assert client.calls == []


def test_the_older_recordings_cleanup_deletes_the_copy_before_the_original():
    from services import bundled_era_storage as be

    client = FakeClient()
    place = be.Place("r2", "b", "willab_lab/s/r.webm")
    with mock.patch("services.lab_audio_storage._client", return_value=client):
        be._default_delete(place)
    assert [c[2] for c in client.calls] == [
        "willab_lab/s/r.playback.m4a", "willab_lab/s/r.webm"]


def test_a_copy_that_cannot_be_deleted_stops_the_deletion():
    from services import bundled_era_storage as be

    client = FakeClient()

    def refuse(Bucket, Key):
        raise RuntimeError("provider down")

    client.delete_object = refuse  # type: ignore[method-assign]
    with mock.patch("services.lab_audio_storage._client", return_value=client), \
            pytest.raises(RuntimeError):
        be._default_delete(be.Place("r2", "b", "willab_lab/s/r.webm"))


def test_the_player_resolver_signs_the_copy_when_it_exists():
    from services import audio_ref_resolver as resolver

    signed: list = []
    with mock.patch.object(pc, "playable_key",
                           side_effect=lambda b, k: k.replace(".webm", ".playback.m4a")), \
            mock.patch("services.coach_video_storage.default_media_bucket",
                       return_value="b"), \
            mock.patch("services.coach_video_storage.presigned_get_coach_object",
                       side_effect=lambda bucket, key, expires_in: signed.append(key)
                       or f"https://signed/{key}"):
        out = resolver.resolve_playable_ref("s3://b/willab_lab/s/r.webm")
    assert signed == ["willab_lab/s/r.playback.m4a"]
    assert out == "https://signed/willab_lab/s/r.playback.m4a"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_a_real_webm_becomes_an_mp4_safari_can_play(tmp_path):
    src = tmp_path / "t.webm"
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=2", "-c:a", "libopus",
                    str(src)], check=True)
    with mock.patch("services.webm_remux._ffmpeg", return_value=shutil.which("ffmpeg")):
        out = pc.transcode_to_m4a(src.read_bytes())
    assert out is not None and out[4:8] == b"ftyp"


def test_a_short_practise_clip_is_copied_during_its_upload():
    client = FakeClient()
    with mock.patch.object(pc, "_r2_client", return_value=client), \
            mock.patch.object(pc, "transcode_to_m4a", return_value=b"m4a"), \
            mock.patch.object(pc, "schedule_playback_copy") as schedule:
        pc.copy_on_upload("b", "confidence-practice/u/p/a.webm", b"x" * 1000)
        assert pc.playable_key("b", "confidence-practice/u/p/a.webm") == \
            "confidence-practice/u/p/a.playback.m4a"
        pc.copy_on_upload("b", "willab_lab/s/take.webm", b"x" * 2_000_000)
    schedule.assert_called_once_with("b", "willab_lab/s/take.webm")


def test_storing_lab_audio_starts_its_copy():
    from services import lab_audio_storage as las

    with mock.patch.object(las, "lab_audio_segregated", return_value=True), \
            mock.patch.object(las, "lab_audio_bucket", return_value="lab"), \
            mock.patch.object(las, "_client", return_value=FakeClient()), \
            mock.patch.object(pc, "copy_on_upload") as copy:
        las.put_lab_audio_bytes("willab_lab/s/r.webm", b"abc", "audio/webm")
    copy.assert_called_once_with("lab", "willab_lab/s/r.webm", b"abc")
