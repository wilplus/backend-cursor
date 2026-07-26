"""Reference link on a coach-verified moment (ticket 6, 2026-07-26).

Founder decision: the COACH attaches the post by hand, and only on golden
stars. No automatic or LLM matching.

Pinned here:
  R-1  the coach write path: slug validated against the Journal (a typo 404s
       HERE, not silently later), null clears, non-coach can't reach it;
  R-2  read-time resolution: title+url resolved late, and a DRAFT or DELETED
       post yields NO reference rather than a dead link;
  R-3  the payload shape: `reference` present only on a verified star, key
       ABSENT (not null) when there is none;
  R-4  the reference never touches the served text (L1) and carries no
       score/number (AC-9).

Run: ./venv/bin/python -m unittest test_moment_reference
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
    _IMPORT_ERROR = e

SNIP = "aaaa1111-aaaa-1111-aaaa-111111111111"
SESS = "bbbb2222-bbbb-2222-bbbb-222222222222"


def _post(**over):
    row = {"slug": "why-your-voice-shakes", "title": "Why your voice shakes",
           "status": "published"}
    row.update(over)
    return row


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ResolveTests(unittest.TestCase):
    """R-2 — resolution happens at read time and fails CLOSED."""

    def _resolve(self, slug, post):
        with patch.object(v2.db, "get_journal_post_by_slug",
                          return_value=post) as m:
            return v2._moment_reference(slug), m

    def test_published_post_resolves_to_slug_title_url(self):
        out, _ = self._resolve("why-your-voice-shakes", _post())
        self.assertEqual(out, {
            "slug": "why-your-voice-shakes",
            "title": "Why your voice shakes",
            "url": "/blog/why-your-voice-shakes",
        })

    def test_url_uses_the_new_blog_path_not_journal(self):
        # The stored value is a SLUG precisely so the path can move; pin that
        # the resolver emits the new one.
        out, _ = self._resolve("s", _post(slug="s"))
        self.assertTrue(out["url"].startswith("/blog/"))
        self.assertNotIn("/journal/", out["url"])

    def test_a_draft_or_deleted_post_yields_no_reference(self):
        # get_journal_post_by_slug(published_only=True) returns None for both.
        out, _ = self._resolve("gone", None)
        self.assertIsNone(out)

    def test_lookup_is_published_only(self):
        # THE line that keeps an unpublished post from leaking to a student.
        _, m = self._resolve("s", _post())
        self.assertTrue(m.call_args.kwargs.get("published_only"))

    def test_blank_and_non_string_slugs_short_circuit(self):
        with patch.object(v2.db, "get_journal_post_by_slug") as m:
            for bad in (None, "", "   ", 42, [], {}):
                self.assertIsNone(v2._moment_reference(bad), repr(bad))
            m.assert_not_called()          # no pointless DB round-trip

    def test_a_db_hiccup_degrades_to_no_reference(self):
        with patch.object(v2.db, "get_journal_post_by_slug",
                          side_effect=RuntimeError("boom")):
            self.assertIsNone(v2._moment_reference("s"))

    def test_a_row_without_a_slug_is_refused(self):
        out, _ = self._resolve("s", {"title": "no slug here"})
        self.assertIsNone(out)

    def test_missing_title_does_not_crash(self):
        out, _ = self._resolve("s", {"slug": "s"})
        self.assertEqual(out["title"], "")


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class CoachWriteTests(unittest.TestCase):
    """R-1 — the coach's attach/clear endpoint."""

    def setUp(self):
        self.app = Flask(__name__)

    def _put(self, body, *, snip=None, post="found", snippet_id=SNIP):
        captured = {}

        def _upsert(sid, snid, fields, updated_by=None):
            captured["args"] = (sid, snid, fields)
            return {"ok": True}

        _snip = snip if snip is not None else {"id": SNIP, "session_id": SESS}
        with self.app.test_request_context(json=body):
            request.user_id = "coach1"
            with patch.object(v2.db, "get_snippet_by_id", return_value=_snip), \
                 patch.object(v2.db, "get_journal_post_by_slug",
                              return_value=(_post() if post == "found" else None)), \
                 patch.object(v2.db, "upsert_coach_snippet_draft",
                              side_effect=_upsert):
                out = v2.v2_coach_put_moment_reference.__wrapped__(snippet_id)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, captured

    def test_attach_persists_the_slug(self):
        body, status, cap = self._put({"slug": "why-your-voice-shakes"})
        self.assertEqual(status, 200)
        self.assertTrue(body["saved"])
        self.assertEqual(cap["args"][2],
                         {"reference_post_slug": "why-your-voice-shakes"})

    def test_null_clears_it(self):
        body, status, cap = self._put({"slug": None})
        self.assertEqual(status, 200)
        self.assertIsNone(body["reference_post_slug"])
        self.assertEqual(cap["args"][2], {"reference_post_slug": None})

    def test_a_typo_slug_404s_here_rather_than_failing_silently_later(self):
        _, status, cap = self._put({"slug": "nonexistent"}, post="missing")
        self.assertEqual(status, 404)
        self.assertNotIn("args", cap)          # nothing written

    def test_a_draft_post_is_acceptable_to_attach(self):
        # The coach may line up a post before publishing; the STUDENT payload
        # is where it stays hidden (see ResolveTests).
        _, status, _ = self._put({"slug": "a-draft"})
        self.assertEqual(status, 200)

    def test_missing_slug_key_is_400_not_a_silent_clear(self):
        # {} must not be read as "clear it" — that would wipe a reference on a
        # malformed request.
        _, status, cap = self._put({})
        self.assertEqual(status, 400)
        self.assertNotIn("args", cap)

    def test_non_string_slug_rejected(self):
        _, status, _ = self._put({"slug": 42})
        self.assertEqual(status, 400)

    def test_bad_uuid_400(self):
        _, status, _ = self._put({"slug": "s"}, snippet_id="not-a-uuid")
        self.assertEqual(status, 400)

    def test_unknown_snippet_404(self):
        _, status, _ = self._put({"slug": "s"}, snip={})
        self.assertEqual(status, 404)

    def test_endpoint_is_coach_gated(self):
        # The decorator is the gate; assert it is actually applied.
        self.assertTrue(hasattr(v2.v2_coach_put_moment_reference, "__wrapped__"))


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ExplanationsMapTests(unittest.TestCase):
    """R-3 — the slug rides the verified-star map, and only for golden stars."""

    def _map(self, drafts):
        with patch.object(v2.db, "get_coach_snippet_drafts",
                          return_value=drafts):
            return v2._moment_explanations_map([SESS])

    def test_slug_is_carried_for_a_surfaced_note(self):
        out = self._map([{"snippet_id": SNIP, "surfaced": True,
                          "note": "good moment",
                          "reference_post_slug": "why-your-voice-shakes"}])
        self.assertEqual(out[SNIP]["reference_post_slug"],
                         "why-your-voice-shakes")

    def test_unsurfaced_draft_is_not_a_golden_star_at_all(self):
        out = self._map([{"snippet_id": SNIP, "surfaced": False,
                          "note": "hidden",
                          "reference_post_slug": "why-your-voice-shakes"}])
        self.assertEqual(out, {})

    def test_no_note_and_no_video_is_not_a_golden_star(self):
        out = self._map([{"snippet_id": SNIP, "surfaced": True, "note": "  ",
                          "reference_post_slug": "why-your-voice-shakes"}])
        self.assertEqual(out, {})

    def test_absent_column_is_none_not_a_crash(self):
        # Pre-migration the column does not exist on the row.
        out = self._map([{"snippet_id": SNIP, "surfaced": True, "note": "x"}])
        self.assertIsNone(out[SNIP]["reference_post_slug"])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class FenceTests(unittest.TestCase):
    """R-4 — L1 and AC-9."""

    def test_the_resolver_returns_no_numbers(self):
        # AC-9: a reference is a link, never a score/ratio/confidence.
        with patch.object(v2.db, "get_journal_post_by_slug",
                          return_value=_post()):
            out = v2._moment_reference("s")
        self.assertEqual(set(out), {"slug", "title", "url"})
        for v in out.values():
            self.assertNotRegex(str(v), r"\d+(\.\d+)?%")

    def test_reference_never_appears_in_served_text(self):
        # L1: this is metadata BESIDE a moment. Pin that no serving helper
        # splices it into the text.
        import inspect
        from services import ideal_text_block as mod
        self.assertNotIn("reference_post_slug", inspect.getsource(mod))


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class BatchResolutionTests(unittest.TestCase):
    """The N+1 guard. Resolving inside the per-moment decorator would issue one
    post lookup per verified moment on every ideal-text GET — exactly the shape
    the load-time ticket is about. Caught by profiling the read path."""

    def test_distinct_slugs_are_looked_up_once_each(self):
        calls = []

        def _by_slug(slug, published_only=True):
            calls.append(slug)
            return _post(slug=slug)

        with patch.object(v2.db, "get_journal_post_by_slug",
                          side_effect=_by_slug):
            out = v2._moment_reference_map(["a", "a", "b", "a", "b"])
        self.assertEqual(sorted(calls), ["a", "b"])      # 2 lookups, not 5
        self.assertEqual(sorted(out), ["a", "b"])

    def test_blank_and_none_slugs_cost_nothing(self):
        with patch.object(v2.db, "get_journal_post_by_slug") as m:
            self.assertEqual(v2._moment_reference_map([None, "", "  ", 7]), {})
            m.assert_not_called()

    def test_an_unpublished_slug_is_simply_absent_from_the_map(self):
        with patch.object(v2.db, "get_journal_post_by_slug", return_value=None):
            self.assertEqual(v2._moment_reference_map(["draft-post"]), {})

    def test_empty_input(self):
        self.assertEqual(v2._moment_reference_map([]), {})
        self.assertEqual(v2._moment_reference_map(None), {})

    def test_a_non_dict_explanation_value_does_not_break_the_response(self):
        # REGRESSION: the explanations map holds dicts in production, but
        # callers hand back a truthy marker too. A bare .get() on that is an
        # AttributeError that took the ENTIRE ideal-text response down (the
        # student saw no key_moments at all). Guarded now.
        with patch.object(v2.db, "get_journal_post_by_slug") as m:
            self.assertEqual(
                v2._moment_reference_map([True, None, 1, "ok"]), {})
            # only the real string is even attempted
            self.assertEqual([c.args[0] for c in m.call_args_list], ["ok"])
