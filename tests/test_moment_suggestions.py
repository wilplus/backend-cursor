"""willab — star suggestions on the SD ideal text (founder 2026-07-18).

Pinned here:
  * direction resolution: coach label ALWAYS wins (incl. ambiguous = an
    explicit 'neither'); else the deterministic potentiometer; the shadow
    model is BANNED from the module (blind-coach, source-pinned);
  * kind resolution: REPLACE = threat | profanity | very-low stickiness
    (union — a charisma lean with a swear still replaces); EMPHASIZE only
    for a clean charisma lean;
  * generation: guarded strings, a replace without a replacement is dead;
  * assembly: suggestion-flagged picks get in-text anchors;
  * the student GET: verified (orange) beats suggestion (grey); applied
    folds into the DISPLAYED text only (emphasize -> **{{orange:...}}**,
    replace -> swapped span), anchors always match the served text, the
    canonical row is never written (L1), user_text edit wins wholesale;
  * flag OFF = no star keys at all.

Run: python3 -m unittest tests.test_moment_suggestions
"""
from __future__ import annotations

import inspect
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


class ConfidenceResolutionTests(unittest.TestCase):
    """SPEC §7.2 / §17 — the star lane routes on ``confidence``.

    It used to route on ``charisma`` / ``threat``, resolved from
    ``acoustic_read.tone_hint``. That construct had no written operational
    definition, and §17 names charisma explicitly as something ``confidence``
    must NOT be folded together with — so an undefined subjective label was
    deciding, on every take with no human in the loop, whether a moment got a
    replace star, an emphasize star, or silence."""

    def _resolve(self, score):
        from services.moment_confidence import resolve_moment_confidence
        metrics = ({"voice_confidence": {"score": score,
                                         "version": "voice-confidence-universal-v3"}}
                   if score is not None else None)
        return resolve_moment_confidence(metrics)


    def test_blind_coach_shadow_model_banned(self):
        # The docstring may NAME the ban; the IMPORT is what's banned.
        import services.moment_confidence as mod
        src = inspect.getsource(mod)
        self.assertNotIn("from services.learning_serve", src)
        self.assertNotIn("import learning_serve", src)
        self.assertNotIn("predict_direction", src)


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
            with patch("routes.v2.explore_ideal_text._arc_owned_by_caller",
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

    # ── THE MANAGER ENGINE IS THE SOLE GATEKEEPER (founder 2026-08-10:
    # "no other exist, older feedback system should be ripped off"). The
    # machine star/suggestion branches that served these rows unbudgeted
    # from key_moments are GONE — the same moment_suggestions rows now
    # reach the student ONLY through the gated `changes` lane. These tests
    # pin the rip per lane: the moment keeps its anchor, ids and playback;
    # it never carries a star or a suggestion. ──

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


    def test_ac9_score_free(self):
        body, _ = self._get(sugs=self._sug())
        raw = json.dumps(body)
        for banned in ("potentiometer", "acoustic_read", "overall_score",
                       "slide_stickiness", "rank", "charisma score"):
            self.assertNotIn(banned, raw)


# ── merged from tests/test_moment_suggestions_funnel.py (audit Q-T9) ──


if __name__ == "__main__":
    unittest.main()
