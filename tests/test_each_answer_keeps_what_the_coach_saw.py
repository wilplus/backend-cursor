"""
STORY    As the founder, I want every coach answer, and every word a coach
         leaves on a Take, to keep what the coach was looking at when they
         gave it, so that the answer can still be read against what they
         saw after a clip is re-cut, replaced or purged.
OUTCOME
  O1  A moment's first answer keeps one record: when it was given, the
      clip's words uncut, the slide (the coach's correction first), what
      the coach acted on, the pattern they named, their current diagnosis
      with its label, and the answered Take's own Ideal Text.
  O2  The same answer again (only the share added) keeps nothing new; a
      changed answer and a new video on an answer each keep their own, and
      the first record stays as it was.
  O3  Each save of a Take word keeps the whole Take's words in order, its
      re-read's after them, uncut, the coach's diagnoses on its moments and
      the Take's Ideal Text.
  O4  A moment from a mid-take re-read keeps the spoken Take's Ideal Text.
  O5  A coach answering their own Take keeps nothing.
PROVES   O1, O2 -> test_each_new_answer_to_a_moment_keeps_its_own_situation_once
         O3 -> test_each_take_word_save_keeps_the_whole_take
         O4 -> test_a_moment_from_a_re_read_keeps_the_spoken_takes_ideal_text
         O5 -> test_a_coach_answering_their_own_take_keeps_nothing
WHY      Founder 2026-10-19, decisions log N79 (migration 0483); L3 for a coach
         answering their own Take. The checks run
         on the public services the routes call (resolve_request,
         store_answer_video, save_take_word) with a fake database: that the
         Ideal Text read returns the snapshot of that Take, not the
         speaker's latest, is the database read's filter and is not pinned
         here. The record is kept off the coach's request, so each check
         waits for that thread first.
"""
from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from services import coach_answer_situation as cas
from services import coach_answer_video as cav
from services import coach_take_word as ctw
from services import exercise_coach_requests as ecr

REQUEST_ID = "7a2b3c4d-5e6f-4a70-8b9c-0d1e2f3a4b5c"
ARC = "arc-1"
TAKE, LATER_TAKE, RE_READ = "take-2", "take-3", "read-2"
CLIPS = {
    TAKE: [{"id": "snip-1", "transcript": "Good   morning.", "slide_index": 0},
           {"id": "snip-2", "transcript": "and that   is why the number " + "matters " * 200,
            "slide_index": 1}],
    RE_READ: [{"id": "snip-r1", "transcript": "And that is why  the number matters.",
               "slide_index": 1}],
}


def _settled():
    """Wait for the situations kept off the coach's request."""
    for thread in threading.enumerate():
        if thread.name == cas.THREAD_NAME:
            thread.join(timeout=5)


class _Takes:
    def get_read_sessions_for(self, sid):
        return [{"id": RE_READ}] if sid == TAKE else []


class _Db:
    """The request, the coach's word, the clips, the diagnoses, the Ideal
    Text snapshots and the situations, in memory."""

    def __init__(self, *, owner="speaker-1"):
        self.request = {"id": REQUEST_ID, "take_session_id": TAKE, "snippet_id": "snip-2",
                        "owner_user_id": owner, "kind": "praise", "answer_kind": "ambiguity",
                        "reason": "nothing_spotted", "observed_tags": [], "resolution": None,
                        "resolved_at": None, "shared_at": None}
        self.owner = owner
        self.word: dict = {}
        self.ticks = 0
        self.takes = _Takes()
        self.diagnoses = {"snip-1": {"id": "diag-1", "snippet_id": "snip-1", "kind": "no_error",
                                     "error_id": None, "named_error_id": None, "label": None},
                          "snip-2": {"id": "diag-2", "snippet_id": "snip-2", "kind": "error",
                                     "error_id": "rushing", "named_error_id": None,
                                     "label": "Rushing"},
                          "snip-r1": {"id": "diag-r1", "snippet_id": "snip-r1",
                                      "kind": "error", "error_id": "rushing",
                                      "named_error_id": None, "label": "Rushing"}}
        # The coach moved snip-2 to slide 4; snip-1's correction was withdrawn.
        self.slide_fixes = {TAKE: {"snip-2": 4, "snip-1": None}}
        # The speaker's head is already the later Take's.
        self.snapshots = {TAKE: {"id": "snap-2", "version": 2},
                          LATER_TAKE: {"id": "snap-3", "version": 3}}
        self.situations: list = []

    def _now(self) -> str:
        self.ticks += 1
        return f"2026-10-19T10:00:{self.ticks:02d}.123456+00:00"

    # what a situation is made of
    def get_snippet_passages(self, take, snippet_id=None):
        return [dict(c) for c in CLIPS.get(take, []) if snippet_id in (None, c["id"])]

    def get_snippet_slide_corrections(self, take):
        return dict(self.slide_fixes.get(take, {}))

    def list_current_coach_moment_diagnoses(self, *, take_session_id, coach_id, snippet_id=None):
        clips = {c["id"] for c in CLIPS.get(take_session_id, [])}
        return [dict(d) for s, d in reversed(list(self.diagnoses.items()))
                if s in clips and coach_id == "coach-1" and snippet_id in (None, s)]

    def get_take_ideal_text_snapshot(self, take, *, arc_id):
        return self.snapshots.get(take) if arc_id == ARC else None

    def v2_get_session_by_id(self, sid):
        if sid == RE_READ:
            return {"id": sid, "user_id": self.owner, "arc_id": ARC,
                    "recording_kind": "read", "paired_session_id": TAKE}
        return {"id": sid, "user_id": self.owner, "arc_id": ARC}

    def insert_coach_answer_situation(self, **row):
        key = ("take_word_id", "answered_at") if row["take_word_id"] else ("request_id",
                                                                           "answered_at")
        if any(tuple(s[k] for k in key) == tuple(row[k] for k in key)
               for s in self.situations):
            return None
        self.situations.append(dict(row))
        return dict(row)

    # the saves, as the database writes them (0446: the same answer again
    # keeps its time; any change, a new video included, takes a new one)
    def resolve_exercise_coach_request(self, **kwargs):
        answer = {"resolution": kwargs["resolution"], "answer_text": kwargs.get("answer_text"),
                  "answer_video_ref": kwargs.get("video_ref")
                  or self.request.get("answer_video_ref")}
        if any(self.request.get(k) != v for k, v in answer.items()):
            self.request.update(answer, resolved_by=kwargs["coach_id"],
                                resolved_at=self._now(), shared_at=None)
        if kwargs.get("share") and not self.request.get("shared_at"):
            self.request["shared_at"] = self._now()
        return dict(self.request)

    def upsert_coach_take_word(self, *, take_session_id, coach_id, text, video_ref, share,
                               keep_video=False):
        self.word.update(id="word-1", take_session_id=take_session_id, coach_id=coach_id,
                         text=text, updated_at=self._now())
        if not keep_video:  # a save that names no video keeps the saved one
            self.word["video_ref"] = video_ref
        return dict(self.word)

    def list_speaking_errors(self, active_only=True):
        return [{"error_id": "rushing", "label": "Rushing"}]

    def list_diagnostic_exercises(self):
        return []


class _Upload:
    filename = "answer.mp4"

    def read(self):
        return b"video-bytes"


def _answer(db, coach="coach-1", **body):
    status, _payload = ecr.resolve_request(db, dict(db.request), {
        "resolution": "line_written", "answer_text": "The pause landed.",
        "file_in_catalogue": False, **body}, coach)
    assert status == 200
    _settled()


def _save_word(db, text):
    ctw.save_take_word(db, take_session_id=TAKE, coach_id="coach-1", body={"text": text})
    _settled()


class EachAnswerKeepsWhatTheCoachSawTests(unittest.TestCase):

    def test_each_new_answer_to_a_moment_keeps_its_own_situation_once(self):
        db = _Db()
        _answer(db, pattern_key="pause_before_number")
        [first] = db.situations
        self.assertEqual(first, {
            "take_session_id": TAKE, "snippet_id": "snip-2", "request_id": REQUEST_ID,
            "take_word_id": None, "answered_at": db.request["resolved_at"],
            "kind": "ambiguity", "pattern_key": "pause_before_number",
            "passage_text": " ".join(CLIPS[TAKE][1]["transcript"].split()),
            "slide_index": 4,  # the coach's correction, not the cutter's 1
            "diagnosis_ids": ["diag-2"],
            "diagnoses": [{"diagnosis_id": "diag-2", "snippet_id": "snip-2", "kind": "error",
                           "error_id": "rushing", "named_error_id": None, "label": "Rushing"}],
            "ideal_text_snapshot_id": "snap-2", "ideal_text_version": 2,
            "captured": "at_answer"})
        self.assertGreater(len(first["passage_text"]), 1200)  # uncut

        # The same answer again, now shared: no new answer, nothing new kept.
        with patch.object(ecr, "_tell_the_speaker"):
            _answer(db, share_with_user=True)
        self.assertEqual(len(db.situations), 1)

        # The coach changes their diagnosis, then their answer: its own row.
        db.diagnoses["snip-2"] = {"id": "diag-3", "snippet_id": "snip-2", "kind": "named_error",
                                  "error_id": None, "named_error_id": "named-1",
                                  "label": "Swallowed ending"}
        _answer(db, answer_text="Hold the pause one beat longer.")
        # A new video on that answer is a change too, and names no pattern.
        with patch("services.coach_video_storage.put_coach_object_bytes"), \
                patch("services.coach_video_storage.refreshed_media_url",
                      return_value="https://media/answer.mp4"), \
                patch.object(cav, "transcribe_answer_video_in_background"):
            status, _payload = cav.store_answer_video(
                db, request_row=dict(db.request), video_file=_Upload(), max_mb=100,
                coach_id="coach-1")
        self.assertEqual(status, 200)
        _settled()

        self.assertEqual(len(db.situations), 3)
        self.assertEqual(db.situations[0], first)
        changed, video = db.situations[1], db.situations[2]
        self.assertEqual(video["answered_at"], db.request["resolved_at"])
        self.assertEqual(len({s["answered_at"] for s in db.situations}), 3)
        for later in (changed, video):
            self.assertEqual(later["diagnosis_ids"], ["diag-3"])
            self.assertEqual(later["diagnoses"][0]["label"], "Swallowed ending")
        self.assertEqual((changed["pattern_key"], video["pattern_key"]), (None, None))

    def test_each_take_word_save_keeps_the_whole_take(self):
        db = _Db()
        for text in ("Slow down at the number.", "Pause before the number."):
            _save_word(db, text)
        self.assertEqual(len(db.situations), 2)
        first, second = db.situations
        self.assertEqual(second["answered_at"], db.word["updated_at"])
        self.assertNotEqual(first["answered_at"], second["answered_at"])
        self.assertEqual(
            {k: first[k] for k in ("take_session_id", "snippet_id", "request_id",
                                   "take_word_id", "kind", "slide_index", "diagnosis_ids",
                                   "ideal_text_snapshot_id", "ideal_text_version",
                                   "captured")},
            {"take_session_id": TAKE, "snippet_id": None, "request_id": None,
             "take_word_id": "word-1", "kind": None, "slide_index": None,
             # in the order the coach's packet folds the Take and its re-read
             "diagnosis_ids": ["diag-1", "diag-2", "diag-r1"],
             "ideal_text_snapshot_id": "snap-2", "ideal_text_version": 2,
             "captured": "at_answer"})
        self.assertEqual(first["passage_text"], " ".join(
            " ".join(c["transcript"].split()) for c in CLIPS[TAKE] + CLIPS[RE_READ]))

    def test_a_moment_from_a_re_read_keeps_the_spoken_takes_ideal_text(self):
        db = _Db()
        db.request.update(take_session_id=RE_READ, snippet_id="snip-r1")
        _answer(db)
        [kept] = db.situations
        self.assertEqual(
            {k: kept[k] for k in ("take_session_id", "snippet_id", "passage_text",
                                  "diagnosis_ids", "ideal_text_snapshot_id")},
            {"take_session_id": RE_READ, "snippet_id": "snip-r1",
             "passage_text": "And that is why the number matters.",
             "diagnosis_ids": ["diag-r1"], "ideal_text_snapshot_id": "snap-2"})

    def test_a_coach_answering_their_own_take_keeps_nothing(self):
        db = _Db(owner="coach-1")
        _answer(db)
        _save_word(db, "Note to self.")
        self.assertEqual(db.situations, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
