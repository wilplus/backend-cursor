"""
STORY    As a speaker, I want to add slides to my project, or update them,
         inside the same project, so that my next Take uses them and my Take
         count, my coach's history and my plan carry on. (N257)
OUTCOME
  O1  Updating the slides stores them for the next Take and tells which
      Take that is; the recording screen's setup then serves them and says
      the next Take is the first on new slides. Someone else's project is
      not found, and an empty deck is refused.
  O2  A Take recorded on the new slides is accepted (no 409
      PRESENTATION_LOCKED any more) and spends the stored slides.
  O3  In the chat, a new or updated deck gets Will's signed answer and one
      "update_slides" action, however many Takes are done.
PROVES   O1 -> test_updated_slides_set_up_the_next_take
         O2 -> test_a_take_on_the_new_slides_is_accepted_and_spends_them
         O3 -> test_the_chat_offers_to_update_the_slides_in_this_project
WHY      N257 (founder 2026-10-29). The rewrite of the Ideal Text on that
         Take is proven in tests/test_take_review.py (O4).
"""
from __future__ import annotations

import io
import json
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

try:
    from flask import Flask, request

    from routes.v2 import arcs as arcs_route
    from routes.v2 import lab_recording as lab_route
    from routes.v2 import projects as projects_route
    from services.lab_analysis_dispatch import PendingAnalysis
    _IMPORT_ERROR = None
except Exception as error:  # pragma: no cover
    _IMPORT_ERROR = error

PROJECT = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
USER = "11111111-1111-4111-8111-111111111111"
STRANGER = "99999999-9999-4999-8999-999999999999"
OLD = [{"title": "Intro", "body": "hello"}]
NEW = [{"title": "Intro", "body": "hello"}, {"title": "Pricing", "body": "one"}]


def _take(index, slides):
    return {"id": f"take-{index}", "user_id": USER, "take_index": index,
            "recording_kind": "spoken", "created_at": f"2026-10-2{index}",
            "intake_context": {"topic": "Pitch", "slides": slides}}


class _Projects:
    """The projects table and the project's Takes, in memory."""

    def __init__(self):
        self.row = {"id": PROJECT, "owner_principal_id": f"owner-{USER}",
                    "setup": {"goal": "kept"}, "archived_at": None}
        self.sessions = [_take(1, OLD), _take(2, OLD)]
        self.takes = SimpleNamespace(
            get_arc_sessions=lambda arc_id: [dict(s) for s in self.sessions])

    def get_owner_principal_for_user(self, user_id):
        return {"id": f"owner-{user_id}"}

    def get_project_for_owner(self, project_id, principal_id):
        mine = (project_id == PROJECT
                and principal_id == self.row["owner_principal_id"])
        return dict(self.row) if mine else None

    def get_project_row(self, project_id):
        return dict(self.row) if project_id == PROJECT else None

    def update_project_setup(self, project_id, principal_id, setup):
        if not self.get_project_for_owner(project_id, principal_id):
            return None
        self.row["setup"] = dict(setup)
        return dict(self.row)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class DeckUpdateInsideTheProjectTests(unittest.TestCase):

    def setUp(self):
        self.db = _Projects()

    def _put(self, body, *, user_id=USER):
        with Flask(__name__).test_request_context(
                method="PUT", json=body), \
                patch.object(projects_route, "db", self.db):
            request.user_id = user_id
            out = projects_route.v2_update_project_deck.__wrapped__(PROJECT)
        response, status = out if isinstance(out, tuple) else (out, 200)
        return response.get_json(), status

    def _setup(self):
        with Flask(__name__).test_request_context(), \
                patch.object(arcs_route, "db", self.db), \
                patch("routes.v2.arcs.refreshed_media_url",
                      side_effect=lambda ref: ref):
            request.user_id = USER
            out = arcs_route.v2_explore_arc_setup.__wrapped__(PROJECT)
        response, status = out if isinstance(out, tuple) else (out, 200)
        return response.get_json(), status

    def test_updated_slides_set_up_the_next_take(self):
        before, _ = self._setup()
        self.assertEqual((before["slides"], before["deck_changed"],
                          before["deck_since_take"]), (OLD, False, 1))

        body, status = self._put({"slides": NEW,
                                  "presentation_ref": "decks/new.pdf"})
        self.assertEqual((status, body), (200, {"project_id": PROJECT,
                                                "next_take": 3}))
        self.assertEqual(self.db.row["setup"]["goal"], "kept")
        self.assertEqual(len(self.db.sessions), 2)       # no Take touched

        after, status = self._setup()
        self.assertEqual(status, 200)
        self.assertEqual((after["slides"], after["presentation_ref"]),
                         (NEW, "decks/new.pdf"))
        self.assertEqual((after["deck_changed"], after["deck_since_take"]),
                         (True, None))
        self.assertEqual(after["topic"], "Pitch")

        self.assertEqual(self._put({"slides": NEW}, user_id=STRANGER)[1], 404)
        empty, status = self._put({"slides": [], "presentation_ref": None})
        self.assertEqual((status, empty["code"]), (400, "INVALID_INPUT"))

    def _record(self, slides):
        from werkzeug.datastructures import FileStorage
        data = {"audio_file": FileStorage(
            stream=io.BytesIO(b"x" * 32), filename="take.webm",
            content_type="audio/webm"),
            "topic": "Pitch", "slides": json.dumps(slides)}
        project = SimpleNamespace(
            project_id=PROJECT, idempotency_key="upload-3",
            duplicate_take=None, principal=SimpleNamespace(id=f"owner-{USER}"),
            project=self.db.get_project_row(PROJECT))
        auth = MagicMock(enforced=False)
        auth.resolve_acquisition_principal.return_value = f"owner-{USER}"
        fake_db = MagicMock()
        fake_db.takes.get_arc_sessions = self.db.takes.get_arc_sessions
        fake_db.update_project_setup = self.db.update_project_setup
        with ExitStack() as stack, Flask(__name__).test_request_context(
                method="POST", data=data, content_type="multipart/form-data"):
            for target, kw in (
                ("routes.v2.lab_recording.db", {"new": fake_db}),
                ("routes.v2.lab_recording.resolve_take_project",
                 {"return_value": project}),
                ("routes.v2.lab_recording.ProcessingAuthorizationService",
                 {"return_value": auth}),
                ("services.processing_authorization."
                 "ProcessingAuthorizationService", {"return_value": auth}),
                ("routes.v2.lab_recording._is_data_foundation_canary_owner",
                 {"return_value": False}),
                ("routes.v2.lab_recording.require_analyzable_recording",
                 {"return_value": {"ok": True, "duration_sec": 30}}),
                ("services.lab_audio_storage.put_lab_audio_bytes",
                 {"return_value": "lab-bucket"}),
                ("services.lab_audio_storage.storage_provider",
                 {"return_value": "r2"}),
                ("services.create_take.reserve_take", {"return_value": 3}),
                ("routes.v2.lab_recording.dispatch_recording_analysis",
                 {"return_value": PendingAnalysis({"state": "processing"})}),
            ):
                stack.enter_context(patch(target, **kw))
            out = lab_route.v2_lab_create_recording.__wrapped__()
        response, status = out if isinstance(out, tuple) else (out, 200)
        return response.get_json(), status

    def test_a_take_on_the_new_slides_is_accepted_and_spends_them(self):
        self._put({"slides": NEW})
        body, status = self._record(NEW)
        self.assertEqual(status, 202, body)
        self.assertNotIn("next_deck", self.db.row["setup"])
        self.assertEqual(self.db.row["setup"]["goal"], "kept")

    def test_the_chat_offers_to_update_the_slides_in_this_project(self):
        from services.presentation_change_intent import (
            handle_presentation_change,
        )
        for takes in (0, 4):
            for said in ("I have a new deck", "I updated my slides",
                         "can I upload the new version of my pitch deck?"):
                with self.subTest(said=said, takes=takes):
                    reply = handle_presentation_change(said, {
                        "has_current_project": True,
                        "completed_takes": takes})
                    self.assertEqual(reply["answer"], (
                        "You can update the slides in this project. "
                        "Your next Take uses them."))
                    self.assertEqual(reply["suggested_actions"],
                                     ["update_slides"])


if __name__ == "__main__":
    unittest.main()
