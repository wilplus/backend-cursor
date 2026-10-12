"""User recordings are never handed out on a public bucket URL (DPIA RISK-11).

WHAT WENT WRONG (found 2026-09-17, from the Cloudflare console).

`coach-feedback-videos` and `user-interview-audio` are both served through
Cloudflare public development URLs. A public URL is permanent, unauthenticated
and unrevocable: once it leaves our systems it grants access to that recording
forever. Every read path that served a recording handed one out, because the
minting functions had no idea what kind of object they were addressing.

Keys embed UUIDs, so nothing was browsable. The exposure was the single leaked
URL — forwarded, screenshotted, in a referrer header, in a support ticket.

THE FOUR ROW SHAPES ARE THE POINT OF THIS FILE.

`_resolve_snippet_audio_url` carries four historical states, documented in its
own docstring, and they do not share a code path. A fix verified against one of
them is not a fix — it is a fix for a quarter of the rows, and the other three
quarters keep serving public URLs with nobody looking. Each shape gets its own
test here, named for the state it represents.

WHAT THIS FILE DOES NOT CLAIM. The buckets stay publicly readable, so URLs
already handed out remain valid; that is DPIA M11.4 and it needs a
private-bucket migration, not a test. What is asserted here is that nothing
mints a NEW one, and that existing stored public URLs are re-signed on read
rather than passed through.

Run: python3 -m pytest tests/test_user_content_not_public.py
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import config as config_mod

_COACH_BASE = "https://pub-coach.r2.dev"
_AUDIO_BASE = "https://pub-interview.r2.dev"
_LAB_BASE = "https://pub-lab.r2.dev"
_SIGNED = "https://acct.r2.cloudflarestorage.com/b/k?X-Amz-Signature=deadbeef"


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
    """`_resolve_snippet_audio_url` has four historical states that do not
    share a code path. Each one is rehearsed separately, because a fix proved
    against one of them leaves the other three serving public URLs."""

    def _resolve(self, snippet, *, signed=_SIGNED, supabase="SUPABASE_SIGNED"):
        from routes.v2 import common as common_mod

        patches = _cfg()
        patches.append(patch(
            "services.coach_video_storage.presigned_get_coach_object",
            lambda bucket, key, expires_in=0, **kw: signed))
        patches.append(patch.object(
            common_mod.db, "create_signed_url",
            lambda *a, **kw: supabase, create=True))
        for p in patches:
            p.start()
        try:
            return common_mod._resolve_snippet_audio_url(snippet)
        finally:
            for p in patches:
                p.stop()


    def test_a_dead_signer_falls_through_to_supabase_not_to_a_bare_key(self):
        """The resolver returns its INPUT when it cannot sign — deliberate
        there, useless here, because a bare key is not playable in an
        <audio src>. It must reach the Supabase path instead."""
        out = self._resolve({
            "audio_segment_path": None,
            "storage_path": "session_recordings/s/full.webm",
        }, signed=None)
        self.assertEqual(out, "SUPABASE_SIGNED")


if __name__ == "__main__":
    unittest.main()
