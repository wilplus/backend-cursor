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

Run: python3 -m unittest test_moment_suggestions
"""
from __future__ import annotations

import inspect
import json
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

ARC = "a1"
SNIP = "aaaa1111-aaaa-1111-aaaa-111111111111"
SESS = "bbbb2222-bbbb-2222-bbbb-222222222222"


class DirectionResolutionTests(unittest.TestCase):
    def _resolve(self, label, pot):
        from services.moment_direction import resolve_moment_direction
        read = {"potentiometer": pot} if pot is not None else None
        return resolve_moment_direction(label, read)

    def test_coach_override_always_wins(self):
        self.assertEqual(self._resolve("challenge", -0.9), "charisma")
        self.assertEqual(self._resolve("threat", 0.9), "threat")
        # ambiguous = the coach said NEITHER — beats a strong lean
        self.assertIsNone(self._resolve("ambiguous", 0.9))

    def test_potentiometer_fallback(self):
        self.assertEqual(self._resolve(None, 0.5), "charisma")
        self.assertEqual(self._resolve(None, -0.5), "threat")
        self.assertIsNone(self._resolve(None, 0.1))   # neutral band
        self.assertIsNone(self._resolve(None, None))  # no read

    def test_blind_coach_shadow_model_banned(self):
        # The docstring may NAME the ban; the IMPORT is what's banned.
        import services.moment_direction as mod
        src = inspect.getsource(mod)
        self.assertNotIn("from services.learning_serve", src)
        self.assertNotIn("import learning_serve", src)
        self.assertNotIn("predict_direction", src)


class KindResolutionTests(unittest.TestCase):
    def _kind(self, direction, text="clean words", stick=None):
        from services.moment_direction import resolve_suggestion_kind
        return resolve_suggestion_kind(direction, text,
                                       slide_stickiness=stick,
                                       stickiness_max=0.15)

    def test_threat_replaces(self):
        self.assertEqual(self._kind("threat"), "replace")

    def test_clean_charisma_emphasizes(self):
        self.assertEqual(self._kind("charisma"), "emphasize")

    def test_profanity_replaces_even_on_charisma(self):
        self.assertEqual(self._kind("charisma", "this is fucking great"),
                         "replace")

    def test_low_stickiness_replaces_without_direction(self):
        self.assertEqual(self._kind(None, stick=0.1), "replace")
        self.assertEqual(self._kind(None, stick=0.15), "replace")  # inclusive

    def test_ok_stickiness_no_direction_no_star(self):
        self.assertIsNone(self._kind(None, stick=0.6))
        self.assertIsNone(self._kind(None))

    def test_bool_stickiness_never_triggers(self):
        self.assertIsNone(self._kind(None, stick=False))


class ProfanityTests(unittest.TestCase):
    def test_hits_and_case(self):
        from services.text_flags import has_profanity
        self.assertTrue(has_profanity("well SHIT happens"))
        self.assertTrue(has_profanity("Fucking amazing"))

    def test_whole_word_only(self):
        from services.text_flags import has_profanity
        self.assertFalse(has_profanity("the class assesses Scunthorpe"))
        self.assertFalse(has_profanity("shitake mushrooms"))

    def test_non_string(self):
        from services.text_flags import has_profanity
        self.assertFalse(has_profanity(None))
        self.assertFalse(has_profanity(123))


class AssemblyAnchorTests(unittest.TestCase):
    def _assemble(self, extra):
        import services.ideal_text_block as mod
        bp = {"ready": True, "slides": [{
            "text": "a strong line", "snippet_id": SNIP, "session_id": SESS,
            "breakthrough": False, "key_phrases": [],
        }]}
        with patch.object(mod, "assemble_ideal_text_block",
                          wraps=mod.assemble_ideal_text_block):
            with patch("services.best_presentation.build_best_presentation",
                       return_value=bp):
                return mod.assemble_ideal_text_block(
                    ARC, database=object(), extra_anchor_ids=extra)

    def test_suggestion_pick_gets_anchor(self):
        out = self._assemble({SNIP})
        self.assertIn(f"[[moment:{SNIP}|{SESS}]]", out["text"])
        self.assertEqual(out["key_moments"][0]["snippet_id"], SNIP)

    def test_no_extra_no_anchor(self):
        out = self._assemble(None)
        self.assertNotIn("[[moment:", out["text"])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class GenerationTests(unittest.TestCase):
    def _gen(self, kind, parsed):
        from services import moment_suggestions as ms
        result = type("R", (), {"parsed": parsed, "text": ""})()
        with patch("services.llm.chat_complete", return_value=result):
            return ms.generate_moment_suggestion(kind, "the moment text",
                                                 audience="investors")

    def test_emphasize_shape(self):
        out = self._gen("emphasize", {"why": "It lands because it is plain.",
                                      "replacement": None})
        self.assertEqual(out["why"], "It lands because it is plain.")
        self.assertIsNone(out["replacement"])

    def test_replace_without_replacement_is_dead(self):
        out = self._gen("replace", {"why": "Swap it.", "replacement": ""})
        self.assertIsNone(out)

    def test_guard_kills_digit_copy(self):
        # _guard_copy (AC-9) kills digit-carrying strings → why drops.
        out = self._gen("emphasize", {"why": "You scored 87 here",
                                      "replacement": None})
        self.assertIsNone(out)   # nothing honest left

    def test_bad_kind_or_transcript(self):
        from services.moment_suggestions import generate_moment_suggestion
        self.assertIsNone(generate_moment_suggestion("boost", "text"))
        self.assertIsNone(generate_moment_suggestion("replace", "   "))


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class AppliedMapAndFoldTests(unittest.TestCase):
    def test_last_action_wins(self):
        rows = [
            {"snippet_id": SNIP, "target": "moment_emphasize",
             "action": "applied"},
            {"snippet_id": SNIP, "target": "moment_emphasize",
             "action": "reverted"},
        ]
        with patch.object(v2.db, "get_suggestion_feedback_by_session",
                          return_value=rows):
            self.assertEqual(v2._moment_applied_map([SESS]), {})
        with patch.object(v2.db, "get_suggestion_feedback_by_session",
                          return_value=list(reversed(rows))):
            self.assertEqual(v2._moment_applied_map([SESS]), {SNIP: True})

    def test_fold_emphasize_and_replace(self):
        text = (f"Start. [[moment:{SNIP}|{SESS}]]shaky bit[[/moment]] end.")
        folded = v2._fold_applied_moments(text, [{
            "id": SNIP, "take_session_id": SESS, "applied": True,
            "suggestion": {"kind": "replace", "replacement": "steady bit"},
        }])
        self.assertIn(f"[[moment:{SNIP}|{SESS}]]steady bit[[/moment]]",
                      folded)
        self.assertNotIn("shaky bit", folded)
        folded2 = v2._fold_applied_moments(text, [{
            "id": SNIP, "take_session_id": SESS, "applied": True,
            "suggestion": {"kind": "emphasize"},
        }])
        self.assertIn("**{{orange:shaky bit}}**", folded2)

    def test_unapplied_untouched(self):
        text = f"[[moment:{SNIP}|{SESS}]]x[[/moment]]"
        self.assertEqual(v2._fold_applied_moments(text, [{
            "id": SNIP, "take_session_id": SESS, "applied": False,
            "suggestion": {"kind": "replace", "replacement": "y"},
        }]), text)


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
            with patch.object(v2, "_arc_owned_by_caller",
                              return_value=(True, [])), \
                 patch.object(v2, "_single_deliverable_enabled",
                              return_value=True), \
                 patch.object(v2, "_moment_suggestions_enabled",
                              return_value=stars), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=row), \
                 patch.object(v2.db, "get_user_ideal_edit",
                              return_value=edit), \
                 patch.object(v2.db, "get_moment_unlock",
                              return_value=None), \
                 patch.object(v2.db, "get_moment_suggestions_by_arc",
                              return_value=(sugs or {})), \
                 patch.object(v2.db, "get_coach_snippet_drafts",
                              return_value=(drafts or [])), \
                 patch.object(v2.db, "get_snippets_by_session",
                              return_value=[{
                                  "id": SNIP,
                                  "audio_segment_path": "https://cdn/take.webm",
                                  "start_offset_ms": 1500,
                                  "duration_ms": 900,
                              }]), \
                 patch.object(v2.db, "get_suggestion_feedback_by_session",
                              return_value=(feedback or [])), \
                 patch.object(v2.db, "get_user_arc_ideal_notes",
                              return_value=None), \
                 patch.object(v2.db, "upsert_coach_arc_ideal_text") as m_can, \
                 patch.object(v2.db, "persist_auto_ideal_text") as m_auto:
                out = v2.v2_explore_get_ideal_text.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                # L1: serving never writes the canonical.
                m_can.assert_not_called()
                m_auto.assert_not_called()
                return resp.get_json(), status

    def _sug(self, kind="replace", replacement="steady words"):
        return {SNIP: {"snippet_id": SNIP, "arc_id": ARC, "kind": kind,
                       "replacement_text": replacement,
                       "why": "It reads calmer.", "trigger": "threat"}}

    def test_grey_suggestion_star(self):
        body, status = self._get(sugs=self._sug())
        self.assertEqual(status, 200)
        m = body["key_moments"][0]
        self.assertEqual(m["star"], "suggestion")
        self.assertEqual(m["suggestion"]["kind"], "replace")
        self.assertEqual(m["suggestion"]["replacement"], "steady words")
        self.assertFalse(m["applied"])
        self.assertEqual(m["anchor"], "the turn")   # unapplied → original
        # BOTH id keys: `snippet_id` is what the feedback POST keys on
        # (audit 2026-07-18 — its absence sent an empty snippet id).
        self.assertEqual(m["snippet_id"], SNIP)
        self.assertEqual(m["id"], SNIP)

    def test_served_text_has_no_moment_wrappers_and_anchor_is_plain(self):
        # THE audit's headline gap: an anchor inside a [[moment:…]] token is
        # refused by the FE segmenter → every star lost + free content sold.
        body, _ = self._get(sugs=self._sug())
        self.assertNotIn("[[moment:", body["text"])
        self.assertNotIn("[[/moment]]", body["text"])
        m = body["key_moments"][0]
        self.assertIn(m["anchor"], body["text"])   # plain-text occurrence

    def test_free_snippet_playback_fields(self):
        body, _ = self._get(sugs=self._sug())
        m = body["key_moments"][0]
        self.assertEqual(m["snippet_audio_ref"], "https://cdn/take.webm")
        self.assertEqual(m["start_offset_ms"], 1500)
        self.assertEqual(m["duration_ms"], 900)

    def test_applied_suggestion_emits_no_star(self):
        feedback = [{"snippet_id": SNIP, "target": "moment_replace",
                     "action": "applied"}]
        body, _ = self._get(sugs=self._sug(), feedback=feedback)
        m = body["key_moments"][0]
        self.assertNotIn("star", m)          # consumed — already in the text
        self.assertNotIn("suggestion", m)

    def test_verified_star_beats_suggestion(self):
        drafts = [{"snippet_id": SNIP, "surfaced": True,
                   "note": "Coach note",
                   "breakthrough_video_ref": "https://x/v.mp4"}]
        body, _ = self._get(sugs=self._sug(), drafts=drafts)
        m = body["key_moments"][0]
        self.assertEqual(m["star"], "verified")
        self.assertTrue(m["coach"]["has_video"])
        self.assertNotIn("suggestion", m)
        # content itself is NOT here (paid moments GET serves it)
        self.assertNotIn("Coach note", json.dumps(body))

    def test_applied_replace_folds_text_and_anchor_matches(self):
        feedback = [{"snippet_id": SNIP, "target": "moment_replace",
                     "action": "applied"}]
        body, _ = self._get(sugs=self._sug(), feedback=feedback)
        self.assertIn("steady words", body["text"])
        self.assertNotIn("the turn", body["text"])
        m = body["key_moments"][0]
        self.assertTrue(m["applied"])
        self.assertEqual(m["anchor"], "steady words")   # matches served text
        self.assertIn(m["anchor"], body["text"])

    def test_applied_emphasize_folds_single_accent_marker(self):
        # NEVER nested (**{{orange:…}}**): the FE's marker parser is FLAT and
        # printed the raw syntax to the student (audit 2026-07-18).
        feedback = [{"snippet_id": SNIP, "target": "moment_emphasize",
                     "action": "applied"}]
        body, _ = self._get(sugs=self._sug(kind="emphasize",
                                           replacement=None),
                            feedback=feedback)
        self.assertIn("{{orange:the turn}}", body["text"])
        self.assertNotIn("**{{orange:", body["text"])

    def test_user_edit_wins_wholesale_no_fold(self):
        feedback = [{"snippet_id": SNIP, "target": "moment_replace",
                     "action": "applied"}]
        body, _ = self._get(
            sugs=self._sug(), feedback=feedback,
            edit={"text": "MY OWN FULL EDIT", "version": 2,
                  "updated_at": "t"})
        self.assertEqual(body["text"], "MY OWN FULL EDIT")
        self.assertNotIn("steady words", body["text"])

    def test_flag_off_no_star_keys(self):
        body, _ = self._get(stars=False, sugs=self._sug())
        m = body["key_moments"][0]
        self.assertNotIn("star", m)
        self.assertNotIn("suggestion", m)
        self.assertNotIn("applied", m)

    def test_ac9_score_free(self):
        body, _ = self._get(sugs=self._sug())
        raw = json.dumps(body)
        for banned in ("potentiometer", "acoustic_read", "overall_score",
                       "slide_stickiness", "rank", "charisma score"):
            self.assertNotIn(banned, raw)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SuggestionTargetTests(unittest.TestCase):
    def test_moment_targets_registered(self):
        self.assertIn("moment_emphasize", v2._SUGGESTION_TARGETS)
        self.assertIn("moment_replace", v2._SUGGESTION_TARGETS)


if __name__ == "__main__":
    unittest.main()
