"""Every object key this codebase writes is classified before it ships.

P1 / DPIA RISK-11. `services/user_content_keys.py` decides which stored objects
may be handed out on a permanent, unauthenticated bucket URL and which must be
signed fresh on every read. Its own rule is FAIL TOWARD SIGNING — "an unknown
prefix that should have been listed here stays public, which is the exposure".

That rule only works if an unknown prefix is ever noticed. One was not:
`casual_voice_analytics` writes `casual_voice/<user>/<row>.webm` through
`put_audio_bytes` into the same bucket as `session_recordings/`, and
`audio_public_url`'s docstring asserted the bucket held only the two prefixes
the list already named. A third prefix of retained user voice sat outside the
question entirely and got permanent public URLs.

So this test asks the question the list could not: it finds every object-key
prefix the services layer constructs and fails if one is classified neither way.
Adding a prefix to `NON_USER_CONTENT_PREFIXES` is a deliberate, reviewable act
with a reason beside it; forgetting is not an option the test leaves open.
"""
from __future__ import annotations


class TestRetainedUserVoiceSigns:


    def test_the_audio_bucket_no_longer_hands_it_a_public_url(self, monkeypatch):
        from services import audio_storage

        class _Cfg:
            R2_AUDIO_PUBLIC_BASE_URL = "https://public.example"

        monkeypatch.setattr(audio_storage, "_config", lambda: _Cfg())

        assert audio_storage.audio_public_url("casual_voice/u/r.webm") is None
        assert audio_storage.audio_public_url("session_recordings/u/r.webm") is None
        # Something genuinely not user content still takes the public path,
        # or this change would be an outage rather than a fix.
        assert audio_storage.audio_public_url(
            "journal/audio/x.webm") == "https://public.example/journal/audio/x.webm"
