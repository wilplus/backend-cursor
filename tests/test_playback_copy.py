"""The Safari-safe playback copy (founder 2026-10-10: playback silent on the
iPhone and on Safari on the Mac). services/playback_copy.py."""
from __future__ import annotations

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


def test_deleting_a_recording_deletes_its_copy_first():
    client = FakeClient()
    pc.delete_playback_copy(client, "b", "willab_lab/s/r.webm")
    assert client.calls == [("delete", "b", "willab_lab/s/r.playback.m4a")]
    client.calls.clear()
    pc.delete_playback_copy(client, "b", "willab_presentations/d.pdf")
    assert client.calls == []
