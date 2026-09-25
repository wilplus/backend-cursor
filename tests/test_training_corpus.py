"""The training-corpus copy job (services/training_corpus.py, P3).

Dark first: the switch is a code constant, False, and while it is the enqueue
and the job both return at once. Then, with the switch forced on in-process
only, what the job copies (SPEC §4.3, §10 invariant 7): nothing without an
active training yes, only the Confident Voice moments the speaker was shown,
never a snippet from another Take, and no bytes left behind when the database
refuses the copy.
"""
from __future__ import annotations

import hashlib
import inspect
import unittest
from unittest import mock

from config import Config
from services import training_corpus as tc


class DarkTests(unittest.TestCase):
    def test_the_switch_is_a_code_constant_and_it_is_off(self):
        self.assertIs(Config.MLC2_TRAINING_CORPUS_COPY_ENABLED, False)
        import config
        source = inspect.getsource(config)
        line = next(line for line in source.splitlines()
                    if "MLC2_TRAINING_CORPUS_COPY_ENABLED =" in line)
        self.assertNotIn("getenv", line)

    def test_off_means_nothing_is_enqueued(self):
        with mock.patch("services.job_queue.enqueue") as enqueue:
            self.assertFalse(tc.enqueue_corpus_copy("take", "arc", "user"))
        enqueue.assert_not_called()

    def test_off_means_the_job_does_nothing(self):
        db = mock.Mock()
        self.assertEqual(tc.run_corpus_copy("take", "arc", database=db),
                         {"status": "disabled"})
        db.assert_not_called()
        self.assertEqual(db.method_calls, [])

    def test_the_analysis_run_calls_it_unbranched_after_the_bake(self):
        from services import analysis_worker
        source = inspect.getsource(analysis_worker._run_full_analysis_impl)
        bake = source.index("enqueue_bake(arc_id, user_id, recording_kind)")
        copy = source.index("enqueue_corpus_copy(session_id, arc_id, user_id)")
        self.assertLess(bake, copy)
        between = source[bake:copy]
        self.assertNotIn("if ", between)

    def test_the_corpus_prefix_is_classified_as_user_content(self):
        from services.user_content_keys import USER_CONTENT_PREFIXES
        self.assertIn("training-corpus/", USER_CONTENT_PREFIXES)


WHOLE = b"whole-take-audio"
CLIP = b"clip-bytes"


class _Db:
    def __init__(self, *, consent=None, frozen=True, refuse=False):
        self.consent = consent if consent is not None else {
            "active": True, "grant_event_id": "grant-1"}
        self.frozen = frozen
        self.refuse = refuse
        self.recorded: list[dict] = []

    def v2_get_session_by_id(self, _sid):
        return {"owner_principal_id": None}

    def get_project_owner_principal(self, _arc):
        return "principal-1"

    def get_mlc2_training_consent_status(self, principal):
        assert principal == "principal-1"
        return self.consent

    def get_ideal_text_feedback_set(self, arc, take):
        if not self.frozen:
            return None
        return {"arc_id": arc, "take_session_id": take, "selected_keys": [
            {"id": "cv-1", "kind": "bold", "source": "confident_voice",
             "feedback_family": "confident_voice", "snippet_id": "snip-1"},
            {"id": "cv-other", "kind": "bold", "source": "confident_voice",
             "feedback_family": "confident_voice", "snippet_id": "snip-other"},
            {"id": "rw", "kind": "replace", "source": "wording",
             "feedback_family": "rewrite_clarity"},
        ]}

    def get_snippet_by_id(self, snippet_id):
        take = "take-1" if snippet_id == "snip-1" else "take-other"
        return {"id": snippet_id, "session_id": take,
                "transcript": "Every word counts.",
                "start_offset_ms": 1000, "duration_ms": 3000}

    def get_take_audio_object(self, _take):
        return {"storage_provider": "r2", "bucket": "lab", "object_key": "k",
                "exact_bytes_sha256": hashlib.sha256(WHOLE).hexdigest()}

    def get_confidence_labels_by_snippet_ids(self, ids):
        return {i: [{"lane": "coach", "state_id": "confidence",
                     "value": "yes", "self_report": False}] for i in ids}

    def record_training_corpus_item(self, item):
        if self.refuse:
            raise RuntimeError("TRAINING_CORPUS_NO_ACTIVE_YES")
        self.recorded.append(item)
        return {"id": f"item-{len(self.recorded)}"}


class JobTests(unittest.TestCase):
    def setUp(self):
        patches = [
            # The job's own switch reader, not Config: other suites reload
            # the config module, and a patch on a stale class reaches nobody.
            mock.patch.object(tc, "copy_enabled", return_value=True),
            mock.patch("services.lab_audio_storage.get_exact_storage_object_bytes",
                       return_value=WHOLE),
            mock.patch("services.blind_review_media.render_blind_clip_wav",
                       return_value=CLIP),
            mock.patch("services.lab_audio_storage.put_lab_audio_bytes",
                       return_value="lab"),
            mock.patch("services.lab_audio_storage.storage_provider",
                       return_value="r2"),
            mock.patch("services.lab_audio_storage.delete_verified_lab_audio_object"),
            mock.patch("services.job_queue.enqueue", return_value=True),
        ]
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.delete = self.mocks[5]
        self.enqueue = self.mocks[6]

    def test_no_training_yes_copies_nothing(self):
        db = _Db(consent={"active": False})
        self.assertEqual(tc.run_corpus_copy("take-1", "arc", database=db),
                         {"status": "no_training_yes"})
        self.assertEqual(db.recorded, [])

    def test_the_shown_moment_is_copied_three_ways_and_nothing_else(self):
        db = _Db()
        result = tc.run_corpus_copy("take-1", "arc", database=db)
        self.assertEqual(result, {"status": "copied", "items": 3})
        kinds = {item["item_kind"]: item for item in db.recorded}
        self.assertEqual(set(kinds), {"transcript_span", "audio_segment", "coach_label"})
        self.assertTrue(all(item["source_take_id"] == "take-1" for item in db.recorded))
        audio = kinds["audio_segment"]
        self.assertEqual(audio["storage_key"],
                         "training-corpus/principal-1/grant-1/snip-1.wav")
        self.assertEqual(audio["object_sha256"], hashlib.sha256(CLIP).hexdigest())
        self.assertEqual(kinds["coach_label"]["label_provenance"], "coach")
        self.assertNotIn("label_provenance", kinds["transcript_span"])

    def test_waits_for_the_frozen_set_then_gives_up(self):
        db = _Db(frozen=False)
        self.assertEqual(tc.run_corpus_copy("take-1", "arc", database=db)["status"],
                         "waiting_for_frozen_set")
        self.enqueue.assert_called_once()
        self.assertEqual(
            tc.run_corpus_copy("take-1", "arc", attempt=tc.MAX_WAITS - 1,
                               database=db)["status"], "no_frozen_set")

    def test_a_refused_copy_leaves_no_bytes_behind(self):
        db = _Db(refuse=True)
        tc.run_corpus_copy("take-1", "arc", database=db)
        self.delete.assert_called_once()
        self.assertEqual(self.delete.call_args.args[0],
                         "training-corpus/principal-1/grant-1/snip-1.wav")

    def test_changed_source_bytes_are_not_copied(self):
        db = _Db()
        self.mocks[1].return_value = b"different"
        tc.run_corpus_copy("take-1", "arc", database=db)
        self.assertNotIn("audio_segment",
                         {item["item_kind"] for item in db.recorded})
