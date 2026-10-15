"""Closing an account deletes every coach answer video kept for that
speaker (founder 2026-10-15, fix 5; Privacy 3.6 §7), and only theirs."""
from __future__ import annotations

from unittest.mock import patch

from services import coach_answer_video as cav


class _R2:
    def __init__(self, keys):
        self.keys = set(keys)

    def list_objects_v2(self, Bucket, Prefix, **_):
        return {"Contents": [{"Key": k} for k in sorted(self.keys) if k.startswith(Prefix)],
                "IsTruncated": False}

    def delete_objects(self, Bucket, Delete):
        for obj in Delete["Objects"]:
            self.keys.discard(obj["Key"])


def test_closing_an_account_deletes_that_speakers_answer_videos_only():
    r2 = _R2({"coach-answers/u1/r1/a.mp4", "coach-answers/u1/r2/b.mp4",
              "coach-answers/u2/r3/c.mp4"})
    with patch("services.coach_video_storage.coach_videos_use_r2", return_value=True), \
         patch("services.coach_video_storage._client", return_value=r2), \
         patch("services.coach_video_storage.default_media_bucket", return_value="coach"):
        assert cav.erase_for_user("u1") == 2
    assert r2.keys == {"coach-answers/u2/r3/c.mp4"}
