"""The cold-open read serves a deck address that still resolves.

FOUNDER, 2026-09-19: "no slide preview", and earlier the same symptom in its
more diagnostic form -- "it was visible for a moment but then gone".

THE DEFECT.  ``publish_for_arc`` bakes ``project.presentation_ref`` into the
immutable document snapshot as the URL stored at upload time, and a snapshot
is immutable on purpose -- so whichever address was current when it was
published is the one served forever after.  Since decks became user content
(DPIA RISK-11, 2026-09-18) that address is a SIGNATURE, and
``refreshed_media_url`` exists exactly because, in its own words, "nothing
depends on a stored URL staying valid".

Every other read of ``presentation_ref`` calls it -- ``routes/v2/arcs.py``,
``routes/v2/user_account.py``, ``routes/v2/coach.py``, and the composing ideal
text read in this same module.  ``/ideal-text/core`` did not.  That asymmetry
is the whole bug, and it explains the flicker exactly: the FE's FIRST load
reads the composing lane and gets a signed deck, and every poll after it reads
THIS lane and gets a dead one.

WHAT IS NOT BEING TRADED AWAY.  The endpoint stays strict.  Re-addressing is
not composing, repairing or persisting: the stored snapshot, its payload and
its ``payload_sha256`` are untouched, and nothing re-hashes the served body --
enrichment and recording-roots bind on the snapshot id.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import auth
from flask import Flask

# Imported for its side effect, and imported HERE: every `@v2_bp.route` has to
# be attached before any app registers the blueprint, and Flask raises rather
# than silently serving a half-registered one.
import routes.v2.explore_ideal_text  # noqa: F401
from routes.v2.blueprint import v2_bp

ARC = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
USER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

STORED = (
    "https://acct.r2.cloudflarestorage.com/coach-feedback-videos/"
    "user_content/willab_presentations/deck.pdf"
    "?X-Amz-Date=20260901T100000Z&X-Amz-Signature=expired"
)
FRESH = (
    "https://acct.r2.cloudflarestorage.com/coach-feedback-videos/"
    "user_content/willab_presentations/deck.pdf"
    "?X-Amz-Date=20260919T100000Z&X-Amz-Signature=minted"
)


def _snapshot(ref):
    payload = {"status": "verified", "text": "The document.", "version": 3}
    if ref is not None:
        payload["presentation_ref"] = ref
    return {
        "id": "snap-1",
        "payload_sha256": "f" * 64,
        "payload": payload,
    }


_OVERLAY = {
    "owner_edit": None,
    "confident_moment_summary": None,
    "confident_moment_summary_status": None,
}


def _app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(v2_bp, url_prefix="/v2")
    return app


class CoreReadReaddressesTheDeck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self._orig_verify = auth.verify_supabase_token
        auth.verify_supabase_token = lambda token: {"sub": USER}

    def tearDown(self):
        auth.verify_supabase_token = self._orig_verify

    def _get(self, snapshot, refresh=lambda ref: FRESH if ref else ref):
        core = {"snapshot": snapshot, "dynamic_overlay": dict(_OVERLAY)}
        with patch("services.db.db.get_ideal_text_document_core_v2",
                   return_value=core), \
             patch("routes.v2.explore_ideal_text.refreshed_media_url",
                   side_effect=refresh) as spy:
            response = self.app.test_client().get(
                f"/v2/explore/arc/{ARC}/ideal-text/core",
                headers={"Authorization": "Bearer t"},
            )
        return response, spy

    def test_a_stored_signature_is_re_minted_before_it_is_served(self):
        # THE BUG: this used to answer STORED, whose signature expired weeks
        # ago, and pdf.js has no way to ask for a better one.
        response, spy = self._get(_snapshot(STORED))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["presentation_ref"], FRESH)
        spy.assert_called_once_with(STORED)

    def test_the_stored_snapshot_is_not_rewritten(self):
        # L1 and the immutability of the snapshot: re-addressing happens on
        # the way out.  What is on disk is exactly what was published.
        snapshot = _snapshot(STORED)
        response, _ = self._get(snapshot)
        self.assertEqual(snapshot["payload"]["presentation_ref"], STORED)
        self.assertEqual(
            response.get_json()["document_snapshot_sha256"], "f" * 64)

    def test_a_deckless_arc_still_reports_no_deck(self):
        # An arc with no deck must not acquire one: the FE reads null here and
        # renders the words alone, which is the correct read, not a failure.
        response, _ = self._get(_snapshot(None))
        self.assertIsNone(response.get_json()["presentation_ref"])

    def test_a_ref_that_cannot_be_read_with_certainty_is_left_alone(self):
        # refreshed_media_url returns anything it cannot place untouched. A
        # deck on a base this cannot parse keeps the address it had rather
        # than being replaced by a guess.
        odd = "https://cdn.example.test/decks/deck.pdf"
        response, _ = self._get(_snapshot(odd), refresh=lambda ref: ref)
        self.assertEqual(response.get_json()["presentation_ref"], odd)

    def test_an_empty_string_is_served_as_no_deck(self):
        # `or None` -- an empty ref is the absence of a deck, and "" would
        # reach pdf.js as a request for the current page.
        response, _ = self._get(_snapshot(""), refresh=lambda ref: ref)
        self.assertIsNone(response.get_json()["presentation_ref"])


class TheRouteStillDoesNotCompose(unittest.TestCase):
    """The endpoint's strictness is the reason it can be trusted cold."""

    def test_the_docstring_no_longer_claims_it_never_signs_media(self):
        # It does now, for exactly one field and for a stated reason. A
        # docstring that still said "does not sign media" would be the next
        # reader's evidence that this lane serves what it was given.
        from routes.v2.explore_ideal_text import (
            v2_explore_get_ideal_text_core as route,
        )
        doc = route.__doc__ or ""
        self.assertNotIn("sign media", doc)
        self.assertIn("RE-ADDRESS", doc)
