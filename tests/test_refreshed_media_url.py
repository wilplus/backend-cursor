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

─────────────────────────────────────────────────────────────────────────────
⚠️ 2026-09-18 — THE CONTRACT INVERTED, AND THE DIAGNOSIS ABOVE WAS HALF RIGHT

The fix recorded above was "make the URL permanent". It worked, and it was the
wrong cure: it treated the TTL as the fault. The fault was DEPENDING ON A
STORED URL AT ALL. A permanent URL is simply one that cannot expire because it
has no protection left — which is how decks ended up reachable by anyone
holding the link, forever (DPIA RISK-11).

So the direction reversed. A deck ref is now re-signed FRESH on every read,
from the object KEY recovered out of whatever shape the ref was written in.
The original bug stays fixed — more completely than before, because nothing
depends on any stored URL remaining valid — and the deck stops being public.

The tests below that assert "becomes the permanent one" were rewritten rather
than deleted, so the inversion is visible in this file's history instead of
looking like the September fix was simply thrown away.
─────────────────────────────────────────────────────────────────────────────

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
    previous_signer = storage.presigned_get_coach_object
    storage._cfg = _StubConfig(**settings)
    # Stub the signer rather than letting boto3 mint a real signature: what
    # these tests assert is WHICH branch ran, not what a signature looks like.
    storage.presigned_get_coach_object = (
        lambda bucket, key, expires_in=0, **kw: f"{FRESH}#{key}"
    )
    try:
        yield
    finally:
        storage._cfg = previous
        storage.presigned_get_coach_object = previous_signer


#: What the stub signer returns, so a test can say "this was signed now".
FRESH = "https://acct123.r2.cloudflarestorage.com/signed-just-now"


class RefreshedMediaUrlTests(unittest.TestCase):
    def test_an_expiring_presigned_deck_url_is_re_signed_fresh(self):
        """THE BUG, and its second diagnosis.

        Until 2026-09-18 this asserted that the seven-day link becomes the
        PERMANENT one. It now asserts a fresh signature: the stored URL is
        only ever read for its key. The deck still cannot go dark — and it is
        no longer world-readable to do it."""
        with _with_config():
            self.assertEqual(refreshed_media_url(PRESIGNED), f"{FRESH}#{KEY}")

    def test_a_long_dead_signature_still_yields_a_working_deck(self):
        """The regression that matters. Expiry is now structurally impossible
        for decks, because nothing depends on the stored URL being valid."""
        dead = PRESIGNED.replace("deadbeef", "expired-months-ago")
        with _with_config():
            self.assertEqual(refreshed_media_url(dead), f"{FRESH}#{KEY}")

    def test_an_already_public_deck_url_is_signed_rather_than_passed_through(self):
        """Inverted 2026-09-18. These are the rows written while decks were
        served publicly; re-signing them on read is what covers the existing
        estate without a backfill."""
        with _with_config():
            self.assertEqual(
                refreshed_media_url(f"{PUBLIC}/{KEY}"), f"{FRESH}#{KEY}")

    def test_strips_the_bucket_segment_but_only_when_it_is_one(self):
        """Path-style S3 URLs carry /<bucket>/<key>; a KEY that merely starts
        with the same letters must not be trimmed."""
        tricky_key = "willab-media-archive/deck.pdf"
        url = (
            "https://acct123.r2.cloudflarestorage.com/willab-media/"
            + tricky_key
            + "?X-Amz-Signature=abc"
        )
        # Signed since decision 4 (2026-09-25); the key it signs is the check.
        with _with_config():
            self.assertEqual(refreshed_media_url(url), f"{FRESH}#{tricky_key}")

    def test_leaves_a_supabase_signed_url_alone(self):
        """A different signer, a different shape — not this function's claim."""
        supa = (
            "https://proj.supabase.co/storage/v1/object/sign/decks/"
            "a/b.pdf?token=eyJhbGciOi"
        )
        with _with_config():
            self.assertEqual(refreshed_media_url(supa), supa)

    def test_a_deck_is_signed_even_with_no_public_base_configured(self):
        """Rewritten 2026-09-18. This used to assert that an unconfigured
        public base leaves the expiring link alone, because there was nothing
        to re-point to. Signing needs no public base at all — it works on any
        bucket in the account — so the deck is now recoverable in exactly the
        environment where it used to be least recoverable."""
        with _with_config(public_base=""):
            self.assertEqual(refreshed_media_url(PRESIGNED), f"{FRESH}#{KEY}")

    def test_non_user_content_is_signed_fresh_with_no_public_base(self):
        """Founder 2026-09-25, decision 4. The other half of the split used
        to need a public base to be repaired, and kept an expiring link
        without one. With the buckets private it signs from the key like user
        content — no public base needed, and still no URL invented."""
        coach_url = (
            "https://acct123.r2.cloudflarestorage.com/willab-media/"
            "coach-feedback/a.webm?X-Amz-Signature=deadbeef"
        )
        with _with_config(public_base=""):
            self.assertEqual(refreshed_media_url(coach_url), f"{FRESH}#coach-feedback/a.webm")

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

    def test_every_other_stored_media_ref_it_serves_is_signed(self):
        """Founder 2026-09-25, decision 4: the buckets go private, so a stored
        ref served raw stops playing. These read sites served one raw: the
        coach's feedback video (coach review, a de-duplicated re-upload, and
        the speaker's readout), the readout's deck (two keys), and the
        Trainings-page cover."""
        import re

        for path, field in (
            ("routes/v2/coach.py", '"video_ref"'),
            ("services/lab_recording.py", '"video_ref"'),
            ("services/readout_context.py", '"presentation_ref"'),
            ("services/readout_context.py", 'result["presentation_ref"]'),
            ("routes/v2/user_sessions.py", '"cover_ref"'),
        ):
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            served = re.findall(re.escape(field) + r'\s*[:=]\s*\(?([^\n]*)', src)
            self.assertTrue(served, f"{path} no longer serves {field}")
            for expr in served:
                if expr.startswith(("None", "video_ref", "{")):
                    continue
                self.assertIn("refreshed_media_url", expr,
                              f"{path} serves {field} without signing it: {expr!r}")


if __name__ == "__main__":
    unittest.main()
