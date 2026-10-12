"""Route-level contracts for the speaker's suggestion feedback and Confident
Voice practice routes moved out of ``routes/v2/user_sessions.py`` into
services (founder 2026-10-12: "move logic out of the backend routes and cut
glue").

Characterization tests, written against the unmodified routes first: each pins
one route's main success path (status, body, the writes and their order) and
its main refusal. Decorators (auth, purpose guard, consent choice) are peeled
with ``inspect.unwrap``; the move leaves them untouched.
"""
from __future__ import annotations

import inspect
import io
import unittest
from unittest.mock import ANY, MagicMock, patch

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

    def test_a_dismissed_star_writes_the_ledger_in_order(self):
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
        self.assertEqual([c[0] for c in rec.mock_calls],
                         ["insert", "rebake", "ledger", "spend", "delete"])
        rec.insert.assert_called_once_with(
            snippet_id=SNIP, session_id=SID, user_id=USER,
            target="moment_replace", action="dismissed", upgrade_index=2,
            suggestion_version="5")
        rec.ledger.assert_called_once_with(
            db, ARC, suggestion={"replacement_text": "p"},
            target="moment_replace", action="dismissed", target_text="q",
            snippet_id=SNIP, version=7, slide_index=3)
        rec.spend.assert_called_once_with(
            db, ARC, [session], change_key=f"star:moment_replace:{SNIP}",
            decision="disregarded", lane=None, intervention_type="REWRITE",
            quote=" q ", proposed_text=" p ", why_key="w")
        rec.delete.assert_called_once_with(SNIP)

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
                                    "pace_high": False}) as elig, \
                patch.object(db, "create_confident_voice_practice",
                             side_effect=lambda row: {"id": PRACTICE, **row}) as create:
            status, body = self._post({"kind": "plain", "evidence": self.EVIDENCE})
        self.assertEqual((status, body), (201, {"practice": {"id": PRACTICE,
                                                             "attempts": []}}))
        self.assertEqual(elig.call_args.kwargs, {"session_median_wpm": 120.0})
        create.assert_called_once_with({
            "owner_user_id": USER, "project_id": ARC, "take_session_id": SID,
            "snippet_id": SNIP, "exercise_id": None, "exercise_version": 0,
            "exercise_snapshot": {
                "exercise_id": None, "version": 0, "title": None,
                "instruction": None, "explanation_video_url": None,
                "source": "plain", "feedback_id": None},
            "kind": "plain", "slide_index": 1, "paragraph_index": 0,
            "evidence_span": {"start": 2, "end": 9}, "exact_passage": "said words",
            "original_audio_ref": "a/b.webm", "original_start_offset_ms": 40,
            "original_duration_ms": 900,
            "machine_assessment": {"pattern": "p", "priority": 2},
            "acoustic_evidence": {"signals": ["s"], "snapshot": {"x": 1},
                                  "pace_high": False},
            "original_user_answer": None,
        })

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
                      return_value={"pitch": 1}) as analyze, \
                patch("services.voice_confidence.resolve_confidence_baseline",
                      return_value=(None, "none")), \
                patch("services.voice_confidence.read_for_piece", return_value=None), \
                patch.object(db, "get_snippets_by_session", return_value=[]), \
                patch("services.confident_voice_practice.acoustic_snapshot",
                      return_value={"snap": 1}), \
                patch("services.confident_voice_practice.machine_confidence_decision",
                      return_value="m"), \
                patch("uuid.uuid4", return_value=MagicMock(hex="h")), \
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
        self.assertEqual([c[0] for c in rec.mock_calls],
                         ["transcribe", "store", "record", "strongest"])
        analyze.assert_called_once_with(b"x" * 2000 + b"!", "said words", 2.5)
        key = f"confidence-practice/{USER}/{PRACTICE}/2-h.webm"
        rec.store.assert_called_once_with(key, b"x" * 2000 + b"!", "audio/webm")
        row = rec.record.call_args.args[1]
        self.assertEqual(row, {
            "practice_id": PRACTICE, "attempt_index": 2, "storage_path": key,
            "audio_ref": f"s3://bkt/{key}", "mime_type": "audio/webm",
            "duration_ms": 2500, "transcript": "said words",
            "transcript_alignment": {"matches": True},
            "acoustic_metrics": {"snap": 1},
            "comparison": {"contract_version": "practice-product-observation-v1",
                           "baseline": {"orig": 1}, "attempt": {"snap": 1},
                           "previous_attempt": {"prev": 1},
                           "no_automatic_outcome": True},
            "assessment_key": "recorded_for_comparison",
            "machine_confidence_decision": "m"})
        rec.strongest.assert_called_once_with(PRACTICE, "a1")

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
        rec.keep.assert_called_once_with(PRACTICE, ATTEMPT, "yes")
        rec.update.assert_called_once_with(PRACTICE, USER, {
            "status": "completed", "selected_attempt_id": ATTEMPT,
            "final_user_answer": "yes", "closed_at": ANY})

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
        update.assert_called_once_with(PRACTICE, USER,
                                       {"status": "dismissed", "closed_at": ANY})


if __name__ == "__main__":
    unittest.main()
