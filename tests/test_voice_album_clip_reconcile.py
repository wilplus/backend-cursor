"""
STORY    As a speaker, I want a moment added to my Voice Album only when all
         three yeses align and removed only on a coach's explicit No, so that
         my album is never changed by accident.
OUTCOME
  O1  My yes, the machine's confident read and a professional coach Yes on a
      Take of this project add the clip, on its Take and slide.
  O2  A coach's explicit No removes the clip (no publish gate since the
      arc-level delivery was retired).
  O3  Any other read writes nothing: a missing yes, a weak or unreadable
      machine read, a Take of another project, a database failure.
PROVES   O1 -> test_three_aligned_yeses_add_the_clip
         O2 -> test_a_no_on_an_unpublished_take_withdraws_too
         O3 -> test_any_other_read_writes_nothing
WHY      L3 / contract 65: incomplete reads must never withdraw a saved moment.
"""
from __future__ import annotations

import unittest
from unittest import mock

from services.voice_album import reconcile_voice_album_clip

ARC = "arc-1"
CLIP = "snip-1"
TAKE = "take-1"


class _Db:
    def __init__(self, *, self_reports=(), labels=(), session=None,
                 machine="confident", broken=False):
        self.self_reports = list(self_reports)
        self.labels = list(labels)
        self.session = session
        self.machine = machine          # the clip's own read (Q5, N45)
        self.broken = broken
        self.writes: list[tuple] = []

    def get_confident_voice_practice_attempt(self, target):
        if self.broken:
            raise RuntimeError("database down")
        return None

    def list_confident_voice_self_reports(self, arc):
        return self.self_reports

    def list_owner_voice_album_routes(self, arc):
        return []

    def get_confidence_labels_by_snippet_ids(self, ids):
        return {CLIP: self.labels}

    def v2_get_session_by_id(self, session_id):
        return self.session

    def insert_voice_album_entry(self, **kwargs):
        self.writes.append(("insert", kwargs))
        return True

    def delete_voice_album_entry(self, **kwargs):
        self.writes.append(("delete", kwargs))
        return True


_USER_YES = {"snippet_id": CLIP, "response": "yes", "slide_index": 2}
_COACH_YES = {"lane": "coach", "value": "yes"}
_COACH_NO = {"lane": "coach", "value": "no"}
_THIS_PROJECT = {"project_id": ARC}


def _aligned(**overrides):
    fields = dict(self_reports=[_USER_YES], labels=[_COACH_YES],
                  session=_THIS_PROJECT)
    fields.update(overrides)
    return _Db(**fields)


def _run(database):
    with mock.patch("services.judgement_follow_up.clip_machine_read",
                    lambda db, _take, _snip: db.machine):
        return reconcile_voice_album_clip(
            ARC, CLIP, take_session_id=TAKE, database=database)


class OriginalClip(unittest.TestCase):

    def test_three_aligned_yeses_add_the_clip(self):
        database = _aligned()
        self.assertTrue(_run(database))
        self.assertEqual(database.writes, [("insert", {
            "arc_id": ARC, "snippet_id": CLIP, "take_session_id": TAKE,
            "slide_index": 2,
        })])

    def test_a_no_on_an_unpublished_take_withdraws_too(self):
        database = _aligned(labels=[_COACH_NO])
        self.assertTrue(_run(database))
        self.assertEqual(database.writes, [("delete", {
            "arc_id": ARC, "snippet_id": CLIP,
        })])

    def test_any_other_read_writes_nothing(self):
        cases = {
            "no user yes": _aligned(self_reports=[]),
            "machine reads weak": _aligned(machine="weak"),
            "machine cannot read": _aligned(machine=None),
            "no coach answer": _aligned(labels=[]),
            "a Take of another project": _aligned(
                labels=[_COACH_NO], session={"project_id": "other-arc"}),
            "database down": _aligned(labels=[_COACH_NO], broken=True),
        }
        for name, database in cases.items():
            with self.subTest(name):
                self.assertFalse(_run(database))
                self.assertEqual(database.writes, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
