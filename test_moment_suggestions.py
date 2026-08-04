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

    def test_strategic_context_rides_the_payload_as_speaker_intent(self):
        # ④ step 5 (2026-07-24): the speaker's setup note reaches the model
        # as `speaker_intent` background — present only when non-blank.
        from services import moment_suggestions as ms
        cap = {}

        def _capture(**kwargs):
            cap.update(kwargs)
            return type("R", (), {"parsed": {"why": "good", "replacement": None},
                                  "text": ""})()

        with patch("services.llm.chat_complete", side_effect=_capture):
            ms.generate_moment_suggestion(
                "emphasize", "the moment", audience="investors",
                strategic_context="the board decides the raise")
        self.assertIn("the board decides the raise", cap.get("user") or "")
        self.assertIn("speaker_intent", cap.get("user") or "")

    def test_context_document_rides_the_payload_as_project_background(self):
        # X-1 v2 (2026-07-25): the attached document reaches the model as
        # BACKGROUND for terminology only — never as a source of new claims.
        from services import moment_suggestions as ms
        cap = {}

        def _capture(**kwargs):
            cap.update(kwargs)
            return type("R", (), {"parsed": {"why": "good", "replacement": None},
                                  "text": ""})()

        with patch("services.llm.chat_complete", side_effect=_capture):
            ms.generate_moment_suggestion(
                "emphasize", "the moment", audience="investors",
                context_document="Our retention held through the pilot.")
        user = cap.get("user") or ""
        self.assertIn("project_background", user)
        self.assertIn("retention held through the pilot", user)

    def test_context_document_excerpt_is_capped(self):
        # It rides EVERY snippet's prompt, so an uncapped 40k-char doc would
        # multiply token cost by the snippet count.
        from services import moment_suggestions as ms
        cap = {}

        def _capture(**kwargs):
            cap.update(kwargs)
            return type("R", (), {"parsed": {"why": "ok", "replacement": None},
                                  "text": ""})()

        with patch("services.llm.chat_complete", side_effect=_capture):
            ms.generate_moment_suggestion(
                "emphasize", "the moment",
                context_document="x" * 40000)
        payload = json.loads(cap.get("user") or "{}")
        self.assertLessEqual(len(payload["project_background"]),
                             ms._MAX_DOC_EXCERPT)

    def test_blank_context_document_is_omitted(self):
        from services import moment_suggestions as ms
        cap = {}

        def _capture(**kwargs):
            cap.update(kwargs)
            return type("R", (), {"parsed": {"why": "ok", "replacement": None},
                                  "text": ""})()

        with patch("services.llm.chat_complete", side_effect=_capture):
            ms.generate_moment_suggestion("emphasize", "the moment",
                                          context_document="   ")
        self.assertNotIn("project_background", cap.get("user") or "")

    def test_system_prompt_forbids_importing_facts_from_the_document(self):
        # The anti-hallucination pin: background for terminology, never a
        # source of numbers/names the speaker did not say.
        from services import moment_suggestions as ms
        self.assertIn("project_background", ms._SYSTEM)
        self.assertIn("Never introduce a fact", ms._SYSTEM)

    def test_blank_strategic_context_is_omitted_from_payload(self):
        from services import moment_suggestions as ms
        cap = {}

        def _capture(**kwargs):
            cap.update(kwargs)
            return type("R", (), {"parsed": {"why": "good", "replacement": None},
                                  "text": ""})()

        with patch("services.llm.chat_complete", side_effect=_capture):
            ms.generate_moment_suggestion(
                "emphasize", "the moment", audience="investors",
                strategic_context="   ")
        self.assertNotIn("speaker_intent", cap.get("user") or "")

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
class StructuralDetectionTests(unittest.TestCase):
    TRANS = "It is not about winning, it is about growing every single day."

    def _detect(self, parsed, transcript=None):
        from services import moment_suggestions as ms
        result = type("R", (), {"parsed": parsed, "text": ""})()
        with patch("services.llm.chat_complete", return_value=result):
            return ms.detect_structural_device(transcript or self.TRANS)

    def test_contrast_with_verbatim_quote(self):
        out = self._detect({"device": "contrast",
                            "quote": "not about winning, it is about growing"})
        self.assertEqual(out["device"], "contrast")
        self.assertIn(out["quote"].lower(), self.TRANS.lower())

    def test_quote_not_a_substring_is_dropped(self):
        # THE anti-hallucination pin: an invented quote → no star.
        out = self._detect({"device": "list_of_three",
                            "quote": "faith, hope, and charity"})
        self.assertIsNone(out)

    def test_case_insensitive_substring_ok(self):
        out = self._detect({"device": "contrast",
                            "quote": "NOT ABOUT WINNING"})
        self.assertIsNotNone(out)

    def test_none_device_is_dropped(self):
        self.assertIsNone(self._detect({"device": "none", "quote": ""}))
        self.assertIsNone(self._detect({"device": "metaphor",
                                        "quote": "growing every single day"}))

    def test_blank_transcript(self):
        from services.moment_suggestions import detect_structural_device
        self.assertIsNone(detect_structural_device("   "))


class StructuralPassTests(unittest.TestCase):
    """The second pass: only no-acoustic-star snippets, own cap, flag-gated,
    acoustic stars never displaced."""

    class _Db:
        def __init__(self):
            self.calls = []

        def upsert_moment_suggestion(self, snip, arc, kind, repl, why, trig):
            self.calls.append((snip, kind, why, trig))
            return True

    def _run(self, candidates, *, flag="1", cap=2, detect=None):
        import os
        from services import moment_suggestions as ms
        db = self._Db()
        _det = detect or (lambda t, user_id=None: {
            "device": "contrast", "quote": t})
        with patch.dict(os.environ, {"STRUCTURAL_STARS_ENABLED": flag}), \
             patch.object(ms, "detect_structural_device", side_effect=_det), \
             patch("config.Config") as MC:
            MC.return_value.STRUCTURAL_STARS_MAX_PER_TAKE = cap
            n = ms._generate_structural(db, "arc1", candidates)
        return n, db

    def test_stores_up_to_cap(self):
        cands = [("s1", "a not b"), ("s2", "x not y"), ("s3", "p not q")]
        n, db = self._run(cands, cap=2)
        self.assertEqual(n, 2)                      # capped
        self.assertEqual([c[1] for c in db.calls], ["structure", "structure"])
        self.assertEqual([c[3] for c in db.calls], ["contrast", "contrast"])

    def test_flag_off_stores_nothing(self):
        n, db = self._run([("s1", "a not b")], flag="0")
        self.assertEqual(n, 0)
        self.assertEqual(db.calls, [])

    def test_no_device_no_store(self):
        n, db = self._run([("s1", "plain sentence")],
                          detect=lambda t, user_id=None: None)
        self.assertEqual(n, 0)

    def test_quote_is_stored_as_why_verbatim(self):
        n, db = self._run([("s1", "it is not X, it is Y")], cap=1)
        self.assertEqual(db.calls[0][2], "it is not X, it is Y")  # why=quote


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
        # SINGLE accent marker — never nested (the flat FE parser printed
        # a nested `**{{orange:…}}**` as raw syntax to the student).
        self.assertIn("{{orange:shaky bit}}", folded2)
        self.assertNotIn("**{{orange:", folded2)

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
            with patch("routes.v2.explore_ideal_text._arc_owned_by_caller",
                              return_value=(True, [])), \
                 patch("routes.v2.explore_ideal_text._moment_suggestions_enabled",
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

    def _sug(self, kind="replace", replacement="steady words",
             trigger="threat"):
        return {SNIP: {"snippet_id": SNIP, "arc_id": ARC, "kind": kind,
                       "replacement_text": replacement,
                       "why": "It reads calmer.", "trigger": trigger}}

    def test_polish_star_carries_narrow_diff_quote(self):
        # Quote narrowing (founder 2026-07-20): a polish star underlines
        # ONLY the changed span, computed from the verbatim-vs-polished
        # diff — never the whole piece.
        body, _ = self._get(sugs=self._sug(
            trigger="polish", kind="replace", replacement="the pivot"))
        sug = body["key_moments"][0]["suggestion"]
        self.assertEqual(sug["quote"], "turn")
        self.assertIn(sug["quote"], body["text"])

    def test_threat_replace_is_icon_only_no_quote(self):
        body, _ = self._get(sugs=self._sug(trigger="threat"))
        self.assertIsNone(body["key_moments"][0]["suggestion"]["quote"])

    def test_emphasize_is_icon_only_no_quote(self):
        body, _ = self._get(sugs=self._sug(kind="emphasize",
                                           replacement=None,
                                           trigger="charisma"))
        self.assertIsNone(body["key_moments"][0]["suggestion"]["quote"])

    def test_profanity_replace_quotes_the_carrying_sentence(self):
        self.text = (f"Hello. [[moment:{SNIP}|{SESS}]]We tried hard. "
                     "Then the damn projector died. We laughed."
                     "[[/moment]] goodbye.")
        body, _ = self._get(sugs=self._sug(trigger="threat"))
        sug = body["key_moments"][0]["suggestion"]
        self.assertEqual(sug["quote"], "Then the damn projector died.")
        self.assertIn(sug["quote"], body["text"])

    def test_explanations_available_tracks_coach_explanations(self):
        body, _ = self._get(sugs=self._sug())
        self.assertFalse(body["explanations_available"])
        body, _ = self._get(sugs=self._sug(), drafts=[
            {"snippet_id": SNIP, "surfaced": True, "note": "watch this"}])
        self.assertTrue(body["explanations_available"])

    def test_replace_star_trigger_clamped_to_polish_or_none(self):
        # The FE labels a 'polish' replace differently from the rest — but
        # the raw internal vocabulary (threat/charisma/...) must NEVER ride
        # a user payload (CONSTRUCT/AC-9; adversarial review 2026-07-18).
        body, _ = self._get(sugs=self._sug(trigger="polish", replacement="X"))
        self.assertEqual(body["key_moments"][0]["suggestion"]["trigger"],
                         "polish")
        body, _ = self._get(sugs=self._sug(trigger="threat"))
        m = body["key_moments"][0]
        self.assertIsNone(m["suggestion"]["trigger"])
        self.assertNotIn("threat", json.dumps(m))
        body, _ = self._get(sugs=self._sug(kind="emphasize",
                                           replacement=None,
                                           trigger="charisma"))
        m = body["key_moments"][0]
        self.assertIsNone(m["suggestion"]["trigger"])
        self.assertNotIn("charisma", json.dumps(m))

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

    def _struct(self, device="contrast", quote="the turn"):
        return {SNIP: {"snippet_id": SNIP, "arc_id": ARC, "kind": "structure",
                       "replacement_text": None, "why": quote,
                       "trigger": device}}

    def test_structural_star_serves_device_and_quote(self):
        body, _ = self._get(sugs=self._struct())
        m = body["key_moments"][0]
        self.assertEqual(m["star"], "suggestion")
        s = m["suggestion"]
        self.assertEqual(s["kind"], "structure")
        self.assertEqual(s["device"], "contrast")
        self.assertEqual(s["quote"], "the turn")   # the user's own words
        self.assertIsNone(s["why"])                # no generated prose served
        self.assertNotIn("replacement", s)

    def test_structural_star_never_consumed_by_applied(self):
        # A structural star is a delivery prompt — even a stray feedback row
        # must never fold it away or drop it.
        feedback = [{"snippet_id": SNIP, "target": "moment_structure",
                     "action": "applied"}]
        body, _ = self._get(sugs=self._struct(), feedback=feedback)
        m = body["key_moments"][0]
        self.assertEqual(m["star"], "suggestion")
        self.assertEqual(m["suggestion"]["kind"], "structure")
        self.assertNotIn("[[moment:", body["text"])   # never folded

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
        # The suggestion is CONSUMED — no star re-offering it (its result is
        # already in the text); the moment itself stays, anchored to the
        # replacement so the FE can still locate it.
        self.assertNotIn("star", m)
        self.assertNotIn("applied", m)
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

    def test_delivery_star_serves_device_only(self):
        # Measured delivery star (founder 2026-07-18): behavioural prompt,
        # no prose, no numbers — the FE renders approved copy from device.
        sugs = {SNIP: {"snippet_id": SNIP, "arc_id": ARC, "kind": "delivery",
                       "replacement_text": None, "why": None,
                       "trigger": "pace_fast"}}
        body, _ = self._get(sugs=sugs)
        m = body["key_moments"][0]
        self.assertEqual(m["star"], "suggestion")
        self.assertEqual(m["suggestion"]["kind"], "delivery")
        self.assertEqual(m["suggestion"]["device"], "pace_fast")
        self.assertIsNone(m["suggestion"]["quote"])
        self.assertIsNone(m["suggestion"]["why"])
        raw = json.dumps(body)
        for banned in ("wpm", "z_score", "f0_sd", "dynamic_db",
                       "pause_ratio"):
            self.assertNotIn(banned, raw)   # nothing numeric rides along

    def test_delivery_unknown_device_yields_no_star(self):
        # The FE renders copy PURELY from device (pinned) — an unknown
        # spelling must yield NO star, and must NOT fall through to the
        # generic text-suggestion branch either.
        sugs = {SNIP: {"snippet_id": SNIP, "arc_id": ARC, "kind": "delivery",
                       "replacement_text": None, "why": None,
                       "trigger": "volume_up"}}
        body, _ = self._get(sugs=sugs)
        m = body["key_moments"][0]
        self.assertNotIn("star", m)
        self.assertNotIn("suggestion", m)

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


class StructuralQuoteVerbatimTests(unittest.TestCase):
    """FE contract pin (founder 2026-07-18): the sheet copy is rendered
    PURELY from `device`, so it must be exactly "contrast"/"list_of_three";
    and the `quote` is displayed as-is, so it must be character-for-character
    what the speaker said."""

    TX = "It's Not About Speed, it's about clarity."

    def _detect(self, parsed):
        from services import moment_suggestions as ms
        res = type("R", (), {"parsed": parsed, "text": ""})()
        with patch("services.llm.chat_complete", return_value=res):
            return ms.detect_structural_device(self.TX)

    def test_quote_takes_the_transcripts_own_casing(self):
        # the model echoes different casing than the speaker used
        out = self._detect({"device": "contrast",
                            "quote": "it's not about speed, IT'S ABOUT CLARITY"})
        self.assertEqual(out["quote"], "It's Not About Speed, it's about clarity")
        self.assertIn(out["quote"], self.TX)   # character-exact substring

    def test_device_normalised_to_the_two_exact_spellings(self):
        self.assertEqual(self._detect(
            {"device": "CONTRAST", "quote": "It's Not About Speed"})["device"],
            "contrast")
        self.assertEqual(self._detect(
            {"device": " List_Of_Three ", "quote": "it's about clarity"}
        )["device"], "list_of_three")

    def test_unknown_device_yields_no_star(self):
        self.assertIsNone(self._detect(
            {"device": "anaphora", "quote": "It's Not About Speed"}))
        self.assertIsNone(self._detect(
            {"device": "none", "quote": ""}))

    def test_hallucinated_quote_dropped(self):
        self.assertIsNone(self._detect(
            {"device": "contrast", "quote": "words never spoken"}))


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class LedgerBakeAssemblyTests(unittest.TestCase):
    """Gradual refinement rule 1 (founder 2026-07-20): APPROVED decisions
    bake into every future machine copy at ASSEMBLY time; decided phrases
    (either direction) are never re-offered as polish stars."""

    class _Db:
        def __init__(self, rows):
            self._rows = rows

        def list_ideal_decisions(self, arc_id):
            return self._rows

    def _assemble(self, rows, *, verbatim="the old words carry it",
                  edited="the polished words carry it", polished=True):
        import services.ideal_text_block as mod
        bp = {"ready": True, "slides": [{
            "text": edited, "verbatim": verbatim, "polished": polished,
            "snippet_id": SNIP, "session_id": SESS,
            "breakthrough": False, "key_phrases": [],
        }]}
        with patch("services.best_presentation.build_best_presentation",
                   return_value=bp), \
             patch.object(mod, "_polish_as_suggestions_enabled",
                          return_value=True):
            return mod.assemble_ideal_text_block(
                ARC, database=self._Db(rows))

    def test_approved_replace_bakes_into_the_text(self):
        out = self._assemble([{
            "kind": "replace", "target_phrase": "the old words",
            "display_phrase": "the old words",
            "replacement_text": "the brave words",
            "decision": "approved"}])
        self.assertIn("the brave words carry it", out["text"])
        self.assertNotIn("the old words", out["text"])

    def test_approved_polish_bakes_and_is_not_reoffered(self):
        out = self._assemble([{
            "kind": "polish",
            "target_phrase": "the old words carry it",
            "display_phrase": "the old words carry it",
            "replacement_text": "the polished words carry it",
            "decision": "approved"}])
        self.assertIn("the polished words carry it", out["text"])
        self.assertEqual(out["polish"], [])   # decided → no star again

    def test_dismissed_polish_stays_verbatim_and_silent(self):
        out = self._assemble([{
            "kind": "polish",
            "target_phrase": "the old words carry it",
            "display_phrase": "the old words carry it",
            "replacement_text": "the polished words carry it",
            "decision": "dismissed"}])
        self.assertIn("the old words carry it", out["text"])
        self.assertEqual(out["polish"], [])   # remembered → never again

    def test_no_ledger_keeps_todays_behavior(self):
        out = self._assemble([])
        self.assertIn("the old words carry it", out["text"])  # verbatim
        self.assertEqual(len(out["polish"]), 1)               # star offered

    def test_approved_emphasize_bakes_orange(self):
        out = self._assemble([{
            "kind": "emphasize", "target_phrase": "old words",
            "display_phrase": "old words", "replacement_text": None,
            "decision": "approved"}], polished=False)
        self.assertIn("{{orange:old words}}", out["text"])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class LedgerGenerationFilterTests(unittest.TestCase):
    """Rules 2/3: a decided phrase never regenerates a star — each
    version's stars are that version's delta only."""

    class _Db:
        def __init__(self, decided_rows):
            self.decided = decided_rows
            self.upserts = []

        def v2_get_session_by_id(self, sid):
            return {"id": sid, "user_id": None, "intake_context": {}}

        def list_ideal_decisions(self, arc_id):
            return self.decided

        def upsert_moment_suggestion(self, snip, arc, kind, repl, why, trig):
            self.upserts.append((snip, kind, trig))
            return True

    def test_decided_phrase_skipped_fresh_phrase_generated(self):
        from services import moment_suggestions as ms
        db = self._Db([{"kind": "emphasize",
                        "target_phrase": "keep this phrase",
                        "decision": "dismissed"}])
        readout = {"snippets": [
            {"id": "s1", "transcript": "Keep   THIS phrase",
             "acoustic_read": {"potentiometer": 0.9}},
            {"id": "s2", "transcript": "a fresh phrase lands",
             "acoustic_read": {"potentiometer": 0.9}},
        ]}
        result = type("R", (), {"parsed": {"why": "Plain and strong.",
                                           "replacement": None},
                                "text": ""})()
        with patch("services.lab_recording.build_readout_from_session",
                   return_value=readout), \
             patch("services.llm.chat_complete", return_value=result):
            ms.generate_for_session("sess-1", ARC, database=db)
        kinds = [(snip, kind) for (snip, kind, _t) in db.upserts]
        self.assertNotIn(("s1", "emphasize"), kinds)   # decided → skipped
        self.assertIn(("s2", "emphasize"), kinds)      # the delta


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ContextDocumentReachesGenerationTests(unittest.TestCase):
    """X-1 v2 (2026-07-25) — THE integration point. X-1 shipped the upload +
    storage, but nothing ever read the stored text into a prompt, so an
    attached document sharpened nothing. This pins that it now does."""

    class _Db:
        def __init__(self, doc=None, explode=False):
            self.doc = doc
            self.explode = explode
            self.upserts = []
            self.doc_calls = []

        def v2_get_session_by_id(self, sid):
            return {"id": sid, "user_id": None,
                    "intake_context": {"audience": "investors"}}

        def list_ideal_decisions(self, arc_id):
            return []

        def get_arc_context_document(self, arc_id):
            self.doc_calls.append(arc_id)
            if self.explode:
                raise RuntimeError("table missing (migration pending)")
            return self.doc

        def upsert_moment_suggestion(self, snip, arc, kind, repl, why, trig):
            self.upserts.append(snip)
            return True

    def _run(self, db):
        from services import moment_suggestions as ms
        captured = []
        readout = {"snippets": [
            {"id": "s1", "transcript": "our retention stayed strong",
             "acoustic_read": {"potentiometer": 0.9}},
        ]}

        def _capture(**kwargs):
            captured.append(kwargs.get("user") or "")
            return type("R", (), {"parsed": {"why": "Plain and strong.",
                                             "replacement": None},
                                  "text": ""})()

        with patch("services.lab_recording.build_readout_from_session",
                   return_value=readout), \
             patch("services.llm.chat_complete", side_effect=_capture):
            ms.generate_for_session("sess-1", ARC, database=db)
        return captured

    def test_the_stored_document_text_reaches_the_prompt(self):
        db = self._Db(doc={"text": "Retention held at pilot scale.",
                           "pages": 3})
        prompts = self._run(db)
        self.assertEqual(db.doc_calls, [ARC])          # fetched, arc-scoped
        self.assertTrue(prompts)
        self.assertIn("project_background", prompts[0])
        self.assertIn("Retention held at pilot scale", prompts[0])

    def test_no_document_means_no_background_key(self):
        prompts = self._run(self._Db(doc=None))
        self.assertTrue(prompts)
        self.assertNotIn("project_background", prompts[0])

    def test_a_missing_table_degrades_instead_of_killing_generation(self):
        # LIVE LOOP: pre-migration the table does not exist. Suggestions must
        # still generate, just without the background.
        db = self._Db(explode=True)
        prompts = self._run(db)
        self.assertTrue(prompts)                       # generation survived
        self.assertNotIn("project_background", prompts[0])
        self.assertEqual(db.upserts, ["s1"])           # star still stored

    def test_document_is_fetched_once_per_take_not_per_snippet(self):
        # Cost guard: one arc-scoped read, reused across snippets.
        from services import moment_suggestions as ms
        db = self._Db(doc={"text": "background text"})
        readout = {"snippets": [
            {"id": f"s{i}", "transcript": f"moment number {i} lands",
             "acoustic_read": {"potentiometer": 0.9}} for i in range(4)
        ]}
        result = type("R", (), {"parsed": {"why": "Strong.",
                                           "replacement": None},
                                "text": ""})()
        with patch("services.lab_recording.build_readout_from_session",
                   return_value=readout), \
             patch("services.llm.chat_complete", return_value=result):
            ms.generate_for_session("sess-1", ARC, database=db)
        self.assertEqual(len(db.doc_calls), 1)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SuggestionKindGuardPinTests(unittest.TestCase):
    def test_db_guard_mirrors_the_kind_check(self):
        # The 2026-07-20 lesson: #221 widened the DB CHECK to 'delivery'
        # but not the python guard — the feature ran silently inert in
        # prod. The guard is now a pinned constant.
        from services.db import DatabaseService
        self.assertEqual(
            set(DatabaseService.SUGGESTION_KINDS),
            {"emphasize", "replace", "structure", "delivery"})


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class GenerationRecurrenceProtectionTests(unittest.TestCase):
    """Rule 4a (founder 2026-07-20): a stickiness replace never targets
    wording the speaker uses in >= 2 takes; threat/profanity keep the
    harmful carve-out."""

    class _Db:
        def __init__(self, take_texts):
            self._takes = take_texts
            self.upserts = []

        def v2_get_session_by_id(self, sid):
            return {"id": sid, "user_id": None, "intake_context": {}}

        def list_ideal_decisions(self, arc_id):
            return []

        def get_arc_sessions(self, arc_id):
            return [{"id": f"t{i}", "take_index": i + 1,
                     "recording_kind": "spoken"}
                    for i in range(len(self._takes))]

        def get_snippets_by_session(self, sid):
            i = int(sid[1:])
            return [{"transcript": self._takes[i]}]

        def upsert_moment_suggestion(self, snip, arc, kind, repl, why, trig):
            self.upserts.append((snip, kind, trig))
            return True

    def _run(self, transcript, take_texts):
        from services import moment_suggestions as ms
        db = self._Db(take_texts)
        readout = {"snippets": [
            {"id": "s1", "transcript": transcript,
             "acoustic_read": {"potentiometer": 0.0},
             "slide_stickiness": 0.05},
        ]}
        result = type("R", (), {"parsed": {"why": "Calmer.",
                                           "replacement": "steady words"},
                                "text": ""})()
        with patch("services.lab_recording.build_readout_from_session",
                   return_value=readout), \
             patch("services.llm.chat_complete", return_value=result):
            ms.generate_for_session("sess-1", ARC, database=db)
        return db.upserts

    def test_recurring_wording_is_protected_from_stickiness_replace(self):
        phrase = "our boom town phrase closes it"
        ups = self._run(phrase, [f"first take {phrase}",
                                 f"second take {phrase} again"])
        self.assertNotIn(("s1", "replace", "stickiness"), ups)

    def test_profanity_still_replaces_even_when_recurring(self):
        phrase = "this damn phrase closes it"
        ups = self._run(phrase, [f"first take {phrase}",
                                 f"second take {phrase} again"])
        self.assertIn(("s1", "replace", "profanity"), ups)

    def test_non_recurring_stickiness_still_replaces(self):
        ups = self._run("a one off weak line here",
                        ["totally other take", "and another one"])
        self.assertIn(("s1", "replace", "stickiness"), ups)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class PolishRecurrenceProtectionTests(unittest.TestCase):
    """Rule 4a on the polish lane: a smoothing whose changed span is the
    speaker's recurring wording is never offered."""

    class _Db:
        def __init__(self, take_texts):
            self._takes = take_texts
            self.upserts = []

        def get_arc_sessions(self, arc_id):
            return [{"id": f"t{i}", "take_index": i + 1,
                     "recording_kind": "spoken"}
                    for i in range(len(self._takes))]

        def get_snippets_by_session(self, sid):
            i = int(sid[1:])
            return [{"transcript": self._takes[i]}]

        def list_ideal_decisions(self, arc_id):
            return []

        def get_moment_suggestions_by_arc(self, arc_id):
            return {}

        def persist_auto_ideal_text(self, arc_id, text):
            return True

        def upsert_moment_suggestion(self, snip, arc, kind, repl, why, trig):
            self.upserts.append((snip, trig))
            return True

    def _run(self, take_texts):
        import services.ideal_text_block as mod
        bp = {"ready": True, "slides": [{
            "text": "we are going to win this",
            "verbatim": "we gonna win this", "polished": True,
            "snippet_id": SNIP, "session_id": SESS,
            "breakthrough": False, "key_phrases": [],
        }]}
        db = self._Db(take_texts)
        with patch("services.best_presentation.build_best_presentation",
                   return_value=bp), \
             patch.object(mod, "_polish_as_suggestions_enabled",
                          return_value=True):
            mod.maybe_assemble_ideal_text(ARC, database=db,
                                          require_target=False)
        return db.upserts

    def test_recurring_span_suppresses_the_polish(self):
        ups = self._run(["i gonna say it plain", "gonna win again here"])
        self.assertEqual(ups, [])

    def test_non_recurring_span_still_offers_polish(self):
        ups = self._run(["a clean first take", "a clean second take"])
        self.assertEqual(ups, [(SNIP, "polish")])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class VersionSnapshotWriteTests(unittest.TestCase):
    """The worker freezes each persisted version (founder 2026-07-20):
    text WITH anchors + the step's sanitized reasoning, idempotent per
    (arc, version); a missing snapshot table never breaks assembly."""

    class _Db:
        def __init__(self):
            self.snapshots = []

        def get_arc_sessions(self, arc_id):
            return [{"id": "t0", "take_index": 1,
                     "recording_kind": "spoken"}]

        def get_snippets_by_session(self, sid):
            return [{"transcript": "a line"}]

        def list_ideal_decisions(self, arc_id):
            return []

        def get_moment_suggestions_by_arc(self, arc_id):
            return {SNIP: {"snippet_id": SNIP, "kind": "replace",
                           "replacement_text": "calmer", "why": "why",
                           "trigger": "threat"}}

        def persist_auto_ideal_text(self, arc_id, text):
            return True

        def get_coach_arc_ideal_text(self, arc_id):
            return {"arc_id": arc_id, "version": 4}

        def upsert_moment_suggestion(self, *a):
            return True

        def upsert_ideal_text_version(self, arc_id, version, text, moments):
            self.snapshots.append((arc_id, version, text, moments))
            return True

    def test_snapshot_written_with_sanitized_moments(self):
        import services.ideal_text_block as mod
        bp = {"ready": True, "slides": [{
            "text": "a strong line", "verbatim": "a strong line",
            "polished": False, "snippet_id": SNIP, "session_id": SESS,
            "breakthrough": True, "key_phrases": [],
        }]}
        db = self._Db()
        with patch("services.best_presentation.build_best_presentation",
                   return_value=bp), \
             patch.object(mod, "_polish_as_suggestions_enabled",
                          return_value=True):
            ok = mod.maybe_assemble_ideal_text(ARC, database=db,
                                               require_target=False)
        self.assertTrue(ok)
        arc, version, text, moments = db.snapshots[0]
        self.assertEqual((arc, version), (ARC, 4))
        self.assertIn(f"[[moment:{SNIP}|{SESS}]]", text)  # anchors kept
        self.assertEqual(moments[0]["snippet_id"], SNIP)
        self.assertIsNone(moments[0]["trigger"])          # clamped at write
        self.assertEqual(moments[0]["replacement"], "calmer")

    def test_missing_snapshot_table_never_breaks_assembly(self):
        import services.ideal_text_block as mod
        db = self._Db()
        db.upsert_ideal_text_version = None   # not callable → best-effort
        bp = {"ready": True, "slides": [{
            "text": "a strong line", "verbatim": "a strong line",
            "polished": False, "snippet_id": SNIP, "session_id": SESS,
            "breakthrough": False, "key_phrases": [],
        }]}
        with patch("services.best_presentation.build_best_presentation",
                   return_value=bp), \
             patch.object(mod, "_polish_as_suggestions_enabled",
                          return_value=True):
            self.assertTrue(mod.maybe_assemble_ideal_text(
                ARC, database=db, require_target=False))


if __name__ == "__main__":
    unittest.main()
