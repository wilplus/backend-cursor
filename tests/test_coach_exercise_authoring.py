"""Exercise authoring in the coach panel (founder 2026-09-29, decision 4).

Pins:
  * the coach's save goes through the catalogue with the CMS's refusals,
    source coach_panel; the model's draft kept beside the final is the one
    the server kept on the walk's request, never the client's text (the
    Library's past finals; FL-L3, W6 2026-10-05), and no pair rides a save;
  * a new coach exercise names its main error on every save path, the
    upload seam included, and a named one cannot be cleared (E5);
  * the video is stored, hashed, saved as a new version, transcribed at
    upload, and its transcript's state settled on that version; storage
    that is off or refuses is named, never raised;
  * the draft goes to the coach only and stores nothing; unknown errors
    and an empty request are refused; the library's own finals inform it;
  * the routes are registered, coach-or-admin only, and each calls one
    service function.
"""
from __future__ import annotations

import pathlib
import unittest
from unittest.mock import patch

from services import coach_exercise_authoring as cea
from tests.test_exercise_versions import _Db, _row

ROOT = pathlib.Path(__file__).resolve().parent.parent


class _LibraryDb(_Db):
    def __init__(self, existing=None):
        super().__init__(existing)
        self.principal = {"id": "principal-coach"}

    def list_diagnostic_exercises(self):
        return list(self.rows.values())

    def list_exercise_versions(self, exercise_id):
        return [dict(v) for v in reversed(self.versions)
                if v["exercise_id"] == exercise_id]

    def get_owner_principal_for_user(self, user_id):
        return self.principal


class LibraryTests(unittest.TestCase):
    def test_the_library_reads_with_its_latest_version_and_the_errors(self):
        db = _LibraryDb(existing=_row(version=2))
        db.versions.append({"exercise_id": "land-it", "version": 2, "source": "cms"})
        out = cea.library_for_authoring(db)
        self.assertEqual(out["exercises"][0]["latest_version"]["version"], 2)
        self.assertEqual([e["error_id"] for e in out["speaking_errors"]],
                         ["rushing", "ending_compression"])


REQUEST_ID = "0b6a8c1e-2f3d-4a5b-8c7d-9e0f1a2b3c4d"
WALK_ID = f"coach-request-{REQUEST_ID}"
MAIN = {"primary_problem_tag": "ending_compression"}


class _WalkDb(_LibraryDb):
    """The library plus the walk's request, which keeps the model's draft."""

    def __init__(self, existing=None, request=None):
        super().__init__(existing)
        self.request = request

    def get_exercise_coach_request_by_id(self, request_id):
        if self.request and str(self.request.get("id")) == str(request_id):
            return dict(self.request)
        return None


def _walk_request(**over):
    return {"id": REQUEST_ID, "take_session_id": "take-1", "snippet_id": "snip-1",
            "owner_user_id": "speaker-1", "kind": "error",
            "draft_surface": "exercise_script", "draft_text": "The model's script.",
            "draft_model_version": "gpt-test-1", **over}


class SaveTests(unittest.TestCase):
    def test_a_walk_save_keeps_the_request_s_model_draft_beside_the_final(self):
        """C2/C5: the model's draft is the one the server kept on the request,
        with its model version; the client's text is not taken on its word."""
        db = _WalkDb(request=_walk_request())
        out = cea.save_from_coach_panel(
            db, {**_row(exercise_id=WALK_ID, matching_criteria=MAIN),
                 "ai_draft_text": "Something else.", "ai_draft_model_version": ""},
            coach_id="coach-1")
        self.assertEqual(out["version"], 1)
        row = db.versions[0]
        self.assertEqual((row["source"], row["created_by"]), ("coach_panel", "coach-1"))
        self.assertEqual(row["ai_draft_text"], "The model's script.")
        self.assertEqual(row["ai_draft_model_version"], "gpt-test-1")
        # The draft is not a catalogue field: the live row never carries it.
        self.assertNotIn("ai_draft_text", db.rows[WALK_ID])

    def test_a_library_save_never_keeps_a_past_final_as_the_model_draft(self):
        """FL-L3: the Library shows a previous coach's or the founder's final
        as its starting text. It is not the model's draft and is never
        stored as one, and no pair is recorded from a Library save."""
        db = _LibraryDb()
        with patch("services.feedback_pairs.record_pair") as pair:
            out = cea.save_from_coach_panel(
                db, {**_row(matching_criteria=MAIN),
                     "ai_draft_text": "A coach's earlier final.",
                     "ai_draft_model_version": "m1"}, coach_id="coach-1")
        self.assertEqual(out["version"], 1)
        row = db.versions[0]
        self.assertIsNone(row["ai_draft_text"])
        self.assertIsNone(row["ai_draft_model_version"])
        pair.assert_not_called()

    def test_a_new_coach_exercise_without_its_main_error_is_refused(self):
        """E5 / P2-4, on /coach/exercises: the backend refuses, not only the
        frontend."""
        from services.diagnostic_exercise_catalogue import CatalogueRefusal
        db = _LibraryDb()
        with self.assertRaises(CatalogueRefusal) as ctx:
            cea.save_from_coach_panel(db, _row(), coach_id="coach-1")
        self.assertEqual(ctx.exception.code, "MAIN_TARGET_REQUIRED")
        self.assertEqual(db.rows, {})

    def test_main_target_is_the_short_way_to_name_it(self):
        db = _LibraryDb()
        out = cea.save_from_coach_panel(
            db, {**_row(acoustic_problem_tags=["rushing"]),
                 "main_target": "ending_compression"}, coach_id="coach-1")
        live = out["exercise"]
        self.assertEqual(live["matching_criteria"]["primary_problem_tag"],
                         "ending_compression")
        self.assertEqual(live["acoustic_problem_tags"], ["ending_compression", "rushing"])

    def test_a_legacy_row_without_a_main_error_may_still_be_edited(self):
        db = _LibraryDb(existing=_row())
        out = cea.save_from_coach_panel(
            db, _row(title="Land the ending, slower"), coach_id="coach-1")
        self.assertEqual(out["exercise"]["title"], "Land the ending, slower")

    def test_a_main_error_once_named_cannot_be_cleared(self):
        from services.diagnostic_exercise_catalogue import CatalogueRefusal
        db = _LibraryDb(existing=_row(matching_criteria=MAIN))
        with self.assertRaises(CatalogueRefusal) as ctx:
            cea.save_from_coach_panel(db, _row(matching_criteria={}), coach_id="c")
        self.assertEqual(ctx.exception.code, "MAIN_TARGET_REQUIRED")

    def test_the_cms_refusals_are_the_coach_s_refusals(self):
        from services.diagnostic_exercise_catalogue import CatalogueRefusal
        with self.assertRaises(CatalogueRefusal):
            cea.save_from_coach_panel(
                _LibraryDb(), _row(acoustic_problem_tags=["mumbling"]), coach_id="c")


class VideoTests(unittest.TestCase):
    def _attach(self, db, *, store=None, transcribe=None, definition=None,
                exercise_id="land-it"):
        store = store or (lambda b, f, ct: "https://cdn.example/journal/exercise/x.mp4")
        transcribe = transcribe or (lambda *_a, **_k: (
            "done", {"transcript": "Land it.", "language": "en"}, "en"))
        with patch.object(cea, "store_exercise_video", store), \
                patch("services.exercise_versions.transcribe_exercise_video", transcribe):
            return cea.attach_video(
                db, exercise_id=exercise_id, coach_id="coach-1",
                video_bytes=b"video-bytes", filename="clip.mp4",
                content_type="video/mp4", definition=definition)

    def test_a_new_exercise_arrives_with_its_video_in_one_call(self):
        db = _LibraryDb()
        definition = {k: v for k, v in _row(matching_criteria=MAIN).items()
                      if k not in ("explanation_video_url", "version")}
        definition["ai_draft_text"] = "A past final shown as the start."
        definition["ai_draft_model_version"] = "m-1"
        status, payload = self._attach(db, definition=definition)
        self.assertEqual(status, 200)
        self.assertEqual(payload["version"], 1)
        live = db.rows["land-it"]
        self.assertEqual(live["explanation_video_url"],
                         "https://cdn.example/journal/exercise/x.mp4")
        self.assertEqual(live["acoustic_problem_tags"], _row()["acoustic_problem_tags"])
        row = db.versions[0]
        self.assertEqual(row["source"], "coach_panel")
        # The Library kept no model draft: the client's text is not one (FL-L3).
        self.assertIsNone(row["ai_draft_text"])
        self.assertIsNone(row["ai_draft_model_version"])
        self.assertEqual(row["transcript_status"], "pending")

    def test_the_walk_s_upload_seam_refuses_a_new_exercise_without_its_main_error(self):
        """E5 / P2-4 on the seam the walk uses: refused before the video is
        stored, so nothing is left behind."""
        stored = []

        def store(b, f, ct):
            stored.append(f)
            return "https://cdn.example/journal/exercise/x.mp4"
        db = _WalkDb(request=_walk_request())
        definition = {k: v for k, v in _row(exercise_id=WALK_ID).items()
                      if k not in ("explanation_video_url", "version")}
        status, payload = self._attach(db, store=store, definition=definition,
                                       exercise_id=WALK_ID)
        self.assertEqual((status, payload["code"]), (400, "MAIN_TARGET_REQUIRED"))
        self.assertEqual(stored, [])
        self.assertEqual(db.rows, {})

    def test_the_walk_s_upload_keeps_the_request_s_draft_and_records_no_pair_yet(self):
        """The version row carries the model's draft from the request; the
        pair waits for the request's resolution, which stamps it."""
        db = _WalkDb(request=_walk_request())
        definition = {k: v for k, v in _row(exercise_id=WALK_ID, matching_criteria={
            "requires_multiple_acoustic_signals": True, "max_per_take": 1,
            "primary_problem_tag": "ending_compression"}).items()
            if k not in ("explanation_video_url", "version")}
        definition["ai_draft_text"] = "The model's script."
        with patch("services.feedback_pairs.record_pair") as pair:
            status, _payload = self._attach(db, definition=definition, exercise_id=WALK_ID)
        self.assertEqual(status, 200)
        row = db.versions[0]
        self.assertEqual((row["ai_draft_text"], row["ai_draft_model_version"]),
                         ("The model's script.", "gpt-test-1"))
        # C4: the walk's mirrored default never claims several signals.
        self.assertFalse(db.rows[WALK_ID]["matching_criteria"]
                         ["requires_multiple_acoustic_signals"])
        pair.assert_not_called()

    def test_an_edit_and_a_new_video_merge_over_the_live_row(self):
        db = _LibraryDb(existing=_row(version=1))
        status, payload = self._attach(db, definition={"title": "Land it, slower"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["version"], 2)
        self.assertEqual(db.rows["land-it"]["title"], "Land it, slower")
        self.assertEqual(db.rows["land-it"]["instruction"], _row()["instruction"])

    def test_a_refused_definition_stores_no_video(self):
        stored = []

        def store(b, f, ct):
            stored.append(f)
            return "https://cdn.example/journal/exercise/x.mp4"
        db = _LibraryDb()
        status, payload = self._attach(
            db, store=store, definition={"acoustic_problem_tags": ["rushing"]})
        self.assertEqual(status, 400)
        self.assertIn("title", payload["error"])
        self.assertEqual(stored, [])
        self.assertEqual(db.rows, {})

    def test_the_video_becomes_a_new_version_with_its_lineage_and_transcript(self):
        db = _LibraryDb(existing=_row(version=1))
        status, payload = self._attach(db)
        self.assertEqual(status, 200)
        self.assertEqual(payload["version"], 2)
        self.assertEqual(payload["transcript_status"], "done")
        self.assertEqual(db.rows["land-it"]["explanation_video_url"],
                         "https://cdn.example/journal/exercise/x.mp4")
        row = db.versions[0]
        self.assertEqual(row["transcript_status"], "pending")
        self.assertEqual(row["video_bytes"], len(b"video-bytes"))
        self.assertEqual(len(row["video_sha256"]), 64)
        self.assertEqual(db.settled[0]["status"], "done")
        self.assertEqual(db.settled[0]["version"], 2)
        self.assertEqual(db.settled[0]["language"], "en")

    def test_a_missing_authorization_is_recorded_and_the_upload_succeeds(self):
        db = _LibraryDb(existing=_row(version=1))
        status, payload = self._attach(
            db, transcribe=lambda *_a, **_k: ("coach_authorization_missing", None, None))
        self.assertEqual(status, 200)
        self.assertEqual(payload["transcript_status"], "coach_authorization_missing")
        self.assertEqual(db.settled[0]["status"], "coach_authorization_missing")
        self.assertIsNone(db.settled[0]["transcript"])

    def test_storage_that_is_off_is_503_and_a_failed_put_is_502(self):
        from services.journal_media import JournalMediaError

        def off(*_a):
            raise JournalMediaError("Journal media storage is not configured")

        def broken(*_a):
            raise RuntimeError("boom")
        db = _LibraryDb(existing=_row(version=1))
        self.assertEqual(self._attach(db, store=off)[0], 503)
        self.assertEqual(self._attach(db, store=broken)[0], 502)
        self.assertEqual(db.versions, [])

    def test_an_unknown_exercise_without_a_definition_is_404(self):
        self.assertEqual(self._attach(_LibraryDb())[0], 404)

    def test_the_stored_url_is_public_under_the_journal_base(self):
        with patch("services.journal_media.put_object_bytes",
                   return_value={"public_url": "https://cdn/journal/exercise/k.mp4",
                                 "key": "journal/exercise/k.mp4"}) as put:
            url = cea.store_exercise_video(b"x", "clip.mov", "video/quicktime")
        self.assertEqual(url, "https://cdn/journal/exercise/k.mp4")
        self.assertEqual(put.call_args.kwargs["folder"], "exercise")
        self.assertEqual(put.call_args.kwargs["content_type"], "video/quicktime")


class _Result:
    def __init__(self, text, model="m-test"):
        self.text = text
        self.parsed = None
        self.model = model


class DraftTests(unittest.TestCase):
    def test_the_draft_returns_to_the_coach_and_stores_nothing(self):
        db = _LibraryDb(existing=_row())
        with patch("services.llm.chat_complete", return_value=_Result("Try this.")) as chat:
            status, payload = cea.draft_script(
                db, {"error_ids": ["ending_compression"], "notes": "gentle"},
                coach_id="coach-1")
        self.assertEqual((status, payload), (200, {"draft": "Try this.",
                                                    "model_version": "m-test"}))
        self.assertEqual(db.versions, [])
        kwargs = chat.call_args.kwargs
        self.assertEqual(kwargs["surface"], cea.LLM_SURFACE)
        self.assertEqual(kwargs["user_id"], "coach-1")
        self.assertIn("Say the last word fully.", kwargs["user"])   # the library's own final
        self.assertIn("gentle", kwargs["user"])
        self.assertIn("No scores", kwargs["system"])

    def test_an_empty_or_unknown_error_is_refused(self):
        db = _LibraryDb()
        self.assertEqual(cea.draft_script(db, {}, coach_id="c")[0], 400)
        status, payload = cea.draft_script(db, {"error_ids": ["mumbling"]}, coach_id="c")
        self.assertEqual(status, 400)
        self.assertIn("mumbling", payload["error"])

    def test_no_answer_is_503_never_an_empty_draft(self):
        db = _LibraryDb()
        with patch("services.llm.chat_complete", return_value=None):
            self.assertEqual(cea.draft_script(
                db, {"error_ids": ["rushing"]}, coach_id="c")[0], 503)
        with patch("services.llm.chat_complete", return_value=_Result("   ")):
            self.assertEqual(cea.draft_script(
                db, {"error_ids": ["rushing"]}, coach_id="c")[0], 503)


class RouteTests(unittest.TestCase):
    def test_the_module_is_registered_and_every_route_is_coach_or_admin_only(self):
        from routes.v2 import DOMAIN_MODULES
        self.assertIn("coach_exercises", DOMAIN_MODULES)
        source = (ROOT / "routes" / "v2" / "coach_exercises.py").read_text()
        routes = source.count("@v2_bp.route(")
        self.assertEqual(routes, 4)
        self.assertEqual(source.count("@require_admin_or_coach"), routes)
        for fn in ("library_for_authoring", "save_from_coach_panel",
                   "attach_video", "draft_script"):
            self.assertIn(f"{fn}(", source)
        self.assertNotIn("db.upsert", source)
        self.assertIn("@llm_limit", source)
        self.assertIn("@heavy_limit", source)

    def test_the_draft_spec_exists_and_the_purge_registry_knows_the_table(self):
        from services.llm_config import SPEC_EXERCISE_SCRIPT_DRAFT
        from services.data_purge_registry import NON_SUBJECT_RELATIONS
        self.assertGreater(SPEC_EXERCISE_SCRIPT_DRAFT.max_tokens, 0)
        self.assertIn("diagnostic_exercise_version", NON_SUBJECT_RELATIONS)
        self.assertNotIn("SPEC_EXERCISE_SCRIPT_DRAFT", "")
