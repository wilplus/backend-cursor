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

Run: python3 -m unittest test_journal
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

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

PW = "s3cret-pw"
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

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class BodyContractTests(unittest.TestCase):

    def test_crlf_normalized_and_blank_runs_collapsed(self):
        out = jr.normalize_body("One.\r\n\r\n\r\n\r\nTwo.\r\nsame para.")
        self.assertEqual(out, "One.\n\nTwo.\nsame para.")

    def test_paragraph_split_matches_the_fe_contract(self):
        body = jr.normalize_body("A one.\n\nB two.\nstill B.\n\nC three.")
        self.assertEqual(jr.paragraphs(body),
                         ["A one.", "B two.\nstill B.", "C three."])

    def test_control_and_bidi_characters_stripped(self):
        dirty = "Hel​lo‮gnip﻿"
        self.assertEqual(jr.normalize_body(dirty), "Hellognip")

    def test_single_newline_is_not_a_paragraph_break(self):
        self.assertEqual(len(jr.paragraphs("one\ntwo\nthree")), 1)

    def test_body_is_never_interpreted_as_markup(self):
        # There is no HTML handling here at all: markup is stored verbatim as
        # text, and the FE renders it via textContent. This test documents
        # that so nobody "helpfully" adds an HTML pass later.
        raw = "<script>alert(1)</script>"
        self.assertEqual(jr.normalize_body(raw), raw)

    def test_empty_and_non_string(self):
        self.assertEqual(jr.normalize_body(None), "")
        self.assertEqual(jr.paragraphs(None), [])
        with self.assertRaises(jr.JournalError):
            jr.normalize_body(123)


# ── J-2 validation ────────────────────────────────────────────────────────

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ValidationTests(unittest.TestCase):

    def test_create_defaults(self):
        out = jr.validate_post_body({"title": "Hello There"})
        self.assertEqual(out["slug"], "hello-there")
        self.assertEqual(out["status"], "draft")
        self.assertEqual(out["category"], "others")
        self.assertEqual(out["read_time_min"], 1)
        self.assertEqual(out["author_name"], "Willpower Lab")

    def test_missing_title_blames_the_title_not_the_slug(self):
        with self.assertRaises(jr.JournalError) as cm:
            jr.validate_post_body({})
        self.assertIn("title", str(cm.exception))

    def test_slugify_folds_accents_and_punctuation(self):
        self.assertEqual(jr.slugify("  Héllo — Wörld!  "), "hello-world")

    def test_unsluggable_title_is_rejected_not_invented(self):
        with self.assertRaises(jr.JournalError):
            jr.validate_post_body({"title": "日本語だけ"})

    def test_bad_slug_shape_rejected(self):
        for bad in ("Has Spaces", "trailing-", "-leading", "dou--ble",
                    "sla/sh", "under_score", "qu?ery"):
            with self.assertRaises(jr.JournalError, msg=bad):
                jr.validate_post_body({"title": "t", "slug": bad})

    def test_uppercase_slug_is_normalized_not_rejected(self):
        # An author typing the slug in title case gets it lowercased rather
        # than an error — the URL is what matters, and the fix is unambiguous.
        out = jr.validate_post_body({"title": "t", "slug": "Why-Your-Voice"})
        self.assertEqual(out["slug"], "why-your-voice")

    def test_enum_membership(self):
        with self.assertRaises(jr.JournalError):
            jr.validate_post_body({"title": "t", "category": "nope"})
        with self.assertRaises(jr.JournalError):
            jr.validate_post_body({"title": "t", "cover_kind": "gif"})
        ok = jr.validate_post_body({"title": "t", "category": "voice"})
        self.assertEqual(ok["category"], "voice")

    def test_science_category_accepted(self):
        # 'science' joined the tuple with the /science → blog consolidation
        # (migrations/add_journal_science_category.sql widens the CHECK).
        self.assertIn("science", jr.CATEGORIES)
        ok = jr.validate_post_body({"title": "t", "category": "science"})
        self.assertEqual(ok["category"], "science")

    def test_media_urls_must_be_https(self):
        for bad in ("http://x/y.jpg", "javascript:alert(1)",
                    "data:image/png;base64,AAA"):
            with self.assertRaises(jr.JournalError, msg=bad):
                jr.validate_post_body({"title": "t", "cover_image_url": bad})
        ok = jr.validate_post_body(
            {"title": "t", "cover_image_url": "https://cdn/x.jpg"})
        self.assertEqual(ok["cover_image_url"], "https://cdn/x.jpg")

    def test_video_cover_requires_media_on_create(self):
        with self.assertRaises(jr.JournalError):
            jr.validate_post_body({"title": "t", "cover_kind": "video"})
        ok = jr.validate_post_body({"title": "t", "cover_kind": "video",
                                    "media_url": "https://cdn/v.mp4"})
        self.assertEqual(ok["cover_kind"], "video")

    def test_partial_update_only_returns_present_keys(self):
        out = jr.validate_post_body({"title": "New title"}, partial=True)
        self.assertEqual(out, {"title": "New title"})
        self.assertNotIn("status", out)     # untouched fields never written
        self.assertNotIn("body", out)

    def test_explicit_null_in_a_partial_update_never_resets_to_default(self):
        # REGRESSION: an explicit null used to hit the `or <default>` fallback,
        # so a CMS form serializing untouched optional inputs as null would
        # send {"status": null} and silently UNPUBLISH a live post (and
        # {"body": null} would wipe it).
        out = jr.validate_post_body({
            "title": "Kept", "status": None, "body": None, "category": None,
            "read_time_min": None, "author_name": None, "sort_order": None,
            "excerpt": None, "cover_kind": None,
        }, partial=True)
        self.assertEqual(out, {"title": "Kept"})

    def test_create_still_applies_defaults_for_null(self):
        # On CREATE (not partial) a null legitimately means "use the default".
        out = jr.validate_post_body({"title": "t", "status": None,
                                     "category": None}, partial=False)
        self.assertEqual(out["status"], "draft")
        self.assertEqual(out["category"], "others")

    def test_publishing_via_status_stamps_a_display_date(self):
        # REGRESSION: only the publish ROUTE stamped published_at, so flipping
        # the editor's status control to Published produced a live post with
        # published_at = NULL — which sorts NULLS FIRST and pins itself to the
        # top of the public index forever.
        out = jr.validate_post_body({"title": "Launch day",
                                     "status": "published"})
        self.assertTrue(out.get("published_at"))

        upd = jr.validate_post_body({"status": "published"}, partial=True,
                                    existing=_row(published_at=None))
        self.assertTrue(upd.get("published_at"))

    def test_publishing_never_overwrites_an_author_set_date(self):
        # explicit date in the same payload wins
        out = jr.validate_post_body({"title": "t", "status": "published",
                                     "published_at": "2020-01-01"})
        self.assertEqual(out["published_at"], "2020-01-01")
        # a date already stored wins
        upd = jr.validate_post_body(
            {"status": "published"}, partial=True,
            existing=_row(published_at="2019-05-05T00:00:00Z"))
        self.assertNotIn("published_at", upd)

    def test_drafting_does_not_stamp_a_date(self):
        out = jr.validate_post_body({"title": "t"})
        self.assertIsNone(out.get("published_at"))

    def test_impossible_calendar_dates_are_400_not_500(self):
        # REGRESSION: the shape-only regex accepted 2026-13-45; Postgres then
        # rejected the write and the route surfaced an opaque 500.
        for bad in ("2026-13-45", "0000-00-00", "9999-99-99T99:99",
                    "2026-02-30"):
            with self.assertRaises(jr.JournalError, msg=bad):
                jr.validate_post_body({"published_at": bad}, partial=True)

    def test_real_dates_still_pass_with_or_without_a_time(self):
        for good in ("2026-07-18", "2026-07-18T09:30:00Z",
                     "2026-07-18 09:30:00+00", "2024-02-29"):  # leap day
            out = jr.validate_post_body({"published_at": good}, partial=True)
            self.assertEqual(out["published_at"], good, good)

    def test_non_leap_year_feb_29_rejected(self):
        with self.assertRaises(jr.JournalError):
            jr.validate_post_body({"published_at": "2026-02-29"},
                                  partial=True)

    def test_urls_reject_embedded_whitespace_and_control_chars(self):
        for bad in ("https://a b/c", "https://\njavascript:alert(1)",
                    "https://a\tb"):
            with self.assertRaises(jr.JournalError, msg=bad):
                jr.validate_post_body({"title": "t",
                                       "cover_image_url": bad})

    def test_partial_media_invariant_checked_against_merged_row(self):
        stored = _row(cover_kind="image", media_url=None)
        # kind flips to audio in this save, media arrives in a later one
        with self.assertRaises(jr.JournalError):
            jr.check_media_consistency({**stored, "cover_kind": "audio"})
        # kind was already audio, media supplied now -> fine
        jr.check_media_consistency({**stored, "cover_kind": "audio",
                                    "media_url": "https://cdn/a.mp3"})

    def test_password_and_id_never_become_columns(self):
        out = jr.validate_post_body(
            {"title": "t", "password": "hunter2", "id": "x",
             "created_at": "nope"}, partial=False)
        for banned in ("password", "id", "created_at"):
            self.assertNotIn(banned, out)

    def test_read_time_accepts_numeric_string_and_bounds(self):
        self.assertEqual(
            jr.validate_post_body({"title": "t", "read_time_min": "7"}
                                  )["read_time_min"], 7)
        with self.assertRaises(jr.JournalError):
            jr.validate_post_body({"title": "t", "read_time_min": 9999})
        with self.assertRaises(jr.JournalError):
            jr.validate_post_body({"title": "t", "read_time_min": True})

    def test_published_at_shape(self):
        out = jr.validate_post_body({"title": "t",
                                     "published_at": "2026-07-18"},
                                    partial=True)
        self.assertEqual(out["published_at"], "2026-07-18")
        with self.assertRaises(jr.JournalError):
            jr.validate_post_body({"published_at": "last tuesday"},
                                  partial=True)

    def test_sort_key_mapping(self):
        self.assertEqual(jr.sort_key_for(None), ("published_at", True))
        self.assertEqual(jr.sort_key_for("newest"), ("published_at", True))
        self.assertEqual(jr.sort_key_for("oldest"), ("published_at", False))
        self.assertEqual(jr.sort_key_for("curated"), ("sort_order", False))
        self.assertEqual(jr.sort_key_for("garbage"), ("published_at", True))

    def test_limit_and_offset_clamped(self):
        self.assertEqual(jr.clamp_limit(None), jr.DEFAULT_LIMIT)
        self.assertEqual(jr.clamp_limit(9999), jr.MAX_LIMIT)
        self.assertEqual(jr.clamp_limit(0), 1)
        self.assertEqual(jr.clamp_offset(-5), 0)
        self.assertEqual(jr.clamp_offset("12"), 12)


# ── J-3 serialization ─────────────────────────────────────────────────────

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SerializationTests(unittest.TestCase):

    def test_card_never_leaks_body_status_or_id(self):
        card = jr.serialize_card(_row())
        for banned in ("body", "status", "id", "media_url", "created_at"):
            self.assertNotIn(banned, card)
        self.assertEqual(card["slug"], "why-your-voice-shakes")

    def test_public_post_carries_body_but_not_status_or_id(self):
        post = jr.serialize_post(_row())
        self.assertEqual(post["body"], "One.\n\nTwo.")
        self.assertNotIn("status", post)
        self.assertNotIn("id", post)

    def test_admin_shape_has_everything(self):
        adm = jr.serialize_admin(_row())
        self.assertEqual(adm["id"], PID)
        self.assertEqual(adm["status"], "published")
        self.assertIn("updated_at", adm)


# ── route harness ─────────────────────────────────────────────────────────

class _FakeDb:
    """Records calls; returns canned rows."""

    def __init__(self, rows=None, one=None, created=None, updated=None,
                 raise_on_slug=False):
        self.rows = rows if rows is not None else []
        self.one = one
        self.created = created
        self.updated = updated
        self.raise_on_slug = raise_on_slug
        self.calls = []

    def list_journal_posts(self, **kw):
        self.calls.append(("list", kw))
        return self.rows

    def count_journal_posts(self, **kw):
        self.calls.append(("count", kw))
        return len(self.rows)

    def get_journal_post_by_slug(self, slug, published_only=True,
                                 strict=False):
        self.calls.append(("by_slug", slug, published_only))
        if self.raise_on_slug:
            raise RuntimeError("db down")
        return self.one

    def get_journal_post_by_id(self, pid):
        self.calls.append(("by_id", pid))
        return self.one

    def create_journal_post(self, fields):
        self.calls.append(("create", fields))
        return self.created

    def update_journal_post(self, pid, fields):
        self.calls.append(("update", pid, fields))
        return self.updated

    def delete_journal_post(self, pid):
        self.calls.append(("delete", pid))
        return True

    def reorder_journal_posts(self, ids):
        self.calls.append(("reorder", ids))
        return len(ids)

    def journal_category_counts(self):
        return {"voice": 2}


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class _RouteCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def _get(self, fn, *args, query=None):
        qs = query or {}
        with self.app.test_request_context(query_string=qs):
            out = fn(*args)
            resp, status = out if isinstance(out, tuple) else (out, 200)
            return resp.get_json(), status

    def _post(self, fn, body, *args, pw=PW):
        with self.app.test_request_context(json=body):
            with patch.object(jroutes.config, "JOURNAL_ADMIN_PASSWORD", pw):
                out = fn(*args)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status


# ── J-4 PUBLIC reads ──────────────────────────────────────────────────────

class PublicReadTests(_RouteCase):

    def test_index_needs_no_auth_and_returns_cards(self):
        fake = _FakeDb(rows=[_row()])
        with patch.object(jroutes, "db", fake):
            body, status = self._get(jroutes.journal_list_posts)
        self.assertEqual(status, 200)
        self.assertEqual(body["total"], 1)
        self.assertNotIn("body", body["posts"][0])
        # published_only is the non-negotiable public filter
        self.assertTrue(fake.calls[0][1]["published_only"])

    def test_index_sort_and_category_reach_the_query(self):
        fake = _FakeDb(rows=[])
        with patch.object(jroutes, "db", fake):
            self._get(jroutes.journal_list_posts,
                      query={"sort": "curated", "category": "voice"})
        kw = fake.calls[0][1]
        self.assertEqual(kw["order_column"], "sort_order")
        self.assertEqual(kw["category"], "voice")

    def test_index_all_category_is_no_filter(self):
        fake = _FakeDb(rows=[])
        with patch.object(jroutes, "db", fake):
            self._get(jroutes.journal_list_posts, query={"category": "all"})
        self.assertIsNone(fake.calls[0][1]["category"])

    HOSTILE_SEARCH = (
        "x,status.eq.draft",
        "x),or=(status.eq.draft",
        "%", "*", "x.status.eq.draft", "\\",
    )

    def test_hostile_search_never_relaxes_the_published_filter(self):
        # The published filter is a SEPARATE ANDed query param, so no value of
        # `q` can widen the result set past published rows. Pinned on BOTH the
        # list and count queries — they must agree or paging goes wrong.
        for needle in self.HOSTILE_SEARCH:
            fake = _FakeDb(rows=[])
            with patch.object(jroutes, "db", fake):
                _, status = self._get(jroutes.journal_list_posts,
                                      query={"q": needle})
            self.assertEqual(status, 200, needle)
            for call in ("list", "count"):
                kw = [c for c in fake.calls if c[0] == call][0][1]
                self.assertTrue(kw["published_only"], f"{call}/{needle}")

    def test_index_bad_category_400s(self):
        with patch.object(jroutes, "db", _FakeDb()):
            _, status = self._get(jroutes.journal_list_posts,
                                  query={"category": "nope"})
        self.assertEqual(status, 400)

    def test_index_degrades_instead_of_500ing(self):
        # Defense in depth: the db helper already swallows errors into [], so
        # in production this route's except branch is a second net (it also
        # covers a serialization bug). The INDEX degrading to empty is right —
        # unlike the by-slug route, which must 503 rather than cache a 404
        # (see test_db_outage_on_by_slug_is_503_not_a_cacheable_404).
        class _Boom:
            def list_journal_posts(self, **kw):
                raise RuntimeError("db down")
        with patch.object(jroutes, "db", _Boom()):
            body, status = self._get(jroutes.journal_list_posts)
        self.assertEqual(status, 200)      # a marketing page never 500s
        self.assertEqual(body, {"posts": [], "total": 0})

    def test_post_by_slug_public(self):
        with patch.object(jroutes, "db", _FakeDb(one=_row())):
            body, status = self._get(jroutes.journal_get_post,
                                     "why-your-voice-shakes")
        self.assertEqual(status, 200)
        self.assertEqual(body["body"], "One.\n\nTwo.")
        self.assertNotIn("status", body)

    def test_draft_and_unknown_slug_both_404(self):
        fake = _FakeDb(one=None)   # published_only filter yields nothing
        with patch.object(jroutes, "db", fake):
            _, status = self._get(jroutes.journal_get_post, "a-draft")
        self.assertEqual(status, 404)
        self.assertTrue(fake.calls[0][2])   # published_only=True enforced

    def test_db_outage_on_by_slug_is_503_not_a_cacheable_404(self):
        # REGRESSION: the db helper swallowed every error into None and the
        # route mapped None -> 404, so a Supabase blip made a live post look
        # deleted — and the FE's ISR would cache that 404.
        fake = _FakeDb(one=_row(), raise_on_slug=True)
        with patch.object(jroutes, "db", fake):
            body, status = self._get(jroutes.journal_get_post, "a-real-post")
        self.assertEqual(status, 503)
        self.assertEqual(body["code"], "UNAVAILABLE")

    def test_categories_lists_every_key(self):
        with patch.object(jroutes, "db", _FakeDb()):
            body, status = self._get(jroutes.journal_categories)
        self.assertEqual(status, 200)
        self.assertEqual(len(body["categories"]), len(jr.CATEGORIES))
        counts = {c["key"]: c["count"] for c in body["categories"]}
        self.assertEqual(counts["voice"], 2)
        self.assertEqual(counts["philosophy"], 0)


# ── J-5 ADMIN gate + semantics ────────────────────────────────────────────

class AdminGateTests(_RouteCase):

    ADMIN_FNS = (
        ("journal_admin_list", ()),
        ("journal_admin_get", ()),
        ("journal_admin_create", ()),
        ("journal_admin_update", ()),
        ("journal_admin_delete", ()),
        ("journal_admin_publish", ()),
        ("journal_admin_unpublish", ()),
        ("journal_admin_reorder", ()),
        ("journal_admin_presign", ()),
    )

    def test_every_admin_endpoint_401s_on_wrong_password(self):
        with patch.object(jroutes, "db", _FakeDb(one=_row())):
            for name, args in self.ADMIN_FNS:
                fn = getattr(jroutes, name)
                body, status = self._post(fn, {"password": "wrong"}, *args)
                self.assertEqual(status, 401, name)
                self.assertEqual(body["error"], "Wrong password", name)

    def test_every_admin_endpoint_503s_when_unconfigured(self):
        with patch.object(jroutes, "db", _FakeDb(one=_row())):
            for name, args in self.ADMIN_FNS:
                fn = getattr(jroutes, name)
                body, status = self._post(fn, {"password": "x"}, *args, pw="")
                self.assertEqual(status, 503, name)
                self.assertEqual(body["code"], "DISABLED", name)

    def test_missing_password_key_is_401_not_a_crash(self):
        with patch.object(jroutes, "db", _FakeDb()):
            _, status = self._post(jroutes.journal_admin_list, {})
        self.assertEqual(status, 401)

    def test_non_string_password_is_401_not_a_crash(self):
        with patch.object(jroutes, "db", _FakeDb()):
            _, status = self._post(jroutes.journal_admin_list,
                                   {"password": {"a": 1}})
        self.assertEqual(status, 401)

    def test_non_ascii_supplied_password_is_401_not_a_500(self):
        # hmac.compare_digest raises TypeError on non-ASCII *str*, so a probe
        # sending an accented password used to 500. We compare bytes.
        with patch.object(jroutes, "db", _FakeDb()):
            _, status = self._post(jroutes.journal_admin_list,
                                   {"password": "pwé-ünicode-🎤"})
        self.assertEqual(status, 401)

    def test_non_ascii_configured_password_still_works(self):
        # An admin password with an accent must AUTHORIZE, not explode.
        pw = "hasło-żółw-é"
        with patch.object(jroutes, "db", _FakeDb(rows=[])):
            body, status = self._post(jroutes.journal_admin_list,
                                      {"password": pw}, pw=pw)
            self.assertEqual(status, 200)
            self.assertEqual(body["posts"], [])
            # ...and a wrong password against it is still 401
            _, status2 = self._post(jroutes.journal_admin_list,
                                    {"password": "wrong"}, pw=pw)
            self.assertEqual(status2, 401)


class AdminBehaviourTests(_RouteCase):

    def test_list_includes_drafts(self):
        fake = _FakeDb(rows=[_row(status="draft")])
        with patch.object(jroutes, "db", fake):
            body, status = self._post(jroutes.journal_admin_list,
                                      {"password": PW})
        self.assertEqual(status, 200)
        self.assertEqual(body["posts"][0]["status"], "draft")
        self.assertFalse(fake.calls[0][1]["published_only"])

    def test_cms_list_order_is_pinned_sort_order_then_created_at(self):
        # FE amendment 2026-07-25: reorder writes a whole-corpus ordering that
        # drives the public "Curated" sort, so the CMS must show exactly the
        # order it is writing. created_at (never NULL), not published_at.
        fake = _FakeDb(rows=[_row()])
        with patch.object(jroutes, "db", fake):
            self._post(jroutes.journal_admin_list, {"password": PW})
        kw = fake.calls[0][1]
        self.assertEqual(kw["order_column"], "sort_order")
        self.assertFalse(kw["descending"])            # sort_order ASC
        self.assertEqual(kw["tiebreak_column"], "created_at")

    def test_cms_list_is_pageable(self):
        # REGRESSION: limit/offset were hardcoded, and since this endpoint is
        # the only way to learn a post's id, post #101 was uneditable forever.
        fake = _FakeDb(rows=[_row()])
        with patch.object(jroutes, "db", fake):
            body, status = self._post(jroutes.journal_admin_list,
                                      {"password": PW, "limit": 25,
                                       "offset": 100})
        self.assertEqual(status, 200)
        kw = [c for c in fake.calls if c[0] == "list"][0][1]
        self.assertEqual(kw["limit"], 25)
        self.assertEqual(kw["offset"], 100)
        self.assertIn("total", body)     # so the CMS can render a pager

    def test_non_string_id_is_400_not_a_500(self):
        # REGRESSION: (body.get("id") or "").strip() raised AttributeError on
        # a numeric/list id -> unhandled -> 500.
        routes_taking_id = (jroutes.journal_admin_get,
                            jroutes.journal_admin_update,
                            jroutes.journal_admin_delete,
                            jroutes.journal_admin_publish,
                            jroutes.journal_admin_unpublish)
        with patch.object(jroutes, "db", _FakeDb(one=_row())):
            for fn in routes_taking_id:
                for bad_id in (123, 4.5, True, ["a"], {"k": 1}):
                    _, status = self._post(fn, {"password": PW,
                                                "id": bad_id})
                    self.assertEqual(status, 400,
                                     f"{fn.__name__}/{bad_id!r}")

    def test_create_201(self):
        fake = _FakeDb(created=_row())
        with patch.object(jroutes, "db", fake):
            body, status = self._post(
                jroutes.journal_admin_create,
                {"password": PW, "title": "Why your voice shakes"})
        self.assertEqual(status, 201)
        self.assertEqual(body["post"]["id"], PID)

    def test_create_slug_collision_is_409(self):
        fake = _FakeDb(created="DUPLICATE_SLUG")
        with patch.object(jroutes, "db", fake):
            body, status = self._post(jroutes.journal_admin_create,
                                      {"password": PW, "title": "t"})
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "DUPLICATE_SLUG")

    def test_create_validation_error_is_400(self):
        with patch.object(jroutes, "db", _FakeDb()):
            _, status = self._post(jroutes.journal_admin_create,
                                   {"password": PW})
        self.assertEqual(status, 400)

    def test_update_writes_only_supplied_keys(self):
        fake = _FakeDb(one=_row(), updated=_row(title="New"))
        with patch.object(jroutes, "db", fake):
            _, status = self._post(jroutes.journal_admin_update,
                                   {"password": PW, "id": PID,
                                    "title": "New"})
        self.assertEqual(status, 200)
        wrote = [c for c in fake.calls if c[0] == "update"][0][2]
        self.assertEqual(wrote, {"title": "New"})

    def test_update_unknown_id_404(self):
        with patch.object(jroutes, "db", _FakeDb(one=None)):
            _, status = self._post(jroutes.journal_admin_update,
                                   {"password": PW, "id": PID, "title": "x"})
        self.assertEqual(status, 404)

    def test_update_no_fields_400(self):
        with patch.object(jroutes, "db", _FakeDb(one=_row())):
            _, status = self._post(jroutes.journal_admin_update,
                                   {"password": PW, "id": PID})
        self.assertEqual(status, 400)

    def test_publish_stamps_date_only_when_null(self):
        # already dated -> the author's display date is preserved
        fake = _FakeDb(one=_row(published_at="2020-01-01T00:00:00Z"),
                       updated=_row())
        with patch.object(jroutes, "db", fake):
            self._post(jroutes.journal_admin_publish,
                       {"password": PW, "id": PID})
        wrote = [c for c in fake.calls if c[0] == "update"][0][2]
        self.assertEqual(wrote, {"status": "published"})
        self.assertNotIn("published_at", wrote)

        # never published -> stamp now
        fake2 = _FakeDb(one=_row(published_at=None), updated=_row())
        with patch.object(jroutes, "db", fake2):
            self._post(jroutes.journal_admin_publish,
                       {"password": PW, "id": PID})
        wrote2 = [c for c in fake2.calls if c[0] == "update"][0][2]
        self.assertIn("published_at", wrote2)

    def test_unpublish_keeps_the_date(self):
        fake = _FakeDb(one=_row(), updated=_row(status="draft"))
        with patch.object(jroutes, "db", fake):
            _, status = self._post(jroutes.journal_admin_unpublish,
                                   {"password": PW, "id": PID})
        self.assertEqual(status, 200)
        wrote = [c for c in fake.calls if c[0] == "update"][0][2]
        self.assertEqual(wrote, {"status": "draft"})

    def test_reorder_validates_the_id_list(self):
        fake = _FakeDb()
        with patch.object(jroutes, "db", fake):
            body, status = self._post(jroutes.journal_admin_reorder,
                                      {"password": PW, "ids": ["a", "b"]})
            self.assertEqual(status, 200)
            # Assert the ORDER reached the db in the caller's sequence — that
            # is the contract. (`updated` counts accepted writes, not matched
            # rows; asserting its value here would only test the fake.)
            self.assertEqual(
                [c for c in fake.calls if c[0] == "reorder"][0][1],
                ["a", "b"])
            for bad in (None, [], "a,b", [1, 2], ["ok", ""]):
                _, st = self._post(jroutes.journal_admin_reorder,
                                   {"password": PW, "ids": bad})
                self.assertEqual(st, 400, repr(bad))

    def test_delete(self):
        with patch.object(jroutes, "db", _FakeDb()):
            body, status = self._post(jroutes.journal_admin_delete,
                                      {"password": PW, "id": PID})
        self.assertEqual(status, 200)
        self.assertTrue(body["deleted"])


# ── J-6 media presign ─────────────────────────────────────────────────────

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class PresignUnitTests(unittest.TestCase):

    def _mod(self):
        from services import journal_media as jm
        return jm

    def test_kind_and_content_type_allowlist(self):
        jm = self._mod()
        with self.assertRaises(jm.JournalMediaError):
            jm.presign_put(kind="doc", content_type="application/pdf")
        with self.assertRaises(jm.JournalMediaError):
            # right kind, disallowed type
            jm.presign_put(kind="image", content_type="image/svg+xml")

    def test_refuses_when_storage_unconfigured(self):
        jm = self._mod()
        with patch.object(jm, "journal_media_use_r2", return_value=False):
            with self.assertRaises(jm.JournalMediaError) as cm:
                jm.presign_put(kind="image", content_type="image/png")
        self.assertIn("not configured", str(cm.exception))

    def test_refuses_when_no_public_base_url(self):
        jm = self._mod()
        with patch.object(jm, "journal_media_use_r2", return_value=True), \
             patch.object(jm, "journal_public_base_url", return_value=""):
            with self.assertRaises(jm.JournalMediaError) as cm:
                jm.presign_put(kind="image", content_type="image/png")
        self.assertIn("public base URL", str(cm.exception))

    def test_object_key_is_random_and_never_the_client_filename(self):
        jm = self._mod()
        k1 = jm.build_object_key("image", "image/png", "../../etc/passwd")
        k2 = jm.build_object_key("image", "image/png", "../../etc/passwd")
        self.assertNotEqual(k1, k2)                  # randomized
        self.assertNotIn("passwd", k1)               # filename never echoed
        self.assertNotIn("..", k1)                   # no traversal
        self.assertTrue(k1.startswith("journal/image/"))
        self.assertTrue(k1.endswith(".png"))         # extension preserved

    def test_happy_presign_shape(self):
        jm = self._mod()
        fake_client = SimpleNamespace(
            generate_presigned_url=lambda *a, **kw: "https://r2/put?sig=1")
        with patch.object(jm, "journal_media_use_r2", return_value=True), \
             patch.object(jm, "journal_public_base_url",
                          return_value="https://cdn.example"), \
             patch.object(jm, "journal_bucket_name", return_value="b"), \
             patch.object(jm, "_client", return_value=fake_client):
            out = jm.presign_put(kind="video", content_type="video/mp4",
                                 filename="launch.mp4")
        self.assertEqual(out["upload_url"], "https://r2/put?sig=1")
        self.assertTrue(out["public_url"].startswith("https://cdn.example/journal/video/"))
        # Content-Type is part of the signature -> must be echoed to the client
        self.assertEqual(out["headers"]["Content-Type"], "video/mp4")
        self.assertGreater(out["max_bytes"], 0)

    def test_size_caps_per_kind(self):
        jm = self._mod()
        self.assertLess(jm.max_bytes_for("image"), jm.max_bytes_for("audio"))
        self.assertLess(jm.max_bytes_for("audio"), jm.max_bytes_for("video"))

    def test_classify_kind(self):
        jm = self._mod()
        self.assertEqual(jm.classify_kind("image/png"), "image")
        self.assertEqual(jm.classify_kind("video/mp4"), "video")
        self.assertIsNone(jm.classify_kind("application/zip"))


class PresignRouteTests(_RouteCase):

    def test_bad_kind_is_400(self):
        with patch.object(jroutes, "db", _FakeDb()):
            _, status = self._post(jroutes.journal_admin_presign,
                                   {"password": PW, "kind": "doc",
                                    "content_type": "application/pdf"})
        self.assertEqual(status, 400)

    def test_unconfigured_storage_is_503(self):
        from services import journal_media as jm
        with patch.object(jroutes, "db", _FakeDb()), \
             patch.object(jm, "journal_media_use_r2", return_value=False):
            body, status = self._post(jroutes.journal_admin_presign,
                                      {"password": PW, "kind": "image",
                                       "content_type": "image/png"})
        self.assertEqual(status, 503)
        self.assertEqual(body["code"], "DISABLED")


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class PublishedFilterTranslationTests(unittest.TestCase):
    """THE line that keeps drafts private: `published_only=True` must actually
    emit `status=eq.published` to PostgREST.

    Everything else asserts `published_only=True` was *passed*; this asserts it
    is *honoured*, by running the real db methods against a real PostgREST
    query builder and inspecting the params that would go on the wire.
    """

    def _builder_params(self, method_name, **kwargs):
        """Run the REAL db method against a REAL PostgREST query builder and
        return the params that would go on the wire. Only execute() is stubbed
        — and only after every filter has been applied — so this exercises the
        actual translation, not a mock's memory of it."""
        import postgrest._sync.request_builder as rb
        from postgrest import SyncPostgrestClient
        from services.db import DatabaseService

        captured = {}
        client = SyncPostgrestClient("http://localhost/rest/v1",
                                     schema="public", headers={})
        real_table = client.table

        def _table(name):
            captured["table"] = name
            return real_table(name)

        class _Res:
            data = []
            count = 0

        def _capture_execute(builder_self):
            captured["params"] = dict(builder_self.params)
            return _Res()

        fake_self = SimpleNamespace(
            client=SimpleNamespace(table=_table),
            journal_search_filter=DatabaseService.journal_search_filter,
            _JOURNAL_COLUMNS=DatabaseService._JOURNAL_COLUMNS,
        )
        with patch.object(rb.SyncSelectRequestBuilder, "execute",
                          _capture_execute):
            getattr(DatabaseService, method_name)(fake_self, **kwargs)
        return captured

    def test_public_list_emits_status_eq_published(self):
        cap = self._builder_params("list_journal_posts", published_only=True)
        self.assertEqual(cap["table"], "journal_post")
        self.assertEqual(cap["params"].get("status"), "eq.published")

    def test_public_count_emits_status_eq_published(self):
        cap = self._builder_params("count_journal_posts", published_only=True)
        self.assertEqual(cap["params"].get("status"), "eq.published")

    def test_by_slug_emits_status_eq_published(self):
        cap = self._builder_params("get_journal_post_by_slug",
                                   slug="a-post", published_only=True)
        self.assertEqual(cap["params"].get("status"), "eq.published")
        self.assertEqual(cap["params"].get("slug"), "eq.a-post")

    def test_category_counts_is_published_only_with_no_opt_out(self):
        cap = self._builder_params("journal_category_counts")
        self.assertEqual(cap["params"].get("status"), "eq.published")

    def test_hostile_search_leaves_the_status_filter_intact(self):
        # The or=(...) filter is a SEPARATE param from status; PostgREST ANDs
        # separate params, so no needle can widen past published rows.
        for needle in ("x,status.eq.draft", "x),or=(status.eq.draft", "%"):
            cap = self._builder_params("list_journal_posts",
                                       published_only=True, search=needle)
            self.assertEqual(cap["params"].get("status"), "eq.published",
                             needle)
            self.assertIn("or", cap["params"], needle)
            self.assertEqual(str(cap["params"]["or"]).count("ilike"), 2,
                             needle)

    def test_admin_list_does_not_filter_status(self):
        cap = self._builder_params("list_journal_posts", published_only=False)
        self.assertIsNone(cap["params"].get("status"))

    # ── ordering on the wire (FE amendment 2026-07-25) ────────────────

    def test_admin_order_is_sort_order_asc_then_created_at_desc(self):
        # The CMS list includes DRAFTS (published_at NULL) and every new post
        # starts at sort_order=0, so the tiebreak IS the visible order. A
        # published_at tiebreak would float undated drafts to the top
        # (Postgres DESC = NULLS FIRST) and reshuffle as dates get set.
        cap = self._builder_params(
            "list_journal_posts", published_only=False,
            order_column="sort_order", descending=False,
            tiebreak_column="created_at")
        # A bare column emits no direction modifier — ASC is PostgREST's
        # default — so `sort_order` here IS sort_order ASC.
        self.assertEqual(cap["params"].get("order"),
                         "sort_order,created_at.desc")

    def test_public_curated_order_still_tiebreaks_on_published_at(self):
        # Public rows are all published, so the date is non-NULL and IS the
        # meaningful tiebreak. This must not change.
        cap = self._builder_params(
            "list_journal_posts", published_only=True,
            order_column="sort_order", descending=False)
        self.assertEqual(cap["params"].get("order"),
                         "sort_order,published_at.desc")

    def test_public_default_order_emits_no_duplicate_tiebreak(self):
        cap = self._builder_params("list_journal_posts", published_only=True)
        self.assertEqual(cap["params"].get("order"), "published_at.desc")


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SearchFilterSanitizationTests(unittest.TestCase):
    """The PostgREST or=(...) needle sanitizer — one source of truth shared by
    the list and count queries."""

    def _f(self, needle):
        from services.db import DatabaseService
        return DatabaseService.journal_search_filter(needle)

    def test_plain_needle_builds_both_ilike_terms(self):
        self.assertEqual(self._f("voice"),
                         "title.ilike.%voice%,excerpt.ilike.%voice%")

    def test_condition_separators_are_stripped(self):
        # , ( ) are PostgREST's condition/group separators. After stripping,
        # an injected value stays inside ONE ilike pattern: the filter still
        # has exactly the two terms this function builds.
        for needle in ("x,status.eq.draft", "x),or=(status.eq.draft"):
            out = self._f(needle)
            self.assertEqual(out.count("ilike"), 2, needle)
            self.assertNotIn("status.eq.draft,", out, needle)
            self.assertNotIn("(", out, needle)
            self.assertNotIn(")", out, needle)

    def test_empty_and_separator_only_needles_yield_no_filter(self):
        for needle in (None, "", "   ", ",,,", "()", ",( )"):
            self.assertIsNone(self._f(needle), repr(needle))

    def test_wildcards_pass_through_as_search_breadth_only(self):
        # % and * only widen the match; they cannot add a condition.
        self.assertEqual(self._f("%").count("ilike"), 2)
        self.assertEqual(self._f("*").count("ilike"), 2)


# ── the fence: this feature stays off the live loop ───────────────────────

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class IsolationTests(unittest.TestCase):
    """The Journal is a marketing surface. It must not reach into the
    record → transcribe → coach → read loop, and no F1 module may come to
    depend on it."""

    def test_journal_modules_import_nothing_from_the_loop(self):
        import inspect
        from services import journal as a
        from services import journal_media as b
        from routes import journal as c
        banned = ("best_presentation", "ideal_text", "charisma_snippets",
                  "lab_recording", "moment_suggestions", "say_it_stronger",
                  "delivery_stars", "power_score")
        for mod in (a, b, c):
            src = inspect.getsource(mod)
            for name in banned:
                self.assertNotIn(
                    name, src,
                    f"{mod.__name__} must not reference {name}")

    def test_public_payloads_carry_no_scores(self):
        # AC-9 is about the coaching product, but the invariant is free here:
        # nothing in a Journal payload is a score or verdict.
        import json
        raw = json.dumps(jr.serialize_post(_row()))
        for banned in ("power_score", "charisma", "overall_score", "threat"):
            self.assertNotIn(banned, raw)


if __name__ == "__main__":
    unittest.main()
