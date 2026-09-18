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
from services.user_content_keys import is_user_content_key

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


class ThePredicate(unittest.TestCase):
    """The one list all three storage modules share."""

    def test_every_user_recording_prefix_is_user_content(self):
        for key in (
            "session_recordings/abc/full.webm",
            "guest_funnel/abc/turn_1.webm",
            "willab_lab/abc/recording_ff.webm",
            "charisma_snippets/abc/x_snippet.webm",
            "snippets/abc/x.webm",
        ):
            self.assertTrue(is_user_content_key(key), key)

    def test_an_uploaded_deck_is_user_content(self):
        """Added 2026-09-18, a day after the rest. Decks are the prefix the
        permanent public URL was introduced FOR — they went dark for a week in
        September when they carried a 7-day signature nothing re-signed. They
        are only safe to sign once the read path mints a FRESH signature from
        the key every time, which refreshed_media_url now does."""
        self.assertTrue(is_user_content_key("willab_presentations/abc.pdf"))

    def test_coach_authored_media_is_not(self):
        """The split is still load bearing: the coach's own material on
        surfaces that already gate access keeps the public path."""
        for key in (
            "coach-feedback/abc.webm",
            "copilot/abc.mp4",
            "coach-snippet-breakthrough/abc.webm",
            "mlc2/abc.webm",
        ):
            self.assertFalse(is_user_content_key(key), key)

    def test_a_leading_slash_does_not_defeat_it(self):
        """Callers disagree about leading slashes. A prefix check that can be
        defeated by one is not a control."""
        self.assertTrue(is_user_content_key("/session_recordings/a/full.webm"))

    def test_a_key_that_merely_starts_with_the_same_letters_is_not_matched(self):
        self.assertFalse(is_user_content_key("snippets_archive/a.webm"))
        self.assertFalse(is_user_content_key("willab_lab_notes/a.txt"))

    def test_junk_is_false_rather_than_raising(self):
        """A missing key cannot be user content, and raising here would turn a
        cosmetic read into a 500."""
        for value in (None, "", "   ", 42, b"session_recordings/a", object()):
            self.assertFalse(is_user_content_key(value), repr(value))


class TheMintingFunctions(unittest.TestCase):
    """All three refuse to build a public URL for user content, and all three
    still build one for everything else."""

    def _run(self, fn, key, **cfg):
        # Each storage module caches a Config INSTANCE in a module global.
        # Patching the class does nothing if a previous test already
        # populated that cache, which is why this suite passed alone and
        # failed in the full run. Clear the caches so the patched class is
        # what gets read, and restore them so we do not leak into the next
        # test the same way.
        from services import audio_storage, coach_video_storage, lab_audio_storage

        modules = (coach_video_storage, audio_storage, lab_audio_storage)
        saved = [getattr(m, "_cfg", None) for m in modules]
        patches = _cfg(**cfg)
        for p in patches:
            p.start()
        for m in modules:
            m._cfg = None
        try:
            return fn(key)
        finally:
            for p in patches:
                p.stop()
            for m, previous in zip(modules, saved):
                m._cfg = previous

    def test_coach_media_public_url_refuses_user_content(self):
        from services.coach_video_storage import coach_media_public_url
        self.assertIsNone(self._run(
            coach_media_public_url, "charisma_snippets/s/1_snippet.webm"))

    def test_coach_media_public_url_refuses_a_deck(self):
        from services.coach_video_storage import coach_media_public_url
        self.assertIsNone(self._run(
            coach_media_public_url, "willab_presentations/a.pdf"))

    def test_coach_media_public_url_still_serves_coach_authored_media(self):
        from services.coach_video_storage import coach_media_public_url
        self.assertEqual(
            self._run(coach_media_public_url, "coach-feedback/a.webm"),
            f"{_COACH_BASE}/coach-feedback/a.webm",
        )

    def test_audio_public_url_refuses_a_session_recording(self):
        from services.audio_storage import audio_public_url
        self.assertIsNone(self._run(
            audio_public_url, "session_recordings/s/full.webm"))

    def test_audio_public_url_refuses_guest_funnel_audio(self):
        """Pre-account audio is still a recording of a person speaking."""
        from services.audio_storage import audio_public_url
        self.assertIsNone(self._run(
            audio_public_url, "guest_funnel/s/turn_1.webm"))

    def test_lab_audio_public_url_refuses_an_uploaded_take(self):
        from services.lab_audio_storage import lab_audio_public_url
        self.assertIsNone(self._run(
            lab_audio_public_url, "willab_lab/s/recording_ff.webm"))


class TheDeckReadPath(unittest.TestCase):
    """`refreshed_media_url` serves presentation_ref on four surfaces. It used
    to turn a stored signature INTO a permanent public URL; it now goes the
    other way for user content, and re-mints from the key on every read so no
    stored URL has to stay valid. That is what makes signing decks safe after
    the 2026-09-16 blackout — the TTL was blamed, but the cause was depending
    on a stored URL at all."""

    def _refresh(self, ref, *, signed=_SIGNED):
        from services import coach_video_storage as cvs

        saved = getattr(cvs, "_cfg", None)
        patches = _cfg()
        for p in patches:
            p.start()
        cvs._cfg = None
        patches.append(patch.object(
            cvs, "presigned_get_coach_object",
            lambda bucket, key, expires_in=0, **kw: signed))
        patches[-1].start()
        try:
            return cvs.refreshed_media_url(ref)
        finally:
            for p in patches:
                p.stop()
            cvs._cfg = saved

    def test_a_stored_public_deck_url_comes_back_signed(self):
        """The rows already in the table. No backfill — they are re-addressed
        on read."""
        out = self._refresh(f"{_COACH_BASE}/willab_presentations/a.pdf")
        self.assertEqual(out, _SIGNED)

    def test_a_stored_presigned_deck_url_is_re_signed_not_publicised(self):
        """This is the exact inversion. The old code took this ref and handed
        back a permanent public URL."""
        out = self._refresh(
            "https://acct.r2.cloudflarestorage.com/coach-feedback-videos/"
            "willab_presentations/a.pdf?X-Amz-Signature=old")
        self.assertEqual(out, _SIGNED)

    def test_an_expired_signature_cannot_strand_a_deck(self):
        """The regression that matters. A week-old stored signature is only
        ever used to recover the KEY; what comes back is minted now. So a deck
        cannot go dark because its stored URL aged, which is what happened in
        September."""
        stale = ("https://acct.r2.cloudflarestorage.com/coach-feedback-videos/"
                 "willab_presentations/a.pdf?X-Amz-Signature=expired-weeks-ago")
        self.assertEqual(self._refresh(stale, signed="FRESH"), "FRESH")

    def test_coach_authored_media_still_gets_the_permanent_public_url(self):
        """The other half of the split must not move."""
        out = self._refresh(
            "https://acct.r2.cloudflarestorage.com/coach-feedback-videos/"
            "coach-feedback/a.webm?X-Amz-Signature=old")
        self.assertEqual(out, f"{_COACH_BASE}/coach-feedback/a.webm")

    def test_a_foreign_url_is_left_alone(self):
        ref = "https://example.org/somebody-elses/deck.pdf"
        self.assertEqual(self._refresh(ref), ref)

    def test_junk_survives_unchanged(self):
        for value in (None, "", 42):
            self.assertEqual(self._refresh(value), value)


class TheKeyExtractor(unittest.TestCase):
    """Four ref shapes written by different code in different months."""

    def _key(self, ref):
        from services import coach_video_storage as cvs

        saved = getattr(cvs, "_cfg", None)
        patches = _cfg()
        for p in patches:
            p.start()
        cvs._cfg = None
        try:
            return cvs.media_key_from_ref(ref)
        finally:
            for p in patches:
                p.stop()
            cvs._cfg = saved

    def test_a_presigned_url_loses_its_bucket_segment(self):
        self.assertEqual(
            self._key("https://acct.r2.cloudflarestorage.com/"
                      "coach-feedback-videos/willab_presentations/a.pdf"
                      "?X-Amz-Signature=x"),
            "willab_presentations/a.pdf")

    def test_a_public_url_on_our_base(self):
        self.assertEqual(
            self._key(f"{_COACH_BASE}/willab_presentations/a.pdf"),
            "willab_presentations/a.pdf")

    def test_an_s3_marker(self):
        self.assertEqual(
            self._key("s3://coach-feedback-videos/willab_presentations/a.pdf"),
            "willab_presentations/a.pdf")

    def test_a_bare_key(self):
        self.assertEqual(
            self._key("willab_presentations/a.pdf"),
            "willab_presentations/a.pdf")

    def test_a_foreign_url_is_not_ours_to_re_address(self):
        """Imports store other people's URLs. Guessing a key out of one and
        signing it against our bucket breaks a working ref."""
        self.assertIsNone(self._key("https://example.org/a/deck.pdf"))

    def test_a_key_that_merely_starts_like_the_bucket_keeps_its_prefix(self):
        self.assertEqual(
            self._key("https://acct.r2.cloudflarestorage.com/"
                      "coach-feedback-videos-archive/a.pdf?X-Amz-Signature=x"),
            "coach-feedback-videos-archive/a.pdf")


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

    def test_path_a_pre_finalize_public_url_in_audio_segment_path(self):
        """Per-turn .webm, storage_path still NULL. The stored value is a full
        public URL on our own audio base — exactly the rows already in the
        table. It must come back SIGNED, which is what fixes the existing
        estate without a backfill."""
        out = self._resolve({
            "audio_segment_path": f"{_AUDIO_BASE}/guest_funnel/s/turn_1.webm",
            "storage_path": None,
        })
        self.assertEqual(out, _SIGNED)
        self.assertNotIn("pub-", out)

    def test_path_a_post_finalize_storage_path_wins_and_is_signed(self):
        """Once finalize populates storage_path it must win, because the
        offsets are relative to the concatenated file. It is a bare key and
        must be signed, never publicised."""
        out = self._resolve({
            "audio_segment_path": f"{_AUDIO_BASE}/guest_funnel/s/turn_1.webm",
            "storage_path": "session_recordings/s/full.webm",
        })
        self.assertEqual(out, _SIGNED)

    def test_path_b_extracted_snippet_full_url_is_signed(self):
        """extract_recording_snippets writes a full URL and leaves
        storage_path NULL."""
        out = self._resolve({
            "audio_segment_path":
                f"{_COACH_BASE}/charisma_snippets/s/1_snippet.webm",
            "storage_path": None,
        })
        self.assertEqual(out, _SIGNED)

    def test_path_c_supabase_snippet_still_uses_the_supabase_signer(self):
        """Student uploads live in Supabase Storage, not R2. The generator was
        deleted in August but its rows still read through here, and signing
        them against R2 would 404 every one. Behaviour must be unchanged."""
        out = self._resolve({
            "audio_segment_path": None,
            "storage_path": "charisma_snippets/some-uuid",
        })
        self.assertEqual(out, "SUPABASE_SIGNED")

    def test_an_s3_marker_ref_still_resolves(self):
        """The CONFIG-FIRST fallback shape. A service without the public base
        writes ``s3://bucket/key``; that path predates this change and must
        keep working."""
        out = self._resolve({
            "audio_segment_path": "s3://user-interview-audio/willab_lab/s/r.webm",
            "storage_path": None,
        })
        self.assertEqual(out, _SIGNED)

    def test_a_dead_signer_falls_through_to_supabase_not_to_a_bare_key(self):
        """The resolver returns its INPUT when it cannot sign — deliberate
        there, useless here, because a bare key is not playable in an
        <audio src>. It must reach the Supabase path instead."""
        out = self._resolve({
            "audio_segment_path": None,
            "storage_path": "session_recordings/s/full.webm",
        }, signed=None)
        self.assertEqual(out, "SUPABASE_SIGNED")

    def test_nothing_playable_is_still_none(self):
        self.assertIsNone(self._resolve(
            {"audio_segment_path": None, "storage_path": None}))


class TheAdminTurnAudioPath(unittest.TestCase):
    """The admin surface had the same hole, plus one of its own: it returned
    the stored ref RAW, so every pre-existing public URL was served unchanged."""

    def _resolve(self, snippet, *, signed=_SIGNED):
        from routes.v2 import admin as admin_mod

        fn = getattr(admin_mod, "_resolve_turn_audio_url", None)
        if fn is None:  # pragma: no cover - name drift guard
            self.skipTest("admin turn-audio resolver not found by name")
        patches = _cfg()
        patches.append(patch(
            "services.coach_video_storage.presigned_get_coach_object",
            lambda bucket, key, expires_in=0, **kw: signed))
        patches.append(patch.object(
            admin_mod.db, "create_signed_url",
            lambda *a, **kw: "SUPABASE_SIGNED", create=True))
        for p in patches:
            p.start()
        try:
            return fn(snippet)
        finally:
            for p in patches:
                p.stop()

    def test_a_stored_public_url_is_resigned_not_passed_through(self):
        out = self._resolve({
            "audio_segment_path":
                f"{_AUDIO_BASE}/session_recordings/s/full.webm",
        })
        self.assertEqual(out, _SIGNED)

    def test_a_foreign_https_ref_still_passes_through(self):
        """Imports store external URLs. Re-signing one against our bucket
        would break it."""
        ref = "https://example.org/somebody-elses/clip.webm"
        self.assertEqual(self._resolve({"audio_segment_path": ref}), ref)


class NoReadPathMintsAPublicUrlForUserContent(unittest.TestCase):
    """Structural guard. Fixing call sites one Sentry issue at a time is how
    the next one is missed — the same reason tests/test_coach_bucket_literals.py
    exists. A new route that reaches for the public minting function instead of
    the resolver fails here rather than in production."""

    def test_the_service_signs_and_the_routes_delegate_to_it(self):
        from pathlib import Path

        service = Path("services/snippet_audio_url.py").read_text(encoding="utf-8")
        self.assertIn("resolve_playable_ref", service)

        for path in (Path("routes/v2/common.py"), Path("routes/v2/admin.py")):
            text = path.read_text(encoding="utf-8")
            self.assertIn(
                "services.snippet_audio_url", text,
                f"{path} must delegate to the one storage decision, not carry "
                "its own copy",
            )

    def test_no_route_and_not_the_service_mints_a_public_audio_url(self):
        from pathlib import Path

        # Assert on CODE, not on the word. These files name audio_public_url
        # in comments saying why they no longer call it, and a test that
        # cannot tell prose from a call site fails on an explanation — which
        # teaches the next person to delete the explanation.
        offenders = []
        for path in (Path("routes/v2/common.py"), Path("routes/v2/admin.py"),
                     Path("services/snippet_audio_url.py")):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "audio_public_url" in line and not line.lstrip().startswith("#"):
                    offenders.append(f"{path}:{n}")
        self.assertEqual(
            offenders, [],
            "mints a public audio URL; use the resolver so user content is "
            "signed: " + ", ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
