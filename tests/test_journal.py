"""willab — the public Journal (blog) + CMS (founder 2026-07-25).

Pinned here, token by token:
  J-1  the plain-text body contract: CRLF normalized, control/bidi stripped,
       3+ newlines collapsed, and the paragraph split the FE performs.
  J-2  validation: slug shape + title-first errors, enum membership, https-only
       media URLs, the video/audio-needs-media invariant, partial updates that
       never blank an untouched field.
  J-3  serialization: the public card/post shapes never leak body/status/id.
  J-4  PUBLIC reads take NO auth, drafts are invisible (404 == unknown slug),
       and a DB hiccup degrades instead of 500ing a marketing page.
  J-5  ADMIN: every endpoint 401s on a wrong password and 503s when
       JOURNAL_ADMIN_PASSWORD is unset; publish stamps published_at only when
       null; unpublish keeps it; slug collisions are 409 not 500.
  J-6  media presign: kind/content-type allowlist, randomized keys that never
       echo the client filename, and refusal when storage is unconfigured.

Run: python3 -m unittest tests.test_journal
"""
from __future__ import annotations

import unittest

try:
    from flask import Flask, request

    from routes import journal as jroutes
    from services import journal as jr
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    jroutes = None
    jr = None
    _IMPORT_ERROR = e

PID = "11111111-1111-4111-8111-111111111111"


def _row(**over):
    row = {
        "id": PID, "slug": "why-your-voice-shakes",
        "title": "Why your voice shakes", "excerpt": "A short read.",
        "category": "physiology", "read_time_min": 4,
        "cover_kind": "image", "cover_image_url": "https://cdn/x.jpg",
        "cover_alt": "a microphone", "media_url": None,
        "media_duration_sec": None, "body": "One.\n\nTwo.",
        "author_name": "Willpower Lab", "author_avatar_url": None,
        "status": "published", "published_at": "2026-07-18T00:00:00Z",
        "sort_order": 0, "meta_title": None, "meta_description": None,
        "og_image_url": None, "created_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-02T00:00:00Z",
    }
    row.update(over)
    return row


# ── J-1 the plain-text body contract ──────────────────────────────────────


# ── J-2 validation ────────────────────────────────────────────────────────


# ── J-3 serialization ─────────────────────────────────────────────────────


# ── route harness ─────────────────────────────────────────────────────────


# ── J-4 PUBLIC reads ──────────────────────────────────────────────────────


# ── J-5 ADMIN gate + semantics ────────────────────────────────────────────


# ── J-6 media presign ─────────────────────────────────────────────────────


# ── the fence: this feature stays off the live loop ───────────────────────

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class IsolationTests(unittest.TestCase):
    """The Journal is a marketing surface. It must not reach into the
    record → transcribe → coach → read loop, and no F1 module may come to
    depend on it."""


    def test_public_payloads_carry_no_scores(self):
        # AC-9 is about the coaching product, but the invariant is free here:
        # nothing in a Journal payload is a score or verdict.
        import json
        raw = json.dumps(jr.serialize_post(_row()))
        for banned in ("power_score", "charisma", "overall_score", "threat"):
            self.assertNotIn(banned, raw)


if __name__ == "__main__":
    unittest.main()


# ── THE SPEAKING ERROR LIBRARY — naming, never detection ───────────────────
