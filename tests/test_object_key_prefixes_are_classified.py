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

import pathlib
import re

from services.user_content_keys import (
    CLASSIFIED_PREFIXES,
    NON_USER_CONTENT_PREFIXES,
    USER_CONTENT_PREFIXES,
    is_user_content_key,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVICES = ROOT / "services"

#: An object key built from a literal prefix: `f"prefix/{...}"` or
#: `"prefix/%s"`. Deliberately narrow — it matches the shape every current key
#: writer uses, and a shape it cannot see is a shape to add here, not to ignore.
_KEY_LITERAL = re.compile(
    r"""f?["']([a-z][a-z0-9_-]*)/(?:\{|%s|<)""",
)

#: Prefixes that appear in key-shaped literals but never address a stored
#: object, with the reason each is exempt.
_NOT_OBJECT_KEYS = {
    "http",         # URLs
    "https",
    "v1", "v2",     # route paths
    "api",
    "admin",
    "user",
    "coach",
    "internal",
    "static",
    "tmp",
    "var",
    "opt",
    "usr",
    "home",
    "dev",
    "proc",
    "etc",
}


def _discovered_prefixes() -> dict[str, list[str]]:
    """prefix -> the files that build a key with it."""
    found: dict[str, list[str]] = {}
    for path in sorted(SERVICES.rglob("*.py")):
        source = path.read_text(encoding="utf-8", errors="replace")
        # Comments and docstrings discuss prefixes constantly — including this
        # module's own list. Only code counts.
        code = re.sub(r"#[^\n]*", "", source)
        code = re.sub(r'"""[\s\S]*?"""', "", code)
        code = re.sub(r"'''[\s\S]*?'''", "", code)
        for match in _KEY_LITERAL.finditer(code):
            prefix = match.group(1)
            if prefix in _NOT_OBJECT_KEYS:
                continue
            found.setdefault(prefix + "/", []).append(path.name)
    return found


class TestNoPrefixShipsUnclassified:

    def test_every_key_prefix_is_user_content_or_explicitly_not(self):
        """The named regression test for P1.

        Fails today if `casual_voice/` is removed from the list again, and
        fails tomorrow for whatever the next one is.
        """
        unclassified = {
            prefix: sorted(set(files))
            for prefix, files in _discovered_prefixes().items()
            if prefix not in CLASSIFIED_PREFIXES
        }

        assert unclassified == {}, (
            "an object-key prefix is neither user content nor explicitly "
            "exempt, so it silently gets a permanent public URL: "
            f"{unclassified}. Add it to USER_CONTENT_PREFIXES, or to "
            "NON_USER_CONTENT_PREFIXES with the reason it is safe."
        )

    def test_the_scanner_can_actually_see_the_known_writers(self):
        """A scanner that found nothing would pass the case above forever."""
        found = _discovered_prefixes()

        for expected in ("willab_lab/", "charisma_snippets/", "casual_voice/",
                         "journal/"):
            assert expected in found, (
                f"the scanner no longer sees {expected} being written — the "
                "regex has drifted from how keys are built, and the case "
                "above is now vacuous"
            )


class TestRetainedUserVoiceSigns:

    def test_casual_voice_is_user_content(self):
        """`casual_voice/<user>/<row>.webm` is a retained recording of a person
        speaking, written into the same bucket as `session_recordings/`."""
        assert is_user_content_key(
            "casual_voice/11111111-1111-1111-1111-111111111111/abc.webm"
        )

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

    def test_the_fourth_storage_module_asks_the_same_question(self, monkeypatch):
        """`user_media_storage` minted public URLs without consulting the list
        at all — the module docstring said three modules and there were four."""
        from services import user_media_storage

        class _Cfg:
            R2_USER_MEDIA_PUBLIC_BASE_URL = "https://media.example"

        monkeypatch.setattr(user_media_storage, "_config", lambda: _Cfg())

        assert user_media_storage.user_media_public_url(
            "session_recordings/u/r.webm") is None
        assert user_media_storage.user_media_public_url(
            "coach-feedback/x.mp4") == "https://media.example/coach-feedback/x.mp4"


class TestTheTwoListsStaySeparate:

    def test_no_prefix_is_in_both(self):
        overlap = set(USER_CONTENT_PREFIXES) & set(NON_USER_CONTENT_PREFIXES)
        assert overlap == set(), f"a prefix is classified both ways: {overlap}"

    def test_every_listed_prefix_ends_in_a_slash(self):
        """`startswith` on a prefix without one would match `snippets_backup/`
        as if it were `snippets/`."""
        bad = [p for p in CLASSIFIED_PREFIXES if not p.endswith("/")]
        assert bad == [], f"prefix without a trailing slash: {bad}"
