"""The one bucket-authoritative ref resolver — including the 2026-08-11
rule: our OWN public bases are not trusted blindly. A writer with the base
env set mints `{base}/{key}` whether or not the bucket actually serves that
base, so a healthy-looking row can 403 on every play (the dead
Feedbacks-review players). Refs on a configured base re-sign against that
base's bucket; foreign https URLs pass through.

Run: python3 -m unittest test_audio_ref_resolver
"""
import unittest
from unittest.mock import patch

import config as config_mod
from services import audio_ref_resolver as arr


def _cfg(**over):
    base = {
        "R2_PUBLIC_BASE_URL": "https://pub-coach.r2.dev",
        "R2_BUCKET_NAME": "",
        "COACH_FEEDBACK_VIDEO_BUCKET": "coach_feedback_videos",
        "R2_LAB_AUDIO_PUBLIC_BASE_URL": "https://pub-lab.r2.dev",
        "R2_LAB_AUDIO_BUCKET": "willab-lab-audio",
        "R2_AUDIO_PUBLIC_BASE_URL": "https://pub-interview.r2.dev",
        "R2_AUDIO_BUCKET_NAME": "user-interview-audio",
    }
    base.update(over)
    return [patch.object(config_mod.Config, k, v, create=True)
            for k, v in base.items()]


class ResolverPublicBaseTests(unittest.TestCase):

    def _resolve(self, ref, *, sign=None, cfg=None):
        signs: list = []

        def _fake_sign(bucket, key, expires_in=0):
            signs.append((bucket, key))
            return sign

        patches = _cfg(**(cfg or {}))
        patches.append(patch(
            "services.coach_video_storage.presigned_get_coach_object",
            _fake_sign))
        for p in patches:
            p.start()
        try:
            out = arr.resolve_playable_ref(ref)
        finally:
            for p in patches:
                p.stop()
        return out, signs

    def test_a_ref_on_our_coach_base_is_resigned_against_the_coach_bucket(self):
        out, signs = self._resolve(
            "https://pub-coach.r2.dev/willab_lab/s1/take.webm",
            sign="https://signed/x")
        self.assertEqual(out, "https://signed/x")
        self.assertEqual(signs, [("coach_feedback_videos",
                                  "willab_lab/s1/take.webm")])

    def test_a_ref_on_the_lab_base_signs_against_the_lab_bucket(self):
        out, signs = self._resolve(
            "https://pub-lab.r2.dev/willab_lab/s1/take.webm",
            sign="https://signed/y")
        self.assertEqual(out, "https://signed/y")
        self.assertEqual(signs[0][0], "willab-lab-audio")

    def test_a_ref_on_the_interview_base_signs_against_its_bucket(self):
        out, signs = self._resolve(
            "https://pub-interview.r2.dev/session_recordings/s/full.webm",
            sign="https://signed/z")
        self.assertEqual(out, "https://signed/z")
        self.assertEqual(signs[0][0], "user-interview-audio")

    def test_the_bucket_name_override_wins_for_the_coach_base(self):
        out, signs = self._resolve(
            "https://pub-coach.r2.dev/k.webm", sign="https://signed/o",
            cfg={"R2_BUCKET_NAME": "override-bucket"})
        self.assertEqual(signs[0][0], "override-bucket")

    def test_a_foreign_https_url_passes_through_untouched(self):
        out, signs = self._resolve("https://cdn.example.com/talk.mp3",
                                   sign="https://signed/never")
        self.assertEqual(out, "https://cdn.example.com/talk.mp3")
        self.assertEqual(signs, [])

    def test_signing_failure_returns_the_input_unchanged(self):
        # Visible and debuggable beats silently missing — same rule as the
        # s3:// branch.
        out, _ = self._resolve(
            "https://pub-coach.r2.dev/willab_lab/s1/take.webm", sign=None)
        self.assertEqual(out,
                         "https://pub-coach.r2.dev/willab_lab/s1/take.webm")

    def test_s3_refs_still_sign_against_their_own_bucket(self):
        out, signs = self._resolve("s3://some-bucket/a/b.webm",
                                   sign="https://signed/s3")
        self.assertEqual(out, "https://signed/s3")
        self.assertEqual(signs, [("some-bucket", "a/b.webm")])

    def test_nothing_in_nothing_out(self):
        self.assertIsNone(arr.resolve_playable_ref(None))
        self.assertIsNone(arr.resolve_playable_ref(""))


if __name__ == "__main__":
    unittest.main()
