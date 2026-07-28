"""willab — generated Journal cover images (founder 2026-07-28).

Pinned here, token by token:
  I-1  the brief: house style + essay reach the model; a STEER is applied to
       the PREVIOUS brief (refine, not restart) and a note-less regenerate
       explicitly asks for a different scene.
  I-2  degradation: no text model ⇒ a deterministic fallback brief that still
       carries the no-text/no-people rules; a garbled brief never reaches the
       image model.
  I-3  the draw: DALL·E is asked for bytes (its url expires in an hour),
       gpt-image-1 is NOT (it rejects the parameter), a content-policy refusal
       is the author's 400 and everything else is a retryable 503.
  I-4  config: a size or quality the model does not accept falls back instead
       of 400ing every draw.
  I-5  routes: the admin gate, the kill switch, a parent_id from another post,
       and the attach contract (cover_alt follows the image; cover_kind never
       changes).
  I-6  never lose a drawn image: a missing history table or a failed attach
       still returns the stored cover.
  I-7  storage: allowlisted type, size cap, refusal when R2 is unconfigured,
       and keys that never echo a filename.
  I-8  the fences — construct guard on public alt copy, no public route reads
       the candidates, no F1 module imports this surface.

Run: python3 -m unittest test_journal_image
"""
from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from flask import Flask
    from routes import journal as jroutes
    from services import journal_image as ji
    from services import journal_media as jm
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    jroutes = None
    ji = None
    jm = None
    _IMPORT_ERROR = e

PW = "s3cret-pw"
PID = "11111111-1111-4111-8111-111111111111"
IID = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _post_row(**over):
    row = {
        "id": PID, "slug": "why-your-voice-shakes",
        "title": "Why your voice shakes", "excerpt": "A short read.",
        "category": "physiology", "read_time_min": 4,
        "cover_kind": "image", "cover_image_url": None, "cover_alt": None,
        "media_url": None, "media_duration_sec": None,
        "body": "One.\n\nTwo.", "author_name": "Willpower Lab",
        "author_avatar_url": None, "status": "draft", "published_at": None,
        "sort_order": 0, "meta_title": None, "meta_description": None,
        "og_image_url": None, "created_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-02T00:00:00Z",
    }
    row.update(over)
    return row


def _image_row(**over):
    row = {
        "id": IID, "journal_post_id": PID,
        "image_url": "https://cdn.example/journal/generated/abc.png",
        "storage_key": "journal/generated/abc.png",
        "alt_text": "A hand resting on a closed piano lid.",
        "prompt": "A hand resting on a closed piano lid, morning light.",
        "revised_prompt": "", "notes": "", "parent_image_id": None,
        "flags": [], "model": "dall-e-3", "size": "1792x1024",
        "quality": "standard", "created_at": "2026-07-28T00:00:00Z",
    }
    row.update(over)
    return row


def _drawn(**over):
    out = {
        "image_bytes": PNG, "content_type": "image/png",
        "prompt": "A hand resting on a closed piano lid.",
        "alt_text": "A hand resting on a closed piano lid.",
        "brief_source": "model", "flags": [], "revised_prompt": None,
        "model": "dall-e-3", "size": "1792x1024", "quality": "standard",
    }
    out.update(over)
    return out


class _FakeDb:
    """Records calls; returns canned rows."""

    def __init__(self, post=None, images=None, inserted="echo", image=None,
                 updated="echo"):
        self.post = post
        self.images = images if images is not None else []
        self.inserted = inserted
        self.image = image
        self.updated = updated
        self.calls = []

    def get_journal_post_by_id(self, pid):
        self.calls.append(("by_id", pid))
        return self.post

    def update_journal_post(self, pid, fields):
        self.calls.append(("update", pid, fields))
        if self.updated == "echo":
            return {**(self.post or {}), **fields}
        return self.updated

    def list_journal_post_images(self, pid, limit=24):
        self.calls.append(("list_images", pid, limit))
        return self.images

    def get_journal_post_image(self, iid):
        self.calls.append(("get_image", iid))
        return self.image

    def insert_journal_post_image(self, row):
        self.calls.append(("insert_image", row))
        if self.inserted == "echo":
            return _image_row(**{k: v for k, v in row.items()
                                 if k != "flags"}, flags=row.get("flags") or [])
        return self.inserted

    def delete_journal_post_image(self, iid):
        self.calls.append(("delete_image", iid))
        return True


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class _Case(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def _post(self, fn, body, pw=PW, enabled=True):
        with self.app.test_request_context(json=body):
            with patch.object(jroutes.config, "JOURNAL_ADMIN_PASSWORD", pw), \
                    patch.object(ji, "image_enabled", lambda: enabled):
                out = fn()
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status

    def _generate(self, fake, body, drawn=None, stored=None, boom=None):
        """POST /image/generate with the model and the bucket stubbed out."""
        stored = stored or {"public_url": "https://cdn.example/journal/"
                                          "generated/abc.png",
                            "key": "journal/generated/abc.png"}
        with patch.object(jroutes, "db", fake), \
                patch.object(ji, "generate_cover_image",
                             (lambda *a, **kw: (_ for _ in ()).throw(boom))
                             if boom else lambda *a, **kw: drawn or _drawn()), \
                patch.object(jm, "put_bytes", lambda **kw: stored):
            return self._post(jroutes.journal_image_generate, body)


def _no_llm():
    """services.llm missing — the brief falls back."""
    return patch.dict(sys.modules, {"services.llm": None})


def _fake_openai(client):
    return patch.dict(
        sys.modules,
        {"services.openai_service": SimpleNamespace(
            openai_service=SimpleNamespace(client=client))},
    )


class _FakeImages:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.kwargs = None

    def generate(self, **kw):
        self.kwargs = kw
        if self.error:
            raise self.error
        return self.result


def _client(result=None, error=None):
    images = _FakeImages(result=result, error=error)
    return SimpleNamespace(images=images), images


def _response(b64="AAAA", revised=None):
    return SimpleNamespace(
        data=[SimpleNamespace(b64_json=b64, revised_prompt=revised)])


# ── I-1 the brief ─────────────────────────────────────────────────────────

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class BriefTests(unittest.TestCase):

    def test_house_style_and_essay_reach_the_model(self):
        out = ji.build_brief_user(_post_row())
        self.assertIn("HOUSE STYLE:", out)
        self.assertIn("Why your voice shakes", out)
        self.assertIn("physiology", out)

    def test_a_steer_is_applied_to_the_previous_brief(self):
        # The whole point of the notes box: "darker" must mean "the image on
        # screen, darker" — not a fresh unrelated cover.
        out = ji.build_brief_user(
            _post_row(), notes="darker, no hands",
            previous={"prompt": "A hand on a piano lid."})
        self.assertIn("PREVIOUS BRIEF", out)
        self.assertIn("A hand on a piano lid.", out)
        self.assertIn("darker, no hands", out)
        self.assertIn("Keep everything it does not mention.", out)

    def test_regenerate_with_no_note_asks_for_a_different_scene(self):
        # Otherwise the model reads the previous brief as something to
        # reproduce and the button looks broken.
        out = ji.build_brief_user(_post_row(),
                                  previous={"prompt": "A hand on a lid."})
        self.assertIn("DIFFERENT scene", out)

    def test_a_first_draw_mentions_no_previous_brief(self):
        out = ji.build_brief_user(_post_row())
        self.assertNotIn("PREVIOUS BRIEF", out)
        self.assertNotIn("STEER", out)

    def test_long_essays_and_long_notes_are_capped(self):
        out = ji.build_brief_user(_post_row(body="x" * 50_000),
                                  notes="y" * 5_000)
        self.assertLess(len(out), 12_000)
        self.assertNotIn("y" * 600, out)

    def test_the_system_prompt_bans_text_people_and_the_construct(self):
        sysp = ji._BRIEF_SYSTEM
        self.assertIn("NO TEXT ANYWHERE IN THE IMAGE", sysp)
        self.assertIn("recognizable people", sysp)
        self.assertIn("charisma score", sysp)   # the retired vocabulary

    def test_non_dict_post_does_not_crash_the_builder(self):
        self.assertIn("HOUSE STYLE:", ji.build_brief_user(None))


# ── I-2 degradation ───────────────────────────────────────────────────────

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class FallbackTests(unittest.TestCase):

    def test_no_text_model_still_produces_a_usable_brief(self):
        with _no_llm():
            brief = ji.compose_brief(_post_row())
        self.assertEqual(brief["brief_source"], "fallback")
        self.assertIn("Why your voice shakes", brief["prompt"])
        # The hard rules survive the fallback — they are not prompt decoration.
        self.assertIn("no text", brief["prompt"].lower())
        self.assertIn("No recognizable people", brief["prompt"])
        self.assertTrue(brief["alt_text"])

    def test_the_fallback_still_applies_the_steer(self):
        with _no_llm():
            brief = ji.compose_brief(_post_row(), notes="colder, no faces",
                                     previous={"prompt": "A warm kitchen."})
        self.assertIn("A warm kitchen.", brief["prompt"])
        self.assertIn("colder, no faces", brief["prompt"])

    def test_an_empty_model_brief_falls_back_rather_than_drawing_nothing(self):
        fake = SimpleNamespace(parsed={"prompt": "   ", "alt_text": "x"},
                               text="")
        with patch("services.llm.chat_complete", lambda **kw: fake):
            brief = ji.compose_brief(_post_row())
        self.assertEqual(brief["brief_source"], "fallback")
        self.assertTrue(brief["prompt"].strip())

    def test_the_model_brief_is_capped_and_demarkdowned(self):
        fake = SimpleNamespace(
            parsed={"prompt": "**" + "a" * 9_000, "alt_text": "b" * 900},
            text="")
        with patch("services.llm.chat_complete", lambda **kw: fake):
            brief = ji.compose_brief(_post_row())
        self.assertEqual(brief["brief_source"], "model")
        self.assertLessEqual(len(brief["prompt"]), ji._MAX_PROMPT_CHARS)
        self.assertLessEqual(len(brief["alt_text"]), ji._MAX_ALT_LEN)
        self.assertFalse(brief["prompt"].startswith("**"))

    def test_a_missing_alt_falls_back_to_the_title(self):
        fake = SimpleNamespace(parsed={"prompt": "a scene", "alt_text": ""},
                               text="")
        with patch("services.llm.chat_complete", lambda **kw: fake):
            brief = ji.compose_brief(_post_row())
        self.assertEqual(brief["alt_text"], "Why your voice shakes")


# ── I-3 the draw ──────────────────────────────────────────────────────────

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class DrawTests(unittest.TestCase):

    def test_dalle_is_asked_for_bytes_not_a_url(self):
        # DALL·E's url expires in ~1h. Storing it would blank every cover on
        # the site shortly after publishing.
        client, images = _client(result=_response())
        with _fake_openai(client), \
                patch.object(ji, "image_model", lambda: "dall-e-3"):
            out = ji._draw("a scene")
        self.assertEqual(images.kwargs["response_format"], "b64_json")
        self.assertEqual(images.kwargs["n"], 1)
        self.assertTrue(images.kwargs["timeout"])
        self.assertEqual(out["image_bytes"], b"\x00\x00\x00")

    def test_gpt_image_is_not_sent_response_format(self):
        # That model 400s on the parameter — it always returns base64.
        client, images = _client(result=_response())
        with _fake_openai(client), \
                patch.object(ji, "image_model", lambda: "gpt-image-1"):
            ji._draw("a scene")
        self.assertNotIn("response_format", images.kwargs)
        self.assertEqual(images.kwargs["model"], "gpt-image-1")

    def test_a_content_policy_refusal_is_the_authors_400(self):
        err = RuntimeError(
            "Your request was rejected as a result of our safety system.")
        client, _ = _client(error=err)
        with _fake_openai(client):
            with self.assertRaises(ji.ImageRejected):
                ji._draw("a scene")

    def test_any_other_failure_is_retryable_not_a_rejection(self):
        client, _ = _client(error=RuntimeError("502 upstream"))
        with _fake_openai(client):
            with self.assertRaises(ji.JournalImageError) as ctx:
                ji._draw("a scene")
        self.assertNotIsInstance(ctx.exception, ji.ImageRejected)

    def test_a_response_with_no_bytes_raises_instead_of_storing_nothing(self):
        client, _ = _client(result=_response(b64=None))
        with _fake_openai(client):
            with self.assertRaises(ji.JournalImageError):
                ji._draw("a scene")

    def test_no_client_raises_instead_of_returning_a_blank_image(self):
        with _fake_openai(None):
            with self.assertRaises(ji.JournalImageError):
                ji._draw("a scene")

    def test_the_revised_prompt_is_carried_through(self):
        client, _ = _client(result=_response(revised="what it actually drew"))
        with _fake_openai(client):
            out = ji._draw("a scene")
        self.assertEqual(out["revised_prompt"], "what it actually drew")


# ── I-4 config ────────────────────────────────────────────────────────────

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ConfigTests(unittest.TestCase):

    def test_a_size_the_model_rejects_falls_back(self):
        # A typo in an env var must not 400 every draw.
        from config import Config
        with patch.object(Config, "JOURNAL_IMAGE_SIZE", "1536x1024"):
            self.assertEqual(ji.image_size("dall-e-3"), "1792x1024")
        with patch.object(Config, "JOURNAL_IMAGE_SIZE", "1024x1024"):
            self.assertEqual(ji.image_size("dall-e-3"), "1024x1024")

    def test_quality_vocabularies_are_per_family(self):
        from config import Config
        with patch.object(Config, "JOURNAL_IMAGE_QUALITY", "medium"):
            self.assertEqual(ji.image_quality("dall-e-3"), "standard")
            self.assertEqual(ji.image_quality("gpt-image-1"), "medium")

    def test_an_unknown_model_is_left_alone(self):
        # A model released after this file was written must stay callable.
        from config import Config
        with patch.object(Config, "JOURNAL_IMAGE_SIZE", "4096x4096"):
            self.assertEqual(ji.image_size("some-future-model"), "4096x4096")


# ── I-5 routes ────────────────────────────────────────────────────────────

class RouteTests(_Case):

    ADMIN_FNS = ("journal_image_generate", "journal_image_list",
                 "journal_image_select", "journal_image_delete")

    def test_every_endpoint_401s_and_503s_like_the_rest_of_the_cms(self):
        for name in self.ADMIN_FNS:
            fn = getattr(jroutes, name)
            with patch.object(jroutes, "db", _FakeDb(post=_post_row())):
                body, status = self._post(fn, {"password": "wrong"})
                self.assertEqual(status, 401, name)
                body, status = self._post(fn, {"password": "x"}, pw="")
                self.assertEqual(status, 503, name)
                self.assertEqual(body["code"], "DISABLED", name)

    def test_the_kill_switch_stops_drawing_but_not_reading(self):
        # Off is a switch for the image bill: covers already drawn stay usable.
        with patch.object(jroutes, "db", _FakeDb(post=_post_row())):
            body, status = self._post(jroutes.journal_image_generate,
                                      {"password": PW, "post_id": PID},
                                      enabled=False)
            self.assertEqual(status, 503)
            self.assertEqual(body["code"], "DISABLED")
            _, status = self._post(jroutes.journal_image_list,
                                   {"password": PW, "post_id": PID},
                                   enabled=False)
            self.assertEqual(status, 200)

    def test_unknown_post_is_404(self):
        with patch.object(jroutes, "db", _FakeDb(post=None)):
            _, status = self._post(jroutes.journal_image_generate,
                                   {"password": PW, "post_id": PID})
        self.assertEqual(status, 404)

    def test_missing_post_id_is_400(self):
        with patch.object(jroutes, "db", _FakeDb()):
            _, status = self._post(jroutes.journal_image_generate,
                                   {"password": PW})
        self.assertEqual(status, 400)

    def test_an_empty_post_is_400_not_a_wasted_image(self):
        empty = _post_row(title="", body="")
        with patch.object(jroutes, "db", _FakeDb(post=empty)):
            _, status = self._post(jroutes.journal_image_generate,
                                   {"password": PW, "post_id": PID})
        self.assertEqual(status, 400)

    def test_a_parent_from_another_post_is_refused(self):
        # Briefing from another post's cover would silently cross the two.
        fake = _FakeDb(post=_post_row(),
                       image=_image_row(journal_post_id=OTHER))
        with patch.object(jroutes, "db", fake):
            body, status = self._post(
                jroutes.journal_image_generate,
                {"password": PW, "post_id": PID, "parent_id": IID})
        self.assertEqual(status, 400)
        self.assertIn("different post", body["error"])

    def test_the_happy_path_stores_attaches_and_returns_the_strip(self):
        fake = _FakeDb(post=_post_row(), images=[_image_row()])
        body, status = self._generate(
            fake, {"password": PW, "post_id": PID, "notes": "colder"})
        self.assertEqual(status, 200)
        self.assertTrue(body["attached"])
        self.assertEqual(body["image"]["image_url"],
                         "https://cdn.example/journal/generated/abc.png")
        self.assertTrue(body["items"])
        # The cover landed on the post, alt included.
        update = [c for c in fake.calls if c[0] == "update"][0]
        self.assertEqual(update[2]["cover_image_url"],
                         "https://cdn.example/journal/generated/abc.png")
        self.assertTrue(update[2]["cover_alt"])
        # ...and the notes were recorded against the attempt.
        insert = [c for c in fake.calls if c[0] == "insert_image"][0]
        self.assertEqual(insert[1]["notes"], "colder")

    def test_attaching_never_changes_the_cover_kind_or_the_media(self):
        # On a video post the drawn image is the poster frame; flipping the
        # kind here would drop the video.
        fake = _FakeDb(post=_post_row(cover_kind="video",
                                      media_url="https://cdn/x.mp4"))
        body, status = self._generate(fake,
                                      {"password": PW, "post_id": PID})
        self.assertEqual(status, 200)
        written = [c for c in fake.calls if c[0] == "update"][0][2]
        self.assertNotIn("cover_kind", written)
        self.assertNotIn("media_url", written)

    def test_a_null_attach_still_attaches(self):
        # null == absent == default true. A FE serializing an untouched
        # optional as null would otherwise draw a cover and never use it.
        fake = _FakeDb(post=_post_row())
        body, status = self._generate(
            fake, {"password": PW, "post_id": PID, "attach": None})
        self.assertEqual(status, 200)
        self.assertTrue(body["attached"])

    def test_attach_false_leaves_the_post_untouched(self):
        fake = _FakeDb(post=_post_row())
        body, status = self._generate(
            fake, {"password": PW, "post_id": PID, "attach": False})
        self.assertEqual(status, 200)
        self.assertFalse(body["attached"])
        self.assertIsNone(body["post"])
        self.assertFalse([c for c in fake.calls if c[0] == "update"])

    def test_regenerate_refines_the_latest_attempt_by_default(self):
        fake = _FakeDb(post=_post_row(), images=[_image_row()])
        seen = {}

        def _capture(post, notes=None, previous=None):
            seen["previous"] = previous
            return _drawn()

        with patch.object(jroutes, "db", fake), \
                patch.object(ji, "generate_cover_image", _capture), \
                patch.object(jm, "put_bytes",
                             lambda **kw: {"public_url": "https://cdn/x.png",
                                           "key": "k"}):
            _, status = self._post(jroutes.journal_image_generate,
                                   {"password": PW, "post_id": PID,
                                    "notes": "darker"})
        self.assertEqual(status, 200)
        self.assertEqual((seen["previous"] or {}).get("id"), IID)

    def test_fresh_ignores_the_history(self):
        fake = _FakeDb(post=_post_row(), images=[_image_row()])
        seen = {}

        def _capture(post, notes=None, previous=None):
            seen["previous"] = previous
            return _drawn()

        with patch.object(jroutes, "db", fake), \
                patch.object(ji, "generate_cover_image", _capture), \
                patch.object(jm, "put_bytes",
                             lambda **kw: {"public_url": "https://cdn/x.png",
                                           "key": "k"}):
            self._post(jroutes.journal_image_generate,
                       {"password": PW, "post_id": PID, "fresh": True})
        self.assertIsNone(seen["previous"])

    def test_a_refused_brief_is_a_400_with_the_reason(self):
        fake = _FakeDb(post=_post_row())
        body, status = self._generate(
            fake, {"password": PW, "post_id": PID},
            boom=ji.ImageRejected("The image model refused this brief."))
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "IMAGE_REJECTED")
        self.assertIn("refused", body["error"])

    def test_a_transient_draw_failure_is_a_retryable_503(self):
        fake = _FakeDb(post=_post_row())
        body, status = self._generate(
            fake, {"password": PW, "post_id": PID},
            boom=ji.JournalImageError("Could not draw the image right now."))
        self.assertEqual(status, 503)
        self.assertEqual(body["code"], "V2_ERROR")

    def test_unconfigured_storage_says_so_instead_of_try_again(self):
        fake = _FakeDb(post=_post_row())

        def _boom(**kw):
            raise jm.JournalMediaError(
                "Journal media storage is not configured.")

        with patch.object(jroutes, "db", fake), \
                patch.object(ji, "generate_cover_image",
                             lambda *a, **kw: _drawn()), \
                patch.object(jm, "put_bytes", _boom):
            body, status = self._post(jroutes.journal_image_generate,
                                      {"password": PW, "post_id": PID})
        self.assertEqual(status, 503)
        self.assertEqual(body["code"], "DISABLED")
        self.assertIn("not configured", body["error"])

    def test_notes_must_be_a_string(self):
        with patch.object(jroutes, "db", _FakeDb(post=_post_row())):
            _, status = self._post(jroutes.journal_image_generate,
                                   {"password": PW, "post_id": PID,
                                    "notes": {"a": 1}})
        self.assertEqual(status, 400)

    def test_a_non_string_post_id_is_400_not_a_crash(self):
        with patch.object(jroutes, "db", _FakeDb(post=_post_row())):
            _, status = self._post(jroutes.journal_image_generate,
                                   {"password": PW, "post_id": 17})
        self.assertEqual(status, 400)


# ── I-6 never lose a drawn image ──────────────────────────────────────────

class ResilienceTests(_Case):

    def test_a_missing_history_table_still_returns_the_cover(self):
        # Migration pending: the strip is empty, the cover is not lost.
        fake = _FakeDb(post=_post_row(), inserted=None, images=[])
        body, status = self._generate(fake, {"password": PW, "post_id": PID})
        self.assertEqual(status, 200)
        self.assertEqual(body["image"]["image_url"],
                         "https://cdn.example/journal/generated/abc.png")
        self.assertTrue(body["attached"])

    def test_a_failed_attach_still_returns_the_image(self):
        # The image is drawn, paid for and stored — a save problem must not
        # discard it.
        fake = _FakeDb(post=_post_row(), updated=None)
        body, status = self._generate(fake, {"password": PW, "post_id": PID})
        self.assertEqual(status, 200)
        self.assertFalse(body["attached"])
        self.assertIn("attach_error", body)
        self.assertTrue(body["image"]["image_url"])

    def test_a_non_https_public_base_is_caught_by_the_cms_validator(self):
        # Generated covers are held to the same contract as pasted ones.
        fake = _FakeDb(post=_post_row())
        body, status = self._generate(
            fake, {"password": PW, "post_id": PID},
            stored={"public_url": "http://insecure/x.png", "key": "k"})
        self.assertEqual(status, 200)
        self.assertFalse(body["attached"])
        self.assertIn("https", body["attach_error"])


# ── I-5 (cont.) select + delete ───────────────────────────────────────────

class SelectTests(_Case):

    def test_select_promotes_an_earlier_attempt(self):
        fake = _FakeDb(post=_post_row(), image=_image_row())
        with patch.object(jroutes, "db", fake):
            body, status = self._post(jroutes.journal_image_select,
                                      {"password": PW, "id": IID})
        self.assertEqual(status, 200)
        written = [c for c in fake.calls if c[0] == "update"][0][2]
        self.assertEqual(written["cover_image_url"], _image_row()["image_url"])
        self.assertEqual(written["cover_alt"], _image_row()["alt_text"])

    def test_select_on_an_unknown_image_is_404(self):
        with patch.object(jroutes, "db", _FakeDb(image=None)):
            _, status = self._post(jroutes.journal_image_select,
                                   {"password": PW, "id": IID})
        self.assertEqual(status, 404)

    def test_delete_clears_the_candidate(self):
        fake = _FakeDb()
        with patch.object(jroutes, "db", fake):
            body, status = self._post(jroutes.journal_image_delete,
                                      {"password": PW, "id": IID})
        self.assertEqual(status, 200)
        self.assertTrue(body["deleted"])

    def test_list_requires_a_post_id(self):
        with patch.object(jroutes, "db", _FakeDb()):
            _, status = self._post(jroutes.journal_image_list,
                                   {"password": PW})
        self.assertEqual(status, 400)


# ── I-7 storage ───────────────────────────────────────────────────────────

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class StorageTests(unittest.TestCase):

    def test_a_disallowed_type_is_refused(self):
        with self.assertRaises(jm.JournalMediaError):
            jm.put_bytes(data=PNG, content_type="image/gif")

    def test_empty_data_is_refused(self):
        with self.assertRaises(jm.JournalMediaError):
            jm.put_bytes(data=b"", content_type="image/png")

    def test_an_oversized_image_is_refused_before_the_upload(self):
        with patch.object(jm, "max_bytes_for", lambda kind: 10):
            with self.assertRaises(jm.JournalMediaError) as ctx:
                jm.put_bytes(data=PNG, content_type="image/png")
        self.assertIn("larger than", str(ctx.exception))

    def test_unconfigured_storage_refuses_rather_than_stranding_bytes(self):
        with patch.object(jm, "journal_media_use_r2", lambda: False):
            with self.assertRaises(jm.JournalMediaError) as ctx:
                jm.put_bytes(data=PNG, content_type="image/png")
        self.assertIn("not configured", str(ctx.exception))

    def test_no_public_base_url_refuses(self):
        with patch.object(jm, "journal_media_use_r2", lambda: True), \
                patch.object(jm, "journal_public_base_url", lambda: ""):
            with self.assertRaises(jm.JournalMediaError) as ctx:
                jm.put_bytes(data=PNG, content_type="image/png")
        self.assertIn("public base URL", str(ctx.exception))

    def test_generated_covers_land_in_their_own_folder(self):
        key = jm.build_object_key("image", "image/png", folder="generated")
        self.assertTrue(key.startswith("journal/generated/"))
        self.assertTrue(key.endswith(".png"))

    def test_the_default_folder_is_still_the_kind(self):
        # The presign path must be byte-identical to before this feature.
        self.assertTrue(
            jm.build_object_key("image", "image/png").startswith(
                "journal/image/"))

    def test_the_upload_is_public_immutable_and_typed(self):
        seen = {}

        class _S3:
            def put_object(self, **kw):
                seen.update(kw)

        with patch.object(jm, "journal_media_use_r2", lambda: True), \
                patch.object(jm, "journal_public_base_url",
                             lambda: "https://cdn.example"), \
                patch.object(jm, "journal_bucket_name", lambda: "b"), \
                patch.object(jm, "_client", lambda: _S3()):
            out = jm.put_bytes(data=PNG, content_type="image/png")
        self.assertEqual(seen["ContentType"], "image/png")
        self.assertIn("immutable", seen["CacheControl"])
        self.assertTrue(out["public_url"].startswith("https://cdn.example/"))


# ── I-8 the fences ────────────────────────────────────────────────────────

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class FenceTests(unittest.TestCase):
    """Generated covers are a marketing surface: guarded public copy,
    invisible to the public API, invisible to the F1 assembly path."""

    def test_the_construct_guard_flags_public_alt_copy(self):
        self.assertEqual(
            ji.guard_flags("your charisma score rose", "a scene"),
            ["construct"])
        self.assertEqual(ji.guard_flags("a hand on a piano lid"), [])

    def test_a_flagged_brief_is_flagged_not_dropped(self):
        # A human is already looking at this draft; a warning beats a silent
        # deletion.
        row = ji.row_for_insert(
            PID, {"alt_text": "the KPI of your voice", "prompt": "a scene",
                  "flags": ji.guard_flags("the KPI of your voice")},
            image_url="https://cdn/x.png")
        self.assertEqual(row["flags"], ["construct"])
        self.assertTrue(row["alt_text"])

    def test_no_public_journal_route_reads_the_candidates(self):
        import inspect
        public = inspect.getsource(jroutes).split("# ── ADMIN")[0]
        for banned in ("journal_post_image", "journal_image"):
            self.assertNotIn(banned, public)

    def test_the_service_names_nothing_from_the_loop(self):
        import inspect
        src = inspect.getsource(ji)
        for banned in ("best_presentation", "ideal_text", "charisma_snippets",
                       "lab_recording", "power_score", "delivery_stars"):
            self.assertNotIn(banned, src)

    def test_l1_no_assembly_module_imports_this_surface(self):
        import importlib
        import inspect
        for name in ("services.best_presentation", "services.ideal_text_block",
                     "services.ideal_text_report",
                     "services.cross_take_selection",
                     "services.charisma_snippet_service"):
            try:
                mod = importlib.import_module(name)
            except Exception:  # pragma: no cover - optional deps
                continue
            self.assertNotIn("journal_image", inspect.getsource(mod), name)

    def test_no_scores_reach_a_cms_payload(self):
        import json
        raw = json.dumps(ji.serialize_image(_image_row()))
        for banned in ("power_score", "charisma", "overall_score", "threat"):
            self.assertNotIn(banned, raw)

    def test_the_row_never_carries_publishable_fields(self):
        # Structural: a candidate has no slug/status, so it cannot be rendered
        # as an article on its own.
        row = ji.row_for_insert(PID, _drawn(), image_url="https://cdn/x.png")
        for banned in ("slug", "status", "published_at", "sort_order"):
            self.assertNotIn(banned, row)


if __name__ == "__main__":
    unittest.main()
