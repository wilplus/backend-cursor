"""
STORY    As a speaker, I want every stored recording of my voice served only
         through a fresh signed link, so that my voice is never reachable on
         a permanent public URL.
OUTCOME
  O1  Every object-key prefix the services and routes write is classified,
      as user content or deliberately not.
  O2  A user-content key gets no public URL; a non-user key still does.
PROVES   O1 -> test_every_written_prefix_is_classified,
               test_the_voice_and_coach_answer_prefixes_sign
         O2 -> test_the_audio_bucket_no_longer_hands_it_a_public_url
WHY      P1 / DPIA RISK-11: casual_voice/ sat outside the list and got
         permanent public URLs. O1 reads SOURCE TEXT: it finds key prefixes
         as written in f-strings (f"prefix/{...}") and prefix constants.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from services.user_content_keys import CLASSIFIED_PREFIXES, USER_CONTENT_PREFIXES

ROOT = Path(__file__).resolve().parents[1]
_F_STRING_KEY = re.compile(r"""\bf["']([a-z0-9][a-z0-9_\-]*/)\{""")
_PREFIX_CONSTANT = re.compile(
    r"""^\s*(?:[A-Z_]*KEY_PREFIX|[a-z_]*storage_prefix)\s*(?::[^=\n]*)?="""
    r"""\s*["']([a-z0-9][a-z0-9_\-]*?)/?["']""", re.M)



def _written_prefixes() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for top in ("services", "routes"):
        for path in (ROOT / top).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for pattern in (_F_STRING_KEY, _PREFIX_CONSTANT):
                for match in pattern.finditer(text):
                    prefix = match.group(1).rstrip("/") + "/"
                    found.setdefault(prefix, set()).add(
                        str(path.relative_to(ROOT)))
    return found


def test_every_written_prefix_is_classified():
    found = _written_prefixes()
    # The scan must see the writers it is known to cover, or it proves nothing.
    assert {"willab_lab/", "charisma_snippets/", "willab_presentations/",
            "session_recordings/", "pair-releases/"} <= set(found)
    unclassified = {
        prefix: sorted(paths) for prefix, paths in found.items()
        if not prefix.startswith(CLASSIFIED_PREFIXES)
    }
    assert unclassified == {}, (
        "classify these in services/user_content_keys.py")


@pytest.mark.parametrize("prefix", ["ai-voice/", "coach-answers/"])
def test_the_voice_and_coach_answer_prefixes_sign(prefix):
    # Classified 2026-10-20 (founder): the speaker's cloned voice and a
    # coach's answer filed under the speaker are user content, so signed.
    assert prefix in _written_prefixes()
    assert prefix.startswith(USER_CONTENT_PREFIXES)


class TestRetainedUserVoiceSigns:

    def test_the_audio_bucket_no_longer_hands_it_a_public_url(self, monkeypatch):
        from services import audio_storage

        class _Cfg:
            R2_AUDIO_PUBLIC_BASE_URL = "https://public.example"

        monkeypatch.setattr(audio_storage, "_config", lambda: _Cfg())

        for prefix in USER_CONTENT_PREFIXES:
            assert audio_storage.audio_public_url(f"{prefix}u/r.webm") is None
        # Something genuinely not user content still takes the public path,
        # or this change would be an outage rather than a fix.
        assert audio_storage.audio_public_url(
            "journal/audio/x.webm") == "https://public.example/journal/audio/x.webm"
