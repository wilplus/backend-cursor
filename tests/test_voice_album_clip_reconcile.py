"""`reconcile_voice_album_clip`, pinned path by path.

The exact-clip reconciler admits a moment only when Machine Yes, User Yes
and a professional Coach Yes on the PUBLISHED Take align on that clip (L3),
and removes one only on an explicit professional No. A practice attempt is
reconciled from its own three recorded decisions instead. Every other read
is a no-op that can never withdraw a saved moment.
"""
from __future__ import annotations

import logging
import unittest

from services.voice_album import reconcile_voice_album_clip

ARC = "arc-1"
CLIP = "snip-1"
TAKE = "take-1"


class _Db:
    def __init__(self, *, attempt=None, practice=None, self_reports=(),
                 routes=(), suggestion=None, labels=(), session=None,
                 broken=False):
        self.attempt = attempt
        self.practice = practice
        self.self_reports = list(self_reports)
        self.routes = list(routes)
        self.suggestion = suggestion
        self.labels = list(labels)
        self.session = session
        self.broken = broken
        self.writes: list[tuple] = []
        self.reads: list[str] = []

    def get_confident_voice_practice_attempt(self, target):
        self.reads.append("attempt")
        if self.broken:
            raise RuntimeError("database down")
        return self.attempt

    def get_confident_voice_practice(self, practice_id):
        self.reads.append(f"practice:{practice_id}")
        return self.practice

    def list_confident_voice_self_reports(self, arc):
        return self.self_reports

    def list_owner_voice_album_routes(self, arc):
        return self.routes

    def get_moment_suggestions_by_arc(self, arc):
        return {CLIP: self.suggestion} if self.suggestion else {}

    def get_confidence_labels_by_snippet_ids(self, ids):
        return {CLIP: self.labels}

    def v2_get_session_by_id(self, session_id):
        self.reads.append(f"session:{session_id}")
        return self.session

    def insert_voice_album_entry(self, **kwargs):
        self.writes.append(("insert", kwargs))
        return True

    def delete_voice_album_entry(self, **kwargs):
        self.writes.append(("delete", kwargs))
        return True

    def insert_voice_album_practice_entry(self, **kwargs):
        self.writes.append(("insert_practice", kwargs))
        return True

    def delete_voice_album_practice_entry(self, **kwargs):
        self.writes.append(("delete_practice", kwargs))
        return True


_USER_YES = {"snippet_id": CLIP, "response": "yes", "slide_index": 2}
_STAR = {"kind": "emphasize", "trigger": "confident"}
_COACH_YES = {"lane": "coach", "value": "yes"}
_COACH_NO = {"lane": "coach", "value": "no"}
_PUBLISHED = {"results_published_at": "2026-09-01", "project_id": ARC}


def _aligned(**overrides):
    fields = dict(self_reports=[_USER_YES], suggestion=_STAR,
                  labels=[_COACH_YES], session=_PUBLISHED)
    fields.update(overrides)
    return _Db(**fields)


def _run(database, *, take=TAKE, arc=ARC, clip=CLIP):
    return reconcile_voice_album_clip(
        arc, clip, take_session_id=take, database=database)


class OriginalClip(unittest.TestCase):
    def test_three_aligned_legs_on_a_published_take_admit_the_clip(self):
        database = _aligned()
        self.assertTrue(_run(database))
        self.assertEqual(database.writes, [("insert", {
            "arc_id": ARC, "snippet_id": CLIP, "take_session_id": TAKE,
            "slide_index": 2,
        })])
        self.assertIn(f"session:{TAKE}", database.reads)

    def test_a_bool_slide_and_an_empty_take_are_stored_as_none(self):
        database = _aligned(self_reports=[dict(_USER_YES, slide_index=True)])
        database.session = dict(_PUBLISHED)
        self.assertTrue(_run(database, take=""))
        self.assertEqual(database.writes[0][1]["slide_index"], None)
        self.assertEqual(database.writes[0][1]["take_session_id"], None)

    def test_the_legacy_route_is_the_user_leg_when_no_self_report_exists(self):
        database = _aligned(self_reports=[], routes=[_USER_YES])
        self.assertTrue(_run(database))
        self.assertEqual(database.writes[0][0], "insert")

    def test_a_professional_no_on_the_published_take_removes_the_clip(self):
        database = _aligned(labels=[_COACH_NO])
        self.assertTrue(_run(database))
        self.assertEqual(database.writes, [("delete", {
            "arc_id": ARC, "snippet_id": CLIP,
        })])

    def test_an_unpublished_no_withdraws_nothing(self):
        database = _aligned(labels=[_COACH_NO],
                            session={"project_id": ARC})
        self.assertFalse(_run(database))
        self.assertEqual(database.writes, [])

    def test_another_projects_take_never_matches(self):
        database = _aligned(session=dict(_PUBLISHED, project_id="arc-2"))
        self.assertFalse(_run(database))
        self.assertEqual(database.writes, [])

    def test_the_arc_id_stands_in_for_a_missing_project_id(self):
        database = _aligned(session={"results_published_at": "2026-09-01",
                                     "arc_id": ARC})
        self.assertTrue(_run(database))

    def test_each_missing_leg_is_a_no_op(self):
        for name, database in (
            ("user", _aligned(self_reports=[
                dict(_USER_YES, response="no")])),
            ("machine", _aligned(suggestion={"kind": "emphasize",
                                             "trigger": "neutral"})),
            ("coach", _aligned(labels=[])),
            ("peer coach", _aligned(labels=[{"lane": "peer",
                                             "value": "yes"}])),
        ):
            with self.subTest(missing=name):
                self.assertFalse(_run(database))
                self.assertEqual(database.writes, [])


class PracticeAttempt(unittest.TestCase):
    _ATTEMPT = {"practice_id": "practice-1",
                "coach_confidence_decision": "yes",
                "machine_confidence_decision": "yes",
                "user_answer": "yes"}
    _PRACTICE = {"project_id": ARC, "selected_attempt_id": CLIP,
                 "take_session_id": TAKE, "slide_index": 4}

    def _db(self, attempt=None, practice=None):
        return _Db(attempt=dict(self._ATTEMPT, **(attempt or {})),
                   practice=dict(self._PRACTICE, **(practice or {})))

    def test_the_selected_attempt_with_three_yeses_enters(self):
        database = self._db()
        self.assertTrue(_run(database))
        self.assertEqual(database.writes, [("insert_practice", {
            "arc_id": ARC, "practice_attempt_id": CLIP,
            "take_session_id": TAKE, "slide_index": 4,
        })])
        self.assertIn("practice:practice-1", database.reads)
        self.assertNotIn(f"session:{TAKE}", database.reads)

    def test_a_coach_no_removes_the_attempt(self):
        database = self._db(attempt={"coach_confidence_decision": "no"})
        self.assertTrue(_run(database))
        self.assertEqual(database.writes, [("delete_practice", {
            "arc_id": ARC, "practice_attempt_id": CLIP,
        })])

    def test_an_attempt_that_is_not_the_selected_one_stays_out(self):
        database = self._db(practice={"selected_attempt_id": "other"})
        self.assertFalse(_run(database))
        self.assertEqual(database.writes, [])

    def test_a_missing_leg_stays_out(self):
        for field in ("machine_confidence_decision", "user_answer",
                      "coach_confidence_decision"):
            with self.subTest(field=field):
                database = self._db(attempt={field: None})
                self.assertFalse(_run(database))
                self.assertEqual(database.writes, [])

    def test_another_projects_practice_is_refused_even_on_a_no(self):
        database = self._db(attempt={"coach_confidence_decision": "no"},
                            practice={"project_id": "arc-2"})
        self.assertFalse(_run(database))
        self.assertEqual(database.writes, [])


class Boundaries(unittest.TestCase):
    def test_a_missing_arc_or_clip_reads_nothing(self):
        for arc, clip in (("", CLIP), (ARC, ""), (None, None)):
            database = _aligned()
            self.assertFalse(_run(database, arc=arc, clip=clip))
            self.assertEqual(database.reads, [])

    def test_a_broken_database_logs_and_returns_false(self):
        database = _aligned(broken=True)
        with self.assertLogs("services.voice_album", level=logging.WARNING) as logs:
            self.assertFalse(_run(database))
        self.assertIn(
            f"exact clip reconciliation failed arc={ARC} clip={CLIP}: "
            "database down",
            logs.output[0],
        )
        self.assertEqual(database.writes, [])


if __name__ == "__main__":
    unittest.main()
