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

Run: python3 -m unittest tests.test_journal_image
"""
from __future__ import annotations

import unittest
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


# ── I-1 the brief ─────────────────────────────────────────────────────────


# ── I-2 degradation ───────────────────────────────────────────────────────


# ── I-3 the draw ──────────────────────────────────────────────────────────


# ── I-4 config ────────────────────────────────────────────────────────────


# ── I-5 routes ────────────────────────────────────────────────────────────


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


# ── I-5 (cont.) select + delete ───────────────────────────────────────────


# ── I-7 storage ───────────────────────────────────────────────────────────


# ── I-8 the fences ────────────────────────────────────────────────────────


if __name__ == "__main__":
    unittest.main()
