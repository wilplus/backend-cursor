"""willab — context-aware recording setup (founder 2026-07-22).

The user picks the project they are continuing; the server stops
guessing. Pinned here:

  BE-1 `continue_arc_id` = EXPLICIT selection → the take appends
       strictly to that arc, BOTH continue-arc heuristics are skipped,
       the SERVER numbers the take, foreign/unknown arcs are refused.
       The carried-`arc_id` path (takes 2/3 of one sitting) keeps
       today's behavior so the continue-one-arc-per-deck lock
       (2026-06-20) is untouched.
  BE-2 GET …/setup returns ONLY the setup fields, from the latest
       spoken take, owner-only.

Run: python3 -m unittest test_context_aware_setup
"""
from __future__ import annotations

import inspect
import io
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

ARC = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
UID = "11111111-1111-4111-8111-111111111111"
T1 = "22222222-2222-4222-8222-222222222222"
T2 = "33333333-3333-4333-8333-333333333333"


def _file(name="take.webm", ctype="audio/webm", body=b"x" * 64):
    from werkzeug.datastructures import FileStorage
    return FileStorage(stream=io.BytesIO(body), filename=name,
                       content_type=ctype)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ExplicitSelectionTests(unittest.TestCase):
    """BE-1 — no guessing when the user chose the project."""

    def setUp(self):
        self.app = Flask(__name__)

    def _post(self, form, *, owner=UID, caller=UID, gate_ok=True,
              captured_arcs=None, duplicate_upload=None):
        """Drives the real endpoint far enough to reach arc resolution.

        The min-content gate sits BEFORE arc resolution, so it must PASS
        for the heuristics assertions to mean anything (a failing gate
        would return 422 first and every assertion would hold
        vacuously). Storage/DB writes are stubbed; the run ends after
        arc resolution: `db.set_session_arc` is the first call AFTER
        the heuristics block, so raising there stops the run with the
        assertions already decided (verified against the real call
        order, not assumed).
        """
        data = {"audio_file": _file(), "topic": "my talk"}
        data.update(form)
        sessions = [{"id": T1, "user_id": owner, "take_index": 1,
                     "recording_kind": "spoken"},
                    {"id": T2, "user_id": owner, "take_index": 2,
                     "recording_kind": "spoken"}]

        def _stop_at_arc_write(*args, **kwargs):
            if captured_arcs is not None:
                # set_session_arc(session_id, arc_id, take_index)
                captured_arcs.append(args[1])
            raise RuntimeError("stop here")

        with self.app.test_request_context(
                method="POST", data=data,
                content_type="multipart/form-data"):
            request.user_id = caller
            with patch.object(v2.db, "get_arc_sessions",
                              return_value=sessions), \
                 patch.object(v2.db, "v2_find_session_by_upload_key",
                              return_value=duplicate_upload), \
                 patch("routes.v2.lab_recording._continue_deck_arc",
                       side_effect=RuntimeError("deck heuristic")) \
                    as m_deck, \
                 patch("routes.v2.lab_recording._continue_topic_arc",
                       side_effect=RuntimeError("topic heuristic")) \
                    as m_topic, \
                 patch("services.coach_video_storage."
                       "put_coach_object_bytes"), \
                 patch("services.coach_video_storage."
                       "coach_media_public_url", return_value="https://x"), \
                 patch("services.min_content_gate."
                       "evaluate_min_content_bytes",
                       return_value={"ok": gate_ok, "reason": "no_speech",
                                     "duration_sec": 30.0,
                                     "voiced_sec": 20.0,
                                     "thresholds": {}}), \
                 patch.object(v2.db, "v2_get_session_by_id",
                              return_value=None), \
                 patch.object(v2.db, "v2_create_guest_session",
                              return_value={"id": "new"}), \
                 patch.object(v2.db, "set_session_intake_context"), \
                 patch.object(v2.db, "set_session_source"), \
                 patch.object(v2.db, "set_session_presentation_duration"), \
                 patch.object(v2.db, "set_session_user_id"), \
                 patch.object(v2.db, "set_session_arc",
                              side_effect=_stop_at_arc_write):
                out = v2.v2_lab_create_recording.__wrapped__()
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, m_deck, m_topic

    def test_explicit_selection_skips_both_heuristics(self):
        # The heuristics RAISE if called — reaching the stop-marker
        # instead proves the explicit path skipped them.
        _, status, m_deck, m_topic = self._post(
            {"continue_arc_id": ARC, "slides": '[{"title":"a"}]'})
        self.assertEqual(status, 500)          # the stop marker
        m_deck.assert_not_called()
        m_topic.assert_not_called()

    def test_continue_intent_reuses_exactly_the_selected_uuid(self):
        captured = []
        _, status, m_deck, m_topic = self._post(
            {"project_intent": "continue", "continue_arc_id": ARC,
             "arc_id": ARC, "slides": '[{"title":"same project"}]'},
            captured_arcs=captured)
        self.assertEqual(status, 500)
        self.assertEqual(captured, [ARC])
        m_deck.assert_not_called()
        m_topic.assert_not_called()

    def test_new_project_intent_keeps_a_fresh_uuid_with_default_slides(self):
        captured = []
        _, status, m_deck, m_topic = self._post(
            {"project_intent": "new", "topic": "fresh default project",
             "slides": '[{"title":"the shared default"}]'},
            captured_arcs=captured)
        self.assertEqual(status, 500)  # reached the post-resolution marker
        self.assertEqual(len(captured), 1)
        self.assertNotEqual(captured[0], ARC)
        m_deck.assert_not_called()
        m_topic.assert_not_called()

    def test_two_same_named_future_projects_get_two_distinct_uuids(self):
        captured = []
        for _ in range(2):
            _, status, m_deck, m_topic = self._post(
                {"project_intent": "new", "topic": "Quarterly update",
                 "slides": '[{"title":"the same shared default"}]'},
                captured_arcs=captured)
            self.assertEqual(status, 500)
            m_deck.assert_not_called()
            m_topic.assert_not_called()
        self.assertEqual(len(captured), 2)
        self.assertNotEqual(captured[0], captured[1])

    def test_new_project_retry_collapses_by_capture_key(self):
        duplicate = {"id": T1, "arc_id": ARC, "take_index": 1}
        body, status, m_deck, m_topic = self._post(
            {"project_intent": "new", "topic": "already accepted",
             "upload_idempotency_key": "same-captured-take"},
            duplicate_upload=duplicate)
        self.assertEqual(status, 200)
        self.assertTrue(body["duplicate"])
        self.assertEqual(body["arc_id"], ARC)
        m_deck.assert_not_called()
        m_topic.assert_not_called()

    def test_new_project_intent_does_not_group_an_uploaded_deck_either(self):
        captured = []
        _, status, m_deck, m_topic = self._post(
            {"project_intent": "new", "topic": "fresh uploaded project",
             "slides": '[{"title":"a"}]',
             "presentation_ref": "https://x/deck.pdf"},
            captured_arcs=captured)
        self.assertEqual(status, 500)
        self.assertEqual(len(captured), 1)
        m_deck.assert_not_called()
        m_topic.assert_not_called()

    def test_new_project_rejects_any_carried_identity_before_storage(self):
        for field in ("arc_id", "continue_arc_id"):
            body, status, m_deck, m_topic = self._post(
                {"project_intent": "new", field: ARC})
            self.assertEqual(status, 400)
            self.assertEqual(body["code"], "INVALID_INPUT")
            m_deck.assert_not_called()
            m_topic.assert_not_called()

    def test_continue_intent_requires_the_selected_project(self):
        body, status, m_deck, m_topic = self._post(
            {"project_intent": "continue"})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "INVALID_INPUT")
        m_deck.assert_not_called()
        m_topic.assert_not_called()

    def test_unknown_project_intent_is_rejected(self):
        body, status, _, _ = self._post({"project_intent": "infer"})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "INVALID_INPUT")

    def test_an_UPLOADED_deck_still_uses_the_deck_heuristic(self):
        # The 2026-06-20 continue-one-arc lock must be untouched: a real deck
        # is still identified by its slides, and its re-takes still join it.
        _, status, m_deck, m_topic = self._post(
            {"arc_id": ARC, "take_index": "2",
             "slides": '[{"title":"a"}]',
             "presentation_ref": "https://x/deck.pdf"})
        m_deck.assert_called_once()
        m_topic.assert_not_called()

    def test_deckless_carried_path_uses_topic_heuristic(self):
        _, status, m_deck, m_topic = self._post(
            {"arc_id": ARC, "take_index": "2"})
        m_topic.assert_called_once()
        m_deck.assert_not_called()

    def test_the_DEFAULT_DECK_continues_by_TOPIC_not_by_deck_hash(self):
        """THE 2026-08-15 BUG, pinned. The default deck (2026-08-11) ships on
        every deckless take so word→slide bucketing is always defined — and it
        is a CONSTANT, so its content hash is one fixed value shared by every
        deckless talk a user has ever given.

        Routing that to the deck heuristic made `_continue_deck_arc` treat all
        of them as re-takes of one deck: a brand-new topic was appended to the
        most-developed unrelated arc and inherited that arc's locked ideal
        text, so the new take's "analysis" was the old take's words. It also
        meant the topic guard — the only thing that separates two talks — was
        never reached.

        Slides with NO `presentation_ref` are a scaffold, not an identity."""
        _, status, m_deck, m_topic = self._post(
            {"arc_id": ARC, "take_index": "2",
             "slides": '[{"title":"Intro — the hook + the promise.",'
                       '"body":"Rule: say what you\'re going to say."}]'})
        m_topic.assert_called_once()
        m_deck.assert_not_called()

    def test_an_empty_presentation_ref_is_not_a_deck(self):
        # A blank string must not read as "there is a PDF here".
        _, status, m_deck, m_topic = self._post(
            {"arc_id": ARC, "take_index": "2",
             "slides": '[{"title":"a"}]', "presentation_ref": ""})
        m_topic.assert_called_once()
        m_deck.assert_not_called()

    def test_refusals_happen_BEFORE_any_storage(self):
        # A take must never be stored against a project the caller does
        # not own (same fail-fast rule as the read guard).
        with self.app.test_request_context(
                method="POST",
                data={"audio_file": _file(), "topic": "t",
                      "continue_arc_id": ARC},
                content_type="multipart/form-data"):
            request.user_id = "someone-else"
            with patch.object(v2.db, "get_arc_sessions",
                              return_value=[{"id": T1, "user_id": UID}]), \
                 patch("services.coach_video_storage."
                       "put_coach_object_bytes") as m_put, \
                 patch("services.min_content_gate."
                       "evaluate_min_content_bytes") as m_gate:
                out = v2.v2_lab_create_recording.__wrapped__()
                resp, status = out if isinstance(out, tuple) else (out, 200)
        self.assertEqual(status, 404)
        m_put.assert_not_called()      # nothing stored
        m_gate.assert_not_called()     # not even processed

    def test_foreign_arc_is_refused_not_silently_new(self):
        body, status, m_deck, m_topic = self._post(
            {"continue_arc_id": ARC}, owner="someone-else")
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "NOT_FOUND")
        m_deck.assert_not_called()

    def test_malformed_id_400(self):
        body, status, _, _ = self._post({"continue_arc_id": "not-a-uuid"})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "INVALID_INPUT")

    def test_guest_cannot_claim_a_project(self):
        _, status, _, _ = self._post({"continue_arc_id": ARC}, caller=None)
        self.assertEqual(status, 404)

    def test_server_numbers_the_take_not_the_client(self):
        # Source pin: the FE-sent take_index is never trusted on the
        # explicit path (two spoken takes exist → the next is 3).
        src = inspect.getsource(v2.v2_lab_create_recording)
        self.assertIn("take_index = len(spoken_arc_sessions(", src)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SetupEndpointTests(unittest.TestCase):
    """BE-2 — minimal, latest-take, owner-only."""

    def setUp(self):
        self.app = Flask(__name__)

    def _get(self, sessions, *, owned=True):
        with self.app.test_request_context():
            request.user_id = UID
            with patch("routes.v2.arcs._arc_owned_by_caller",
                              return_value=(owned, sessions)):
                out = v2.v2_explore_arc_setup.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status

    def test_latest_take_context_wins(self):
        sessions = [
            {"id": T1, "take_index": 1, "recording_kind": "spoken",
             "intake_context": {"topic": "old topic", "audience": "team",
                                "target_length_seconds": 120}},
            {"id": T2, "take_index": 2, "recording_kind": "spoken",
             "intake_context": {"topic": "the talk", "audience": "investors",
                                "strategic_context": "board wants the raise",
                                "target_length_seconds": 300,
                                "slides": [{"title": "one"}],
                                "presentation_ref": "deck.pdf"}},
        ]
        body, status = self._get(sessions)
        self.assertEqual(status, 200)
        self.assertEqual(body["topic"], "the talk")
        self.assertEqual(body["audience"], "investors")
        self.assertEqual(body["strategic_context"], "board wants the raise")
        self.assertEqual(body["target_length_seconds"], 300)
        self.assertEqual(body["slides"], [{"title": "one"}])
        self.assertEqual(body["presentation_ref"], "deck.pdf")

    def test_payload_is_exactly_the_setup_fields(self):
        sessions = [{"id": T1, "take_index": 1, "recording_kind": "spoken",
                     "intake_context": {"topic": "t"}}]
        body, _ = self._get(sessions)
        self.assertEqual(
            set(body),
            {"arc_id", "topic", "audience", "strategic_context",
             "target_length_seconds", "slides", "presentation_ref"})

    def test_reads_are_not_a_setup_source(self):
        sessions = [
            {"id": T1, "take_index": 1, "recording_kind": "spoken",
             "intake_context": {"topic": "the spoken topic"}},
            {"id": T2, "take_index": 1, "recording_kind": "read",
             "paired_session_id": T1,
             "intake_context": {"topic": "a read", "read_target":
                                "ideal_text"}},
        ]
        body, _ = self._get(sessions)
        self.assertEqual(body["topic"], "the spoken topic")

    def test_unowned_and_empty_404(self):
        _, status = self._get([], owned=False)
        self.assertEqual(status, 404)
        _, status = self._get([])
        self.assertEqual(status, 404)

    def test_ac9_no_scores_or_take_data(self):
        import json
        sessions = [{"id": T1, "take_index": 1, "recording_kind": "spoken",
                     "intake_context": {"topic": "t", "audience": "a"}}]
        body, _ = self._get(sessions)
        raw = json.dumps(body)
        for banned in ("take_count", "overall_score", "power_score",
                       "take_index", "session_id", "charisma"):
            self.assertNotIn(banned, raw)


if __name__ == "__main__":
    unittest.main()
