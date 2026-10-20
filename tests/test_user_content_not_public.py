"""
STORY    As a speaker, I want my recordings served only through short-lived
         signed links, so that a leaked link does not expose my voice forever.
OUTCOME
  O1  Each of the four stored snippet row shapes resolves to a signed link
      against its own bucket, never a URL under a public base; stored public
      URLs are re-signed on read.
  O2  When R2 cannot sign, a stored key falls through to a Supabase signed
      link, never a bare key or a public URL.
PROVES   O1 -> test_path_a_before_finalize_a_public_turn_url_is_re_signed
            -> test_path_a_after_finalize_the_session_key_wins_and_is_signed
            -> test_path_b_a_public_full_url_is_re_signed
            -> test_path_c_a_supabase_key_gets_a_supabase_signed_link
         O2 -> test_a_dead_signer_falls_through_to_supabase_not_to_a_bare_key
WHY      DPIA RISK-11 (2026-09-17): every read path handed out permanent public
         bucket URLs. The four row shapes do not share a code path.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import config as config_mod

_COACH_BASE = "https://pub-coach.r2.dev"
_AUDIO_BASE = "https://pub-interview.r2.dev"
_LAB_BASE = "https://pub-lab.r2.dev"
_PUBLIC_BASES = (_COACH_BASE, _AUDIO_BASE, _LAB_BASE)
_SIGNED_HOST = "https://acct.r2.cloudflarestorage.com"
_SUPABASE_HOST = "https://proj.supabase.co/storage/v1/object/sign"


def _cfg(**over):
    base = {
        "R2_PUBLIC_BASE_URL": _COACH_BASE,
        "R2_BUCKET_NAME": "",
        "COACH_FEEDBACK_VIDEO_BUCKET": "coach-feedback-videos",
        "R2_LAB_AUDIO_PUBLIC_BASE_URL": _LAB_BASE,
        "R2_LAB_AUDIO_BUCKET": "willab-lab-audio",
        "R2_AUDIO_PUBLIC_BASE_URL": _AUDIO_BASE,
        "R2_AUDIO_BUCKET_NAME": "user-interview-audio",
    }
    base.update(over)
    return [patch.object(config_mod.Config, k, v, create=True)
            for k, v in base.items()]


class TheFourSnippetRowShapes(unittest.TestCase):

    def _resolve(self, snippet, *, signer=True):
        from services.snippet_audio_url import resolve_snippet_audio_url

        def sign(bucket, key, expires_in=0, **_kw):
            return f"{_SIGNED_HOST}/{bucket}/{key}?X-Amz-Signature=x" if signer else None

        class _Db:
            def create_signed_url(self, bucket, path, _expiry):
                return f"{_SUPABASE_HOST}/{bucket}/{path}?token=x"

        app_config = SimpleNamespace(AUDIO_BUCKET_NAME="audio",
                                     SIGNED_URL_EXPIRY_SECONDS=600)
        patches = _cfg() + [patch(
            "services.coach_video_storage.presigned_get_coach_object", sign)]
        for p in patches:
            p.start()
        try:
            out = resolve_snippet_audio_url(snippet, database=_Db(),
                                            app_config=app_config)
        finally:
            for p in patches:
                p.stop()
        for base in _PUBLIC_BASES:
            self.assertFalse(str(out).startswith(base), out)
        return out

    def test_path_a_before_finalize_a_public_turn_url_is_re_signed(self):
        out = self._resolve({"audio_segment_path": f"{_LAB_BASE}/willab_lab/u/turn1.webm",
                             "storage_path": None})
        self.assertEqual(out, f"{_SIGNED_HOST}/willab-lab-audio/willab_lab/u/turn1.webm"
                              "?X-Amz-Signature=x")

    def test_path_a_after_finalize_the_session_key_wins_and_is_signed(self):
        out = self._resolve({"audio_segment_path": f"{_LAB_BASE}/willab_lab/u/turn1.webm",
                             "storage_path": "session_recordings/s/full.webm"})
        self.assertEqual(out, f"{_SIGNED_HOST}/user-interview-audio/"
                              "session_recordings/s/full.webm?X-Amz-Signature=x")

    def test_path_b_a_public_full_url_is_re_signed(self):
        out = self._resolve({"audio_segment_path": f"{_COACH_BASE}/snippets/s/clip.webm",
                             "storage_path": None})
        self.assertEqual(out, f"{_SIGNED_HOST}/coach-feedback-videos/snippets/s/clip.webm"
                              "?X-Amz-Signature=x")

    def test_path_c_a_supabase_key_gets_a_supabase_signed_link(self):
        out = self._resolve({"audio_segment_path": None,
                             "storage_path": "charisma_snippets/u/clip.webm"})
        self.assertEqual(out, f"{_SUPABASE_HOST}/audio/charisma_snippets/u/clip.webm?token=x")

    def test_a_dead_signer_falls_through_to_supabase_not_to_a_bare_key(self):
        out = self._resolve({"audio_segment_path": None,
                             "storage_path": "session_recordings/s/full.webm"},
                            signer=False)
        self.assertEqual(out, f"{_SUPABASE_HOST}/audio/session_recordings/s/full.webm?token=x")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
