"""willab — a stored deck URL that expired is repaired on READ.

REPORTED FROM REAL USE 2026-09-16: "slide preview is unavailable again."

A deck's URL is written once, at upload, and read forever after. The writer
prefers the permanent public URL and falls back to a presigned GET with a
SEVEN-DAY life; before ``R2_PUBLIC_BASE_URL`` was configured the fallback was
the only branch. Nothing re-signs it, so those decks went dark a week later
and stayed dark — and setting the variable afterwards fixed new uploads while
doing nothing at all for the rows already written.

The Ideal Text read is where it bites hardest: it serves "the FIRST non-null
presentation_ref across takes in take order", so it serves the OLDEST stored
URL — the one most likely to predate the config.

Run: python3 -m unittest tests.test_refreshed_media_url
"""
from __future__ import annotations

import contextlib
import unittest

import services.coach_video_storage as storage
from services.coach_video_storage import refreshed_media_url

PUBLIC = "https://pub-62a94c47b9a741d8b5b4bea704f13447.r2.dev"
KEY = "willab_presentations/2f8c1d9e4a7b.pdf"
PRESIGNED = (
    "https://acct123.r2.cloudflarestorage.com/willab-media/"
    + KEY
    + "?X-Amz-Algorithm=AWS4-HMAC-SHA256"
    "&X-Amz-Credential=abc%2F20260909%2Fauto%2Fs3%2Faws4_request"
    "&X-Amz-Date=20260909T101500Z&X-Amz-Expires=604800"
    "&X-Amz-SignedHeaders=host&X-Amz-Signature=deadbeef"
)


class _StubConfig:
    """The three attributes this helper reads, and nothing else."""

    def __init__(self, public_base: str, bucket: str):
        self.R2_PUBLIC_BASE_URL = public_base
        self.R2_BUCKET_NAME = bucket
        self.COACH_FEEDBACK_VIDEO_BUCKET = bucket


@contextlib.contextmanager
def _with_config(**over):
    """Install the config the helper reads, and put back what was there.

    THE CACHED INSTANCE, not the Config CLASS. `_config()` memoises into
    `storage._cfg` and only imports `config.Config` when that is empty, so
    patching the class is a bet on nobody else in the suite having warmed the
    cache or swapped the module first — which is exactly how these two tests
    passed alone and failed in the full run. Writing the cache directly is the
    same thing the code reads, in every order.
    """
    settings = {"public_base": PUBLIC, "bucket": "willab-media"}
    settings.update(over)
    previous = storage._cfg
    storage._cfg = _StubConfig(**settings)
    try:
        yield
    finally:
        storage._cfg = previous


class RefreshedMediaUrlTests(unittest.TestCase):
    def test_repairs_an_expiring_presigned_deck_url(self):
        """THE BUG: the seven-day link becomes the permanent one."""
        with _with_config():
            self.assertEqual(refreshed_media_url(PRESIGNED), f"{PUBLIC}/{KEY}")

    def test_leaves_an_already_public_url_untouched(self):
        already = f"{PUBLIC}/{KEY}"
        with _with_config():
            self.assertEqual(refreshed_media_url(already), already)

    def test_strips_the_bucket_segment_but_only_when_it_is_one(self):
        """Path-style S3 URLs carry /<bucket>/<key>; a KEY that merely starts
        with the same letters must not be trimmed."""
        tricky_key = "willab-media-archive/deck.pdf"
        url = (
            "https://acct123.r2.cloudflarestorage.com/willab-media/"
            + tricky_key
            + "?X-Amz-Signature=abc"
        )
        with _with_config():
            self.assertEqual(refreshed_media_url(url), f"{PUBLIC}/{tricky_key}")

    def test_leaves_a_supabase_signed_url_alone(self):
        """A different signer, a different shape — not this function's claim."""
        supa = (
            "https://proj.supabase.co/storage/v1/object/sign/decks/"
            "a/b.pdf?token=eyJhbGciOi"
        )
        with _with_config():
            self.assertEqual(refreshed_media_url(supa), supa)

    def test_returns_the_original_when_no_public_base_is_configured(self):
        """Never invent a URL. Without a base there is nothing to re-point to,
        and the expiring link is still better than None."""
        with _with_config(public_base=""):
            self.assertEqual(refreshed_media_url(PRESIGNED), PRESIGNED)

    def test_passes_through_what_it_cannot_read(self):
        with _with_config():
            for value in (None, "", "   ", "not a url", "/relative/deck.pdf"):
                self.assertEqual(refreshed_media_url(value), value)

    def test_a_presigned_url_with_no_path_is_left_alone(self):
        with _with_config():
            url = "https://acct123.r2.cloudflarestorage.com/?X-Amz-Signature=a"
            self.assertEqual(refreshed_media_url(url), url)

    def test_is_idempotent(self):
        """Repairing twice is repairing once — the read runs on every request."""
        with _with_config():
            once = refreshed_media_url(PRESIGNED)
            self.assertEqual(refreshed_media_url(once), once)


class ServedEverywhereTests(unittest.TestCase):
    """The repair belongs on every surface that SERVES a stored ref.

    The Ideal Text deck is the one that was reported, but the same stale row
    reaches the recording stage's setup read, the coach's review payload and
    the account's last-setup read. Fixing one would have left the same deck
    blank on the next screen along.

    The upload response in lab_recording.py is deliberately NOT in this list:
    its ref has just been minted by `_store_presentation_pdf`, which already
    prefers the public URL.
    """

    def test_every_read_that_serves_a_stored_ref_repairs_it(self):
        import re

        for path in (
            "routes/v2/explore_ideal_text.py",
            "routes/v2/arcs.py",
            "routes/v2/coach.py",
            "routes/v2/user_account.py",
        ):
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            served = re.findall(r'"presentation_ref":([^\n]*)', src)
            self.assertTrue(served, f"{path} no longer serves presentation_ref")
            for expr in served:
                self.assertIn(
                    "refreshed_media_url", expr,
                    f"{path} serves a stored ref without repairing it: {expr!r}",
                )


if __name__ == "__main__":
    unittest.main()
