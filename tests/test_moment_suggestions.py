"""
STORY    As a speaker, I want my Ideal Text read to carry no star or
         suggestion outside the gated changes lane and no scores, so that I
         see only words and the latest text.
OUTCOME
  O1  Whatever lane a stored moment suggestion came from (replace,
      emphasize, structure), the GET serves the moment with its anchor and
      playback identity but no star and no suggestion.
  O2  The GET serves the text with no score, rank or internal read
      (Never-1: no scores, numbers or verdicts shown to speakers).
  O3  Serving never writes the canonical or auto Ideal Text (L1, Never-5).
PROVES   O1 -> test_no_lane_serves_a_star_or_suggestion
         O2 -> test_ac9_score_free
         O3 -> test_no_lane_serves_a_star_or_suggestion, test_ac9_score_free
               (asserted inside _get on every read)
WHY      Founder 2026-08-10: the old star lane is ripped; moment suggestions
         reach the speaker only through the gated ``changes`` lane.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

try:
    from flask import Flask, request

    from routes.v2 import explore_ideal_text as v2_explore_ideal_text
    from services.db import db as v2_db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e

ARC = "a1"
SNIP = "aaaa1111-aaaa-1111-aaaa-111111111111"
SESS = "bbbb2222-bbbb-2222-bbbb-222222222222"


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class StudentGetStarTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.text = (f"Hello. [[moment:{SNIP}|{SESS}]]the turn[[/moment]] "
                     "goodbye.")

    def _get(self, *, stars=True, sugs=None, drafts=None, feedback=None,
             edit=None):
        row = {"arc_id": ARC, "text": self.text, "auto_text": self.text,
               "updated_by": None, "approved_at": None, "version": 2,
               "verified_version": None, "verified_text": None}
        with self.app.test_request_context():
            request.user_id = "u1"
            # Every read not stubbed below fails at once, the way an outage
            # does; the GET must degrade, not wait on the network.
            with patch("postgrest.utils.SyncClient.request",
                       side_effect=ConnectionError("offline in tests")), \
                 patch("routes.v2.explore_ideal_text._arc_owned_by_caller",
                              return_value=(True, [])), \
                 patch("routes.v2.explore_ideal_text._moment_suggestions_enabled",
                              return_value=stars), \
                 patch.object(v2_db.ideal_text, "get_coach_arc_ideal_text",
                              return_value=row), \
                 patch.object(v2_db, "get_user_ideal_edit",
                              return_value=edit), \
                 patch.object(v2_db, "get_moment_unlock",
                              return_value=None), \
                 patch.object(v2_db, "get_moment_suggestions_by_arc",
                              return_value=(sugs or {})), \
                 patch.object(v2_db, "get_coach_snippet_drafts",
                              return_value=(drafts or [])), \
                 patch.object(v2_db, "get_snippets_by_session",
                              return_value=[{
                                  "id": SNIP,
                                  "audio_segment_path": "https://cdn/take.webm",
                                  "start_offset_ms": 1500,
                                  "duration_ms": 900,
                              }]), \
                 patch.object(v2_db, "get_suggestion_feedback_by_session",
                              return_value=(feedback or [])), \
                 patch.object(v2_db, "get_user_arc_ideal_notes",
                              return_value=None), \
                 patch.object(v2_db.ideal_text, "upsert_coach_arc_ideal_text") as m_can, \
                 patch.object(v2_db, "persist_auto_ideal_text") as m_auto:
                out = v2_explore_ideal_text.v2_explore_get_ideal_text.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                # L1: serving never writes the canonical.
                m_can.assert_not_called()
                m_auto.assert_not_called()
                return resp.get_json(), status

    def _sug(self, kind="replace", replacement="steady words",
             trigger="threat"):
        return {SNIP: {"snippet_id": SNIP, "arc_id": ARC, "kind": kind,
                       "replacement_text": replacement,
                       "why": "It reads calmer.", "trigger": trigger}}

    # The manager engine is the sole gatekeeper: these rows reach the
    # speaker only through the gated `changes` lane, never as a star on a
    # key moment (founder 2026-08-10).

    def _serves_no_star(self, body):
        m = body["key_moments"][0]
        self.assertNotIn("star", m)
        self.assertNotIn("suggestion", m)
        # The moment itself stays — playback + album identity survive.
        self.assertEqual(m["snippet_id"], SNIP)
        self.assertEqual(m["id"], SNIP)
        self.assertIn(m["anchor"], body["text"])
        return m

    def _struct(self, device="contrast", quote="the turn"):
        return {SNIP: {"snippet_id": SNIP, "arc_id": ARC, "kind": "structure",
                       "replacement_text": None, "why": quote,
                       "trigger": device}}

    def test_no_lane_serves_a_star_or_suggestion(self):
        for lane in (self._sug(),
                     self._sug(kind="emphasize", replacement=None,
                               trigger="confident"),
                     self._struct()):
            body, status = self._get(sugs=lane)
            self.assertEqual(status, 200)
            self._serves_no_star(body)

    def test_ac9_score_free(self):
        body, _ = self._get(sugs=self._sug())
        # The speaker gets their words (markup stripped) and the moment.
        self.assertEqual(body["text"], "Hello. the turn goodbye.")
        self._serves_no_star(body)
        raw = json.dumps(body)
        for banned in ("potentiometer", "acoustic_read", "overall_score",
                       "slide_stickiness", "rank", "charisma score"):
            self.assertNotIn(banned, raw)


if __name__ == "__main__":
    unittest.main()
