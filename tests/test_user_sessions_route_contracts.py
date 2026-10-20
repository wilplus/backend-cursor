"""
STORY    As a speaker, I want my suggestion answers and Confident Voice
         practice (start, attempt, complete) to work and refuse bad input, so
         that practice never loses my recording.
OUTCOME
  O1  A suggestion answer is saved (200 {"saved": true}); a bad target is 400
      and someone else's Take is 404 with nothing written.
  O2  Starting practice on a moment creates it for me (201); an existing one
      is resumed (200) without a second row; a bad or premature answer is
      refused (400, 409).
  O3  An attempt is stored and recorded (201) with no automatic outcome; a
      closed practice is 409 and a passage mismatch is 422 with nothing
      stored.
  O4  Keeping an attempt completes the practice and dismissing closes it
      (200); keeping an attempt that is not the strongest is 400 with nothing
      kept.
PROVES   O1 -> SuggestionFeedbackContract.test_a_dismissed_star_is_saved
            -> SuggestionFeedbackContract.test_refusals
         O2 -> PracticeStartContract.test_a_moment_practice_is_created
            -> PracticeStartContract.test_refusals_and_the_resume
         O3 -> PracticeAttemptContract.test_an_attempt_is_recorded
            -> PracticeAttemptContract.test_refusals
         O4 -> PracticeCompleteContract.test_a_kept_attempt_completes_the_practice
            -> PracticeCompleteContract.test_refusals_and_the_dismissal
WHY      Founder 2026-10-12: route logic moved into services; these hold the
         routes' status and refusal contracts across that move. Decorators are
         peeled with inspect.unwrap.
"""
from __future__ import annotations

import inspect
import io
import unittest
from unittest.mock import MagicMock, patch

try:
    from flask import Flask, request

    from routes.v2 import user_sessions as us
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e

USER = "11111111-1111-4111-8111-111111111111"
SID = "22222222-2222-4222-8222-222222222222"
SNIP = "33333333-3333-4333-8333-333333333333"
ARC = "44444444-4444-4444-8444-444444444444"
PRACTICE = "55555555-5555-4555-8555-555555555555"
ATTEMPT = "66666666-6666-4666-8666-666666666666"


def _call(route, *args, **ctx):
    app = Flask(__name__)
    with app.test_request_context(**ctx):
        request.user_id = USER
        result = inspect.unwrap(route)(*args)
        resp, status = result if isinstance(result, tuple) else (result, 200)
        return status, (resp.get_json() if hasattr(resp, "get_json") else resp)


def _payload(practice, attempts=None):
    return {"id": practice.get("id"), "attempts": attempts}


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SuggestionFeedbackContract(unittest.TestCase):
    """POST /v2/user/snippets/<snip>/suggestion-feedback."""

    def _post(self, body):
        return _call(us.v2_user_suggestion_feedback, SNIP, method="POST",
                     json={"session_id": SID, **body})

    def test_a_dismissed_star_is_saved(self):
        session = {"id": SID, "user_id": USER, "arc_id": ARC}
        snip = {"id": SNIP, "session_id": SID, "transcript": "raw",
                "metrics": {"piece": {"slide_index": 3}}}
        rec = MagicMock()
        rec.insert.return_value = True
        with patch.object(db, "v2_get_session_by_id", return_value=session), \
                patch.object(db, "get_snippet_by_id", return_value=snip), \
                patch.object(db, "insert_user_suggestion_feedback", rec.insert), \
                patch("services.ideal_text_feedback_bake.request_rebake_after_answer",
                      rec.rebake), \
                patch.object(db, "get_moment_suggestions_by_arc",
                             return_value={SNIP: {"replacement_text": "old"}}), \
                patch.object(db.ideal_text, "get_coach_arc_ideal_text",
                             return_value={"version": 7}), \
                patch.object(us, "_document_phrase_for",
                             side_effect=lambda a, s, fallback=None: f"doc:{fallback}"), \
                patch("services.ideal_decision_ledger.record_star_decision",
                      rec.ledger), \
                patch.object(db.takes, "get_arc_sessions", return_value=[session]), \
                patch("services.intervention_spend.spend", rec.spend), \
                patch("services.intervention_spend.unspend", rec.unspend), \
                patch.object(db, "delete_moment_suggestion", rec.delete), \
                patch.object(us, "_reassemble_after_decision", rec.reassemble):
            status, body = self._post({
                "target": "moment_replace", "action": "dismissed",
                "upgrade_index": 2, "suggestion_version": 5,
                "source": "coach_revision", "quote": " q ",
                "proposed_text": " p ", "why_key": "w"})
        self.assertEqual((status, body), (200, {"saved": True}))
        self.assertEqual(rec.insert.call_args.kwargs["action"], "dismissed")

    def test_refusals(self):
        status, body = self._post({"target": "nope", "action": "applied"})
        self.assertEqual((status, body["code"]), (400, "INVALID_INPUT"))
        with patch.object(db, "v2_get_session_by_id",
                          return_value={"id": SID, "user_id": "someone-else"}), \
                patch.object(db, "insert_user_suggestion_feedback") as insert:
            status, body = self._post({"target": "upgrade", "action": "applied"})
        self.assertEqual((status, body["code"]), (404, "NOT_FOUND"))
        insert.assert_not_called()


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class PracticeStartContract(unittest.TestCase):
    """POST /v2/user/snippets/<snip>/confidence-practice."""

    EVIDENCE = {"project_id": ARC, "take_session_id": SID, "slide_index": 1,
                "paragraph_index": 0, "span": {"start": 2, "end": 9}}

    def _post(self, body):
        return _call(us.v2_start_confident_voice_practice, SNIP, method="POST",
                     json=body)

    def _reads(self, existing=None):
        snip = {"id": SNIP, "session_id": SID, "transcript": " said words ",
                "audio_segment_path": "a/b.webm", "start_offset_ms": 40,
                "duration_ms": 900}
        return [
            patch.object(db, "get_snippet_by_id", return_value=snip),
            patch.object(db, "v2_get_session_by_id",
                         return_value={"id": SID, "user_id": USER, "arc_id": ARC}),
            patch.object(db, "get_confident_voice_practice_by_moment",
                         return_value=existing),
            patch.object(us, "_practice_user_payload", side_effect=_payload),
        ]

    def test_a_moment_practice_is_created(self):
        reads = self._reads()
        with reads[0], reads[1], reads[2], reads[3], \
                patch.object(db, "get_snippets_by_session", return_value=[
                    {"wpm": 100}, {"wpm": 140}, {"wpm": 120}, {}]), \
                patch("services.confident_voice_practice.exercise_eligibility",
                      return_value={"pattern": "p", "priority": 2,
                                    "signals": ["s"], "snapshot": {"x": 1},
                                    "pace_high": False}), \
                patch.object(db, "create_confident_voice_practice",
                             side_effect=lambda row: {"id": PRACTICE, **row}) as create:
            status, body = self._post({"kind": "plain", "evidence": self.EVIDENCE})
        self.assertEqual((status, body), (201, {"practice": {"id": PRACTICE,
                                                             "attempts": []}}))
        row = create.call_args.args[0]
        self.assertEqual((row["owner_user_id"], row["snippet_id"], row["exact_passage"]),
                         (USER, SNIP, "said words"))

    def test_refusals_and_the_resume(self):
        status, body = self._post({"original_user_answer": "maybe"})
        self.assertEqual((status, body["code"]), (400, "INVALID_INPUT"))
        reads = self._reads()
        with reads[0], reads[1], reads[2], reads[3], \
                patch.object(db, "list_owner_voice_album_routes", return_value=[]):
            status, body = self._post({"original_user_answer": "yes"})
        self.assertEqual((status, body["code"]), (409, "ANSWER_REQUIRED"))
        reads = self._reads(existing={"id": PRACTICE})
        with reads[0], reads[1], reads[2], reads[3], \
                patch.object(db, "create_confident_voice_practice") as create:
            status, body = self._post({"kind": "plain"})
        self.assertEqual((status, body), (200, {"practice": {"id": PRACTICE,
                                                             "attempts": None}}))
        create.assert_not_called()


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class PracticeAttemptContract(unittest.TestCase):
    """POST /v2/user/confidence-practice/<id>/attempts."""

    PRACTICE_ROW = {"id": PRACTICE, "status": "open", "exact_passage": "said words",
                    "take_session_id": SID, "owner_user_id": USER,
                    "snippet_id": SNIP,
                    "acoustic_evidence": {"snapshot": {"orig": 1}}}

    def _post(self, audio=b"x" * 2000):
        return _call(us.v2_add_confident_voice_practice_attempt, PRACTICE,
                     method="POST", content_type="multipart/form-data",
                     data={"audio_file": (io.BytesIO(audio), "a.webm", "audio/webm"),
                           "duration_sec": "3"})

    def test_an_attempt_is_recorded(self):
        rec = MagicMock()
        rec.transcribe.return_value = {"transcript": "said words",
                                       "transcribed_duration_ms": 2500,
                                       "words": ["w"]}
        rec.store.return_value = "bkt"
        rec.record.return_value = {"id": ATTEMPT, "attempt_index": 2}
        prior = {"id": "a1", "attempt_index": 1, "acoustic_metrics": {"prev": 1}}
        with patch.object(db, "get_confident_voice_practice",
                          return_value=dict(self.PRACTICE_ROW)), \
                patch.object(db, "list_confident_voice_practice_attempts",
                             side_effect=[[prior], ["refreshed"]]), \
                patch("services.webm_remux.remux_webm_for_seeking",
                      side_effect=lambda b, label=None: b + b"!"), \
                patch("services.practice_transcription.transcribe_practice_attempt",
                      rec.transcribe), \
                patch("services.confident_voice_practice.passage_alignment",
                      return_value={"matches": True}), \
                patch("services.audio_metrics.analyze_audio",
                      return_value={"pitch": 1}), \
                patch("services.voice_confidence.resolve_confidence_baseline",
                      return_value=(None, "none")), \
                patch("services.voice_confidence.read_for_piece", return_value=None), \
                patch.object(db, "get_snippets_by_session", return_value=[]), \
                patch("services.confident_voice_practice.acoustic_snapshot",
                      return_value={"snap": 1}), \
                patch("services.confident_voice_practice.machine_confidence_decision",
                      return_value="m"), \
                patch("services.lab_audio_storage.put_lab_audio_bytes", rec.store), \
                patch("services.lab_audio_storage.lab_audio_public_url",
                      return_value=None), \
                patch("services.practice_audio_objects.record_practice_attempt",
                      rec.record), \
                patch.object(db, "set_confident_voice_practice_strongest",
                             rec.strongest), \
                patch.object(us, "_practice_user_payload", side_effect=_payload):
            status, body = self._post()
        self.assertEqual(status, 201, body)
        self.assertEqual(body, {"practice": {"id": PRACTICE, "attempts": ["refreshed"]}})
        stored_key = rec.store.call_args.args[0]
        row = rec.record.call_args.args[1]
        self.assertEqual(row["storage_path"], stored_key)
        self.assertEqual(row["audio_ref"], f"s3://bkt/{stored_key}")
        self.assertIs(row["comparison"]["no_automatic_outcome"], True)

    def test_refusals(self):
        with patch.object(db, "get_confident_voice_practice",
                          return_value={**self.PRACTICE_ROW, "status": "completed"}):
            status, body = self._post()
        self.assertEqual((status, body["code"]), (409, "PRACTICE_CLOSED"))
        with patch.object(db, "get_confident_voice_practice",
                          return_value=dict(self.PRACTICE_ROW)), \
                patch.object(db, "list_confident_voice_practice_attempts",
                             return_value=[]), \
                patch("services.webm_remux.remux_webm_for_seeking",
                      side_effect=lambda b, label=None: b), \
                patch("services.practice_transcription.transcribe_practice_attempt",
                      return_value={"transcript": "other words"}), \
                patch("services.confident_voice_practice.passage_alignment",
                      return_value={"matches": False}), \
                patch("services.lab_audio_storage.put_lab_audio_bytes") as store:
            status, body = self._post()
        self.assertEqual((status, body["code"]), (422, "PASSAGE_MISMATCH"))
        store.assert_not_called()


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class PracticeCompleteContract(unittest.TestCase):
    """PUT /v2/user/confidence-practice/<id>/complete."""

    def _put(self, body):
        return _call(us.v2_complete_confident_voice_practice, PRACTICE,
                     method="PUT", json=body)

    def test_a_kept_attempt_completes_the_practice(self):
        rec = MagicMock()
        rec.keep.return_value = True
        rec.update.return_value = {"id": PRACTICE, "status": "completed"}
        with patch.object(db, "get_confident_voice_practice",
                          return_value={"id": PRACTICE, "status": "open"}), \
                patch.object(db, "list_confident_voice_practice_attempts",
                             return_value=[{"id": ATTEMPT, "is_strongest": True}]), \
                patch.object(db, "keep_confident_voice_practice_attempt", rec.keep), \
                patch.object(db, "update_confident_voice_practice", rec.update), \
                patch.object(us, "_practice_user_payload", side_effect=_payload):
            status, body = self._put({"user_answer": "yes", "attempt_id": ATTEMPT})
        self.assertEqual((status, body), (200, {"practice": {"id": PRACTICE,
                                                             "attempts": None}}))
        self.assertEqual(rec.update.call_args.args[2]["status"], "completed")

    def test_refusals_and_the_dismissal(self):
        with patch.object(db, "get_confident_voice_practice",
                          return_value={"id": PRACTICE, "status": "open"}), \
                patch.object(db, "list_confident_voice_practice_attempts",
                             return_value=[{"id": "other", "is_strongest": True}]), \
                patch.object(db, "keep_confident_voice_practice_attempt") as keep:
            status, body = self._put({"user_answer": "yes", "attempt_id": ATTEMPT})
        self.assertEqual((status, body["code"]), (400, "INVALID_INPUT"))
        keep.assert_not_called()
        with patch.object(db, "get_confident_voice_practice",
                          return_value={"id": PRACTICE, "status": "open"}), \
                patch.object(db, "update_confident_voice_practice",
                             return_value={"id": PRACTICE}) as update, \
                patch.object(us, "_practice_user_payload", side_effect=_payload):
            status, body = self._put({"action": "dismiss"})
        self.assertEqual(status, 200)
        self.assertEqual(update.call_args.args[2]["status"], "dismissed")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
