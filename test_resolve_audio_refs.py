"""The corpus player's refs resolve to URLS THAT EXIST (2026-08-10).

The founder's report: the training-corpus play button rendered but was dead.
Chain: the snippet writer's fallback ref is ``s3://<bucket>/<key>`` (minted
when coach_media_public_url cannot build a public URL — worker-written
snippets, the per-service-env class again); the resolver then signed the key
against the COACH-VIDEO bucket regardless of the bucket in the ref, the URL
404ed, the audio element errored, and MediaPlayer disables its button on
error. The bucket inside an ``s3://`` ref is authoritative.

Run: python3 -m unittest test_resolve_audio_refs
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from routes.v2 import coach as coach_mod
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover — env without app deps
    coach_mod = None
    _IMPORT_ERROR = e


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ResolveAudioRefs(unittest.TestCase):

    def _resolve(self, ref):
        rows = [{"audio_ref": ref}]
        calls = []

        def fake_sign(bucket, key, expires_in=0):
            calls.append((bucket, key))
            return f"https://signed/{bucket}/{key}"

        with patch("services.coach_video_storage.presigned_get_coach_object",
                   fake_sign):
            coach_mod._resolve_audio_refs(rows)
        return rows[0]["audio_ref"], calls

    def test_an_s3_ref_signs_against_ITS_OWN_bucket(self):
        out, calls = self._resolve(
            "s3://recordings/charisma_snippets/sess/clip.webm")
        self.assertEqual(
            calls, [("recordings", "charisma_snippets/sess/clip.webm")])
        self.assertTrue(out.startswith("https://signed/recordings/"))

    def test_a_bare_key_keeps_the_coach_video_default(self):
        _out, calls = self._resolve("some/coach/video.mp4")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], "some/coach/video.mp4")

    def test_absolute_urls_pass_through_untouched(self):
        out, calls = self._resolve("https://cdn.example/clip.webm")
        self.assertEqual(out, "https://cdn.example/clip.webm")
        self.assertEqual(calls, [])

    def test_a_failed_signing_leaves_the_ref_visible(self):
        rows = [{"audio_ref": "s3://recordings/k.webm"}]
        with patch("services.coach_video_storage.presigned_get_coach_object",
                   side_effect=RuntimeError("boom")):
            coach_mod._resolve_audio_refs(rows)
        # Left as-is, never nulled: the failure stays debuggable.
        self.assertEqual(rows[0]["audio_ref"], "s3://recordings/k.webm")


if __name__ == "__main__":
    unittest.main()
