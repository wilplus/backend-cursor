"""A coach's original judgment is never editable (LOCKIN §5c; contract 34;
W6 2026-10-05), and each rating says why the clip was in front of the coach
(decisions K9).

Contract 34: "The original coach judgment is never editable; reconsideration
is a separately timestamped, provenance-bearing revision." Until now a
re-label upserted over the rater's row in confidence_labels, and since the
Read screen records the coach's exposure, the new row was stamped not blind:
the original blind judgment left every quorum, Album leg and measure.

Pins:
  * the first answer is the judgment of record (confidence_labels);
  * a later answer by the same coach is appended to label_revision as a
    reconsideration that supersedes the newest revision, and confidence_labels
    is never written; no second chain judgment; nothing of record is
    reconciled, except the User Yes / Coach No re-review, which the policy
    reads on its own answer;
  * a reconsideration that could not be kept is a 500, never a "saved";
  * K9: every rating carries the policy version, the reason and the sampling
    probability, server-side: a corpus cohort's own record, the walk's census
    of reached bookmarks (probability 1), else a reason with no probability;
  * the K9 stamps never reach the rater before the judgment and ride the
    retry that drops stamp columns a container's schema lacks.
"""
from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

try:
    from flask import Flask, request
    from routes.v2 import coach as v2_coach
    from services.db import DatabaseService, db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e

from services import coach_moments_queue as cmq

SNIP = "22222222-2222-4222-8222-222222222222"
SID = "11111111-1111-4111-8111-111111111111"
COACH = "33333333-3333-4333-8333-333333333333"


def _label(rater, value):
    return {"rater_id": rater, "value": value, "lane": "coach", "state_id": "confidence",
            "self_report": False, "unrateable": False}


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class TheRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.upserts: list = []
        self.reconsiderations: list = []
        self.after: list = []
        self.chain: list = []

    def _put(self, labels, body, *, keep=True):
        def upsert(**kwargs):
            self.upserts.append(kwargs)
            return True

        def reconsider(**kwargs):
            self.reconsiderations.append(kwargs)
            if not keep:
                raise RuntimeError("label_revision unavailable")
            return {"id": 9, **kwargs}

        raw = inspect.unwrap(v2_coach.v2_coach_put_confidence_label)
        with self.app.test_request_context(method="PUT", json=body):
            request.user_id = COACH
            with patch.object(db, "get_snippet_by_id",
                              return_value={"id": SNIP, "session_id": SID, "transcript": "w"}), \
                    patch.object(db, "v2_get_session_by_id",
                                 return_value={"id": SID, "user_id": "speaker-1", "arc_id": "a"}), \
                    patch.object(db, "get_confidence_labels_by_snippet_ids",
                                 return_value={SNIP: labels}), \
                    patch.object(db, "upsert_state_rating", side_effect=upsert), \
                    patch.object(db, "append_label_reconsideration", side_effect=reconsider), \
                    patch.object(db, "list_take_feedback_self_reports_by_snippet",
                                 return_value=[]), \
                    patch.object(v2_coach, "_rater_language_outcome",
                                 return_value=("matched", "en")), \
                    patch.object(v2_coach, "_session_shows_slides", return_value=False), \
                    patch("services.coach_judgement_record.canonical_dual_write"), \
                    patch.object(v2_coach, "_rating_selection",
                                 return_value={"selection_reason": "reached_bookmark"}), \
                    patch.object(v2_coach, "_confidence_chain_judgment",
                                 side_effect=lambda *a, **k: self.chain.append(k)), \
                    patch.object(v2_coach, "_after_coach_judgement",
                                 side_effect=lambda *a, **k: self.after.append(k)):
                result = raw(SNIP)
        resp, status = result if isinstance(result, tuple) else (result, 200)
        return resp.get_json(), status

    def test_the_first_answer_is_the_judgment_of_record(self):
        body, status = self._put([], {"state_id": "confidence", "value": "no"})
        self.assertEqual(status, 200)
        self.assertEqual(len(self.upserts), 1)
        self.assertEqual(self.upserts[0]["selection"], {"selection_reason": "reached_bookmark"})
        self.assertEqual(self.reconsiderations, [])
        self.assertEqual(len(self.chain), 1)
        self.assertEqual(len(self.after), 1)

    def test_a_later_answer_is_a_reconsideration_never_written_over_the_original(self):
        body, status = self._put([_label(COACH, "no")], {"state_id": "confidence", "value": "yes"})
        self.assertEqual(status, 200)
        self.assertEqual(self.upserts, [], "confidence_labels is never written again")
        self.assertEqual(len(self.reconsiderations), 1)
        self.assertEqual(self.reconsiderations[0]["row"]["value"], "yes")
        self.assertEqual(self.reconsiderations[0]["rater_id"], COACH)
        self.assertEqual(self.chain, [], "the chain's judgment is immutable")
        self.assertEqual(self.after, [], "nothing of record changed")
        self.assertIsNone(body["mlc2"])

    def test_a_re_review_is_the_one_later_answer_the_policy_reads(self):
        _body, status = self._put([_label(COACH, "no")],
                                  {"state_id": "confidence", "value": "no", "re_review": True})
        self.assertEqual(status, 200)
        self.assertEqual(self.upserts, [])
        self.assertEqual(len(self.reconsiderations), 1)
        self.assertEqual(len(self.after), 1)
        self.assertTrue(self.after[0]["is_rereview"])

    def test_a_reconsideration_that_was_not_kept_is_never_reported_saved(self):
        body, status = self._put([_label(COACH, "no")],
                                 {"state_id": "confidence", "value": "yes"}, keep=False)
        self.assertEqual(status, 500)
        self.assertEqual(body["code"], "SERVER_ERROR")
        self.assertEqual(self.upserts, [])

    def test_another_coach_s_row_does_not_make_this_one_a_reconsideration(self):
        _body, status = self._put([_label("other-coach", "yes")],
                                  {"state_id": "confidence", "value": "yes"})
        self.assertEqual(status, 200)
        self.assertEqual(len(self.upserts), 1)
        self.assertEqual(self.reconsiderations, [])


class _Query:
    def __init__(self, client, table):
        self.client, self.table = client, table
        self.payload = None

    def select(self, *_a):
        return self

    def insert(self, payload):
        self.payload = payload
        return self

    def eq(self, *_a):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a):
        return self

    def execute(self):
        self.client.calls.append((self.table, self.payload))
        if self.payload is not None:
            return type("R", (), {"data": [{"id": 12, **self.payload}]})()
        return type("R", (), {"data": [{"id": 11}]})()


class _Client:
    def __init__(self):
        self.calls: list = []

    def table(self, name):
        return _Query(self, name)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class TheRevisionWriterTests(unittest.TestCase):
    def _service(self):
        service = DatabaseService.__new__(DatabaseService)
        service.client = _Client()
        return service

    def test_a_reconsideration_supersedes_the_newest_revision_and_touches_no_label(self):
        service = self._service()
        with patch("services.coach_exposure.rating_is_blind", return_value=False):
            row = service.append_label_reconsideration(
                snippet_id=SNIP, row={"state_id": "confidence", "value": "yes"},
                rater_id=COACH, session_id=SID, lane="coach",
                selection={"selection_policy_version": "coach-walk-reached-bookmarks-v1",
                           "selection_reason": "reached_bookmark",
                           "sampling_probability": 1.0})
        tables = [t for t, _ in service.client.calls]
        self.assertNotIn("confidence_labels", tables)
        self.assertEqual(tables, ["label_revision", "label_revision"])
        inserted = service.client.calls[-1][1]
        self.assertTrue(inserted["reconsideration"])
        self.assertEqual(inserted["supersedes_id"], 11)
        self.assertEqual(inserted["value"], "yes")
        self.assertEqual(inserted["origin"], "live")
        self.assertEqual(inserted["selection_reason"], "reached_bookmark")
        self.assertEqual(inserted["sampling_probability"], 1.0)
        self.assertEqual(row["id"], 12)

    def test_the_selection_stamp_rides_the_rating_and_its_shadow(self):
        payload = self._service()._rating_payload(
            snippet_id=SNIP, row={"state_id": "confidence", "value": "no"},
            rater_id=None, session_id=SID, lane="coach", intensity=None,
            model_version_at_time=None, probe_score_at_time=None,
            machine_value=None, self_report=False,
            selection={"selection_policy_version": "p", "selection_reason": "r",
                       "sampling_probability": 0.25})
        self.assertEqual((payload["selection_policy_version"], payload["selection_reason"],
                          payload["sampling_probability"]), ("p", "r", 0.25))
        shadow = DatabaseService._label_revision_row(payload)
        self.assertEqual(shadow["sampling_probability"], 0.25)

    def test_a_probability_outside_the_range_is_dropped_never_coerced(self):
        from services.db import _selection_columns
        self.assertEqual(_selection_columns({"sampling_probability": 0}), {})
        self.assertEqual(_selection_columns({"sampling_probability": 1.5}), {})
        self.assertEqual(_selection_columns({"sampling_probability": True}), {})
        self.assertEqual(_selection_columns(None), {})

    def test_a_schema_without_the_stamp_columns_retries_without_them(self):
        source = inspect.getsource(DatabaseService._retry_rating_without_stamps)
        self.assertIn("*SELECTION_COLUMNS", source)


class TheSelectionStampTests(unittest.TestCase):
    def test_a_reached_bookmark_is_the_walk_s_census(self):
        self.assertEqual(cmq.selection_stamp(reached_bookmark=True), {
            "selection_policy_version": "coach-walk-reached-bookmarks-v1",
            "selection_reason": "reached_bookmark", "sampling_probability": 1.0})

    def test_a_clip_outside_the_walk_and_an_unread_one_carry_no_probability(self):
        self.assertEqual(cmq.selection_stamp(reached_bookmark=False)["selection_reason"],
                         "outside_walk")
        self.assertIsNone(cmq.selection_stamp(reached_bookmark=False)["sampling_probability"])
        self.assertEqual(cmq.selection_stamp(reached_bookmark=None)["selection_reason"],
                         "unknown")

    def test_a_corpus_cohort_keeps_its_own_record(self):
        record = {"snippet_id": "s", "policy_version": "label-queue-mixed-v1",
                  "reason": "random_exploration", "sampling_probability": 0.083333}
        self.assertEqual(cmq.selection_stamp(cohort_record=record, reached_bookmark=True), {
            "selection_policy_version": "label-queue-mixed-v1",
            "selection_reason": "random_exploration", "sampling_probability": 0.083333})

    @unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
    def test_the_route_reads_the_walk_s_reach_for_a_speakers_take(self):
        sess = {"id": SID, "arc_id": "a", "intake_context": {}}
        with patch.object(v2_coach, "_bookmarked_snippet_ids", return_value={SNIP}), \
                patch.object(db, "list_exercise_coach_requests_for_sessions", return_value={}), \
                patch.object(db, "list_moment_events_for_sessions",
                             return_value=[{"take_session_id": SID, "snippet_id": SNIP,
                                            "event": "opened"}]), \
                patch.object(db, "list_confident_voice_answered_moments", return_value=[]):
            stamp = v2_coach._rating_selection(sess, SID, SNIP)
            self.assertEqual(stamp["selection_reason"], "reached_bookmark")
            other = v2_coach._rating_selection(sess, SID, "not-a-bookmark")
            self.assertEqual(other["selection_reason"], "outside_walk")

    @unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
    def test_an_imported_clip_uses_its_cohort_record(self):
        sess = {"id": SID, "source": "training_import", "intake_context": {
            "label_queue_selection": [{"snippet_id": SNIP, "policy_version": "v",
                                       "reason": "model_boundary",
                                       "sampling_probability": 0.5}]}}
        stamp = v2_coach._rating_selection(sess, SID, SNIP)
        self.assertEqual((stamp["selection_reason"], stamp["sampling_probability"]),
                         ("model_boundary", 0.5))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
