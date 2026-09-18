"""A refreshed URL must address the bucket the ref was written on.

SIGN AGAINST THE RIGHT BUCKET (2026-09-18). `refreshed_media_url` re-signs user
content from its KEY, and it signed every one of them against the coach bucket:
`media_key_from_ref` returns a key and throws the bucket away, and the call site
passed "" so `presigned_get_coach_object` fell back to `r2_bucket_name()`.

Five public bases exist and each belongs to exactly one bucket. A ref minted on
the lab-audio, journal or user-media base names a key the coach bucket does not
hold, so the refreshed URL was a well-formed signature over nothing and R2
answered 404 -- replacing a URL that had been working.

Run: python3 -m unittest tests.test_media_ref_bucket
"""
from __future__ import annotations

import contextlib
import unittest

import services.coach_video_storage as storage
from services.coach_video_storage import media_ref_bucket

COACH_BASE = "https://pub-coach.r2.dev"
LAB_BASE = "https://pub-lab.r2.dev"
JOURNAL_BASE = "https://pub-journal.r2.dev"
KEY = "willab_presentations/2f8c1d9e4a7b.pdf"


class _StubConfig:
    R2_PUBLIC_BASE_URL = COACH_BASE
    R2_BUCKET_NAME = "coach-feedback-videos"
    COACH_FEEDBACK_VIDEO_BUCKET = "coach-feedback-videos"
    R2_LAB_AUDIO_PUBLIC_BASE_URL = LAB_BASE
    R2_LAB_AUDIO_BUCKET = "willab-lab-audio"
    R2_JOURNAL_PUBLIC_BASE_URL = JOURNAL_BASE
    R2_JOURNAL_BUCKET = "willab-journal"
    R2_AUDIO_PUBLIC_BASE_URL = ""
    R2_AUDIO_BUCKET_NAME = ""
    R2_USER_MEDIA_PUBLIC_BASE_URL = ""
    R2_USER_MEDIA_BUCKET = ""


@contextlib.contextmanager
def _with_config():
    """Write the CACHED INSTANCE, not the Config class.

    `_config()` memoises into `storage._cfg` and only imports `config.Config`
    when that is empty, so patching the class is a bet on nobody else in the
    suite having warmed the cache first -- which is exactly how two tests in
    this area passed alone and failed in the full run.
    """
    previous = storage._cfg
    storage._cfg = _StubConfig()
    try:
        yield
    finally:
        storage._cfg = previous


class MediaRefBucketTests(unittest.TestCase):
    def test_a_lab_audio_ref_names_the_lab_bucket(self):
        """THE BUG. This one was being signed for coach-feedback-videos."""
        with _with_config():
            self.assertEqual(
                media_ref_bucket(f"{LAB_BASE}/{KEY}"), "willab-lab-audio",
            )

    def test_a_journal_ref_names_the_journal_bucket(self):
        with _with_config():
            self.assertEqual(
                media_ref_bucket(f"{JOURNAL_BASE}/{KEY}"), "willab-journal",
            )

    def test_the_coach_base_defers_to_the_default(self):
        """None, not the literal name: `r2_bucket_name()` owns that resolution
        and honours the R2_BUCKET_NAME override. Answering here would be a
        second definition of the default."""
        with _with_config():
            self.assertIsNone(media_ref_bucket(f"{COACH_BASE}/{KEY}"))

    def test_a_presigned_ref_carries_its_bucket_in_the_path(self):
        with _with_config():
            self.assertEqual(
                media_ref_bucket(
                    "https://acct.r2.cloudflarestorage.com/willab-media/"
                    + KEY + "?X-Amz-Signature=deadbeef"
                ),
                "willab-media",
            )

    def test_an_s3_marker_carries_its_bucket(self):
        with _with_config():
            self.assertEqual(media_ref_bucket(f"s3://willab-journal/{KEY}"),
                             "willab-journal")

    def test_a_bucket_only_presigned_url_is_not_mistaken_for_a_key(self):
        with _with_config():
            self.assertIsNone(media_ref_bucket(
                "https://acct.r2.cloudflarestorage.com/willab-media"
                "?X-Amz-Signature=deadbeef"
            ))

    def test_what_it_cannot_place_gets_the_default(self):
        """Never a guess: an unconfigured base, a foreign host, a bare key and
        a non-string all defer rather than naming a bucket."""
        with _with_config():
            for ref in ("https://example.com/somebody/else.pdf", KEY, "",
                        None, 7):
                self.assertIsNone(media_ref_bucket(ref), ref)


if __name__ == "__main__":
    unittest.main()
