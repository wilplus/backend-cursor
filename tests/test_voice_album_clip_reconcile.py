"""`reconcile_voice_album_clip`, pinned path by path.

The exact-clip reconciler admits a moment only when Machine Yes, User Yes
and a professional Coach Yes on a Take of the project align on that clip
(L3; the publish gate left with the arc-level delivery, contract 65),
and removes one only on an explicit professional No. A practice attempt is
reconciled from its own three recorded decisions instead. Every other read
is a no-op that can never withdraw a saved moment.
"""
from __future__ import annotations

import unittest
from unittest import mock

from services.voice_album import reconcile_voice_album_clip

ARC = "arc-1"
CLIP = "snip-1"
TAKE = "take-1"


# THE MACHINE LEG IS THE CLIP'S OWN READ (founder 2026-10-05, Q5; N45).
# These fakes still describe a confident clip the way the old lane did (an
# EMPHASIZE "confident" row); the read below translates that into the read
# the album now asks for, so each test keeps its meaning. A reader that
# raises is a clip that cannot be read (None).
def _read_from_star(database, take_session_id, snippet_id):
    try:
        try:
            rows = database.get_moment_suggestions_by_arc("arc-1", strict=True)
        except TypeError:
            rows = database.get_moment_suggestions_by_arc("arc-1")
    except Exception:
        return None
    row = (rows or {}).get(str(snippet_id))
    if (isinstance(row, dict) and row.get("kind") == "emphasize"
            and row.get("trigger") == "confident"):
        return "confident"
    return "weak"


_READ_PATCH = mock.patch("services.judgement_follow_up.clip_machine_read",
                         _read_from_star)


def setUpModule():
    _READ_PATCH.start()


def tearDownModule():
    _READ_PATCH.stop()

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


    def test_a_no_on_an_unpublished_take_withdraws_too(self):
        # No publish gate since the arc-level delivery was retired: the
        # coach's No on the walk is final when written.
        database = _aligned(labels=[_COACH_NO],
                            session={"project_id": ARC})
        self.assertTrue(_run(database))
        self.assertEqual(database.writes, [("delete", {
            "arc_id": ARC, "snippet_id": CLIP,
        })])


if __name__ == "__main__":
    unittest.main()
