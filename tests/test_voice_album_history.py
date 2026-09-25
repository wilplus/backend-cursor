"""THE HISTORY BEHIND ONE VOICE ALBUM MOMENT (founder 2026-09-18).

"I want the whole history so I can see from where it came from and the short
note at the end." These pins hold the shape of that account: which lanes may
speak, what they may never say, and that a missing lane goes quiet instead of
guessing.

Run: python3 -m unittest tests.test_voice_album_history
"""
from __future__ import annotations

import unittest

from services.voice_album_history import (
    COACH_DISPLAY,
    build_moment_history,
    order_events,
    split_moment_key,
)

ARC = "arc-1"
SNIP = "snip-1"


def _coach(value):
    return [{"rater_id": "coach1", "lane": "coach", "value": value,
             "state_id": "confidence", "self_report": False,
             "created_at": "2026-08-15T09:00:00Z"}]


class _Db:
    def __init__(self, *, reports=None, labels=None, practice=None,
                 attempts=None, notes=None, attempt_rows=None):
        self.reports = reports or []
        self.labels = labels or {}
        self.practice = practice
        self.attempts = attempts or []
        self.notes = notes or []
        self.attempt_rows = attempt_rows or {}
        self.inserted = []

    def list_take_feedback_self_reports_by_snippet(self, snippet_id):
        return [r for r in self.reports if r.get("snippet_id") == snippet_id]

    def get_confidence_labels_by_snippet_ids(self, ids):
        return {i: self.labels.get(i, []) for i in ids}

    def get_confident_voice_practice_by_take(self, sid, owner=None):
        return self.practice

    def get_confident_voice_practice(self, practice_id, owner=None):
        return self.practice

    def get_confident_voice_practice_attempt(self, attempt_id, practice_id=None):
        return self.attempt_rows.get(attempt_id)

    def list_confident_voice_practice_attempts(self, practice_id):
        return self.attempts

    def list_voice_album_notes(self, *, arc_id, moment_key, owner_user_id):
        return [n for n in self.notes
                if n.get("moment_key") == moment_key
                and n.get("owner_user_id") == owner_user_id]


def _build(db, *, moment=SNIP, entry=None, take_index=2, owner="user-1"):
    return build_moment_history(
        arc_id=ARC, moment_key=moment, owner_user_id=owner,
        entry=entry if entry is not None else {
            "snippet_id": SNIP, "take_session_id": "sess-1", "slide_index": 2,
            "entered_at": "2026-08-15T10:00:00Z",
        },
        take_index=take_index, database=db,
        resolve_audio=lambda ref: ("https://cdn/" + str(ref)) if ref else None,
    )


class MomentKeyTests(unittest.TestCase):
    def test_practice_prefix_splits_into_its_own_kind(self):
        self.assertEqual(split_moment_key("practice:abc"),
                         ("practice_attempt", "abc"))

    def test_a_bare_id_is_a_snippet(self):
        self.assertEqual(split_moment_key(" snip-9 "), ("snippet", "snip-9"))


class OriginTests(unittest.TestCase):
    def test_origin_carries_take_and_slide_not_a_judgement(self):
        out = _build(_Db())
        self.assertEqual(out["origin"]["take_index"], 2)
        self.assertEqual(out["origin"]["slide_index"], 2)
        self.assertEqual(out["origin"]["source"], "snippet")

    def test_missing_arc_or_moment_yields_an_empty_history_not_a_raise(self):
        out = build_moment_history(arc_id="", moment_key="", owner_user_id="u",
                                   database=_Db())
        self.assertEqual(out["events"], [])


class OwnerAnswerTests(unittest.TestCase):
    def test_the_owners_own_confident_voice_answer_is_read_back(self):
        db = _Db(reports=[{"snippet_id": SNIP, "feedback_family":
                           "confident_voice", "response": "yes",
                           "created_at": "2026-08-14T10:00:00Z"}])
        events = _build(db)["events"]
        self.assertEqual([e["kind"] for e in events], ["owner_answer"])
        self.assertEqual(events[0]["response"], "yes")
        self.assertEqual(events[0]["who"], "You")

    def test_only_the_latest_answer_on_that_clip_is_narrated(self):
        db = _Db(reports=[
            {"snippet_id": SNIP, "feedback_family": "confident_voice",
             "response": "in_between", "created_at": "2026-08-14T10:00:00Z"},
            {"snippet_id": SNIP, "feedback_family": "confident_voice",
             "response": "yes", "created_at": "2026-08-14T11:00:00Z"},
        ])
        self.assertEqual(_build(db)["events"][0]["response"], "yes")

    def test_another_family_never_answers_the_confidence_question(self):
        # rewrite_clarity uses a different schema and different words; reading
        # it here would put one rater's answer under another's question.
        db = _Db(reports=[{"snippet_id": SNIP, "feedback_family":
                           "rewrite_clarity", "response": "keep_wording",
                           "created_at": "2026-08-14T10:00:00Z"}])
        self.assertEqual(_build(db)["events"], [])


class CoachLaneTests(unittest.TestCase):
    def test_a_professional_yes_says_only_that_it_was_heard_the_same(self):
        db = _Db(labels={SNIP: _coach("yes")})
        events = _build(db)["events"]
        self.assertEqual([e["kind"] for e in events], ["coach_agreed"])
        self.assertEqual(events[0]["who"], COACH_DISPLAY)
        # BLIND COACH / AC-9: no value, no rater id, no verdict word.
        self.assertNotIn("value", events[0])
        self.assertNotIn("rater_id", events[0])

    def test_a_withdrawn_coach_yes_stops_being_narrated(self):
        db = _Db(labels={SNIP: _coach("no")})
        self.assertEqual(_build(db)["events"], [])

    def test_the_coach_is_never_named(self):
        db = _Db(labels={SNIP: [{"rater_id": "coach1", "lane": "coach",
                                 "value": "yes", "state_id": "confidence",
                                 "self_report": False,
                                 "display_name": "Marta K."}]})
        self.assertNotIn("Marta", str(_build(db)["events"]))


class ExerciseTests(unittest.TestCase):
    PRACTICE = {
        "id": "prac-1", "snippet_id": SNIP, "slide_index": 2,
        "created_at": "2026-08-16T10:00:00Z", "selected_attempt_id": "att-2",
        "exercise_id": "hear-every-word-v1", "exercise_version": 1,
        "exercise_snapshot": {
            "title": "Hear every word",
            "instruction": "Read the same text again, slightly more slowly.",
            "explanation_video_url": "https://video/hear-every-word-v1",
        },
    }
    ATTEMPTS = [
        {"id": "att-1", "attempt_index": 1, "audio_ref": "a1",
         "duration_ms": 5400},
        {"id": "att-2", "attempt_index": 2, "audio_ref": "a2",
         "duration_ms": 6000},
    ]

    def test_the_exercise_carries_its_video_and_every_attempt(self):
        db = _Db(practice=self.PRACTICE, attempts=self.ATTEMPTS)
        event = next(e for e in _build(db)["events"] if e["kind"] == "exercise")
        self.assertEqual(event["title"], "Hear every word")
        self.assertEqual(event["video_url"], "https://video/hear-every-word-v1")
        self.assertEqual([a["attempt_id"] for a in event["attempts"]],
                         ["att-1", "att-2"])
        self.assertEqual([a["kept"] for a in event["attempts"]], [False, True])
        self.assertEqual(event["attempts"][0]["audio_url"], "https://cdn/a1")

    def test_the_assigned_version_is_served_from_the_snapshot(self):
        # §35d: the student is shown the exact version they were given, even
        # once the live catalogue has moved on.
        db = _Db(practice=self.PRACTICE, attempts=self.ATTEMPTS)
        event = next(e for e in _build(db)["events"] if e["kind"] == "exercise")
        self.assertEqual(event["exercise_id"], "hear-every-word-v1")
        self.assertEqual(event["exercise_version"], 1)

    def test_a_practice_for_a_different_clip_is_not_this_clips_history(self):
        db = _Db(practice=dict(self.PRACTICE, snippet_id="other-snip"),
                 attempts=self.ATTEMPTS)
        self.assertEqual(_build(db)["events"], [])

    def test_an_admitted_attempt_inherits_its_original_clips_history(self):
        db = _Db(
            reports=[{"snippet_id": SNIP, "feedback_family": "confident_voice",
                      "response": "yes", "created_at": "2026-08-14T10:00:00Z"}],
            practice=self.PRACTICE, attempts=self.ATTEMPTS,
            attempt_rows={"att-2": {"id": "att-2", "practice_id": "prac-1"}},
        )
        out = _build(db, moment="practice:att-2", entry={
            "practice_attempt_id": "att-2", "take_session_id": "sess-1",
            "slide_index": 2, "entered_at": "2026-08-17T10:00:00Z",
        })
        self.assertEqual(out["origin"]["source"], "practice_attempt")
        self.assertIn("owner_answer", [e["kind"] for e in out["events"]])
        self.assertIn("exercise", [e["kind"] for e in out["events"]])


class NoteTests(unittest.TestCase):
    def test_the_owners_notes_close_the_history(self):
        db = _Db(
            labels={SNIP: _coach("yes")},
            notes=[{"id": "n1", "moment_key": SNIP, "owner_user_id": "user-1",
                    "body": "Play this before Thursday.",
                    "created_at": "2026-08-18T10:00:00Z"}],
        )
        events = _build(db)["events"]
        self.assertEqual(events[-1]["kind"], "note")
        self.assertEqual(events[-1]["body"], "Play this before Thursday.")

    def test_another_users_note_is_never_served(self):
        db = _Db(notes=[{"id": "n1", "moment_key": SNIP,
                         "owner_user_id": "someone-else", "body": "hidden",
                         "created_at": "2026-08-18T10:00:00Z"}])
        self.assertEqual(_build(db)["events"], [])

    def test_an_empty_note_body_is_not_an_event(self):
        db = _Db(notes=[{"id": "n1", "moment_key": SNIP,
                         "owner_user_id": "user-1", "body": "   ",
                         "created_at": "2026-08-18T10:00:00Z"}])
        self.assertEqual(_build(db)["events"], [])


class OrderingTests(unittest.TestCase):
    def test_events_read_in_the_order_they_happened(self):
        db = _Db(
            reports=[{"snippet_id": SNIP, "feedback_family": "confident_voice",
                      "response": "yes", "created_at": "2026-08-14T10:00:00Z"}],
            labels={SNIP: _coach("yes")},
            notes=[{"id": "n1", "moment_key": SNIP, "owner_user_id": "user-1",
                    "body": "later", "created_at": "2026-08-18T10:00:00Z"}],
        )
        self.assertEqual([e["kind"] for e in _build(db)["events"]],
                         ["owner_answer", "coach_agreed", "note"])

    def test_an_undated_event_sorts_last_rather_than_rewriting_the_story(self):
        out = order_events([
            {"kind": "note", "at": None},
            {"kind": "owner_answer", "at": "2026-08-14T10:00:00Z"},
        ])
        self.assertEqual([e["kind"] for e in out], ["owner_answer", "note"])


class NeverSurfacedTests(unittest.TestCase):
    def test_no_lane_carries_a_score_ratio_or_classifier_output(self):
        db = _Db(
            reports=[{"snippet_id": SNIP, "feedback_family": "confident_voice",
                      "response": "yes", "created_at": "2026-08-14T10:00:00Z"}],
            labels={SNIP: _coach("yes")},
            practice=ExerciseTests.PRACTICE, attempts=ExerciseTests.ATTEMPTS,
        )
        blob = str(_build(db))
        for banned in ("power_score", "machine_confidence", "probability",
                       "score", "confidence_value", "percentile"):
            self.assertNotIn(banned, blob)

    def test_the_machine_leg_is_not_drawn_as_an_event(self):
        # Album membership already required it; drawing it on the student's
        # timeline is the closest thing here to a surfaced model badge.
        db = _Db(labels={SNIP: _coach("yes")})
        self.assertNotIn("machine", str(_build(db)["events"]))


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# THE STORY BEHIND ANY MOMENT (founder 2026-09-25).
#
# "the album shows your confident moments, not any moments." The Album is a
# trophy case — three separate yeses to get in — so the history above it can
# only ever be told about a moment that went well. The ones worth learning
# from are the others.
# ---------------------------------------------------------------------------
from services.voice_album_history import (  # noqa: E402
    build_snippet_history,
    owned_snippet_history,
)

SESSION = {"id": "sess-1", "take_index": 2}


class _SnippetDb(_Db):
    """The Album double plus the one read an ownership check needs."""

    def __init__(self, *, snippets=None, snippets_raise=False, **kwargs):
        super().__init__(**kwargs)
        self.snippets = snippets if snippets is not None else [{"id": SNIP}]
        self.snippets_raise = snippets_raise

    def get_snippets_by_session(self, session_id):
        if self.snippets_raise:
            raise RuntimeError("read failed")
        return self.snippets


class TheCoachLaneIsAlbumOnlyTests(unittest.TestCase):
    """The fence, stated as a test because it is invisible in the output.

    `_coach_agreed_event` emits ONLY on a yes. Inside the Album that is
    harmless — every moment there already has a coach yes, so the row is
    always present and discloses nothing. Told about every moment it inverts:
    present on some, missing on others, and the silence announces the verdict
    on the rest. BLIND COACH, breached by omission.
    """

    def test_a_coach_yes_never_appears_in_any_moments_story(self):
        db = _SnippetDb(labels={SNIP: _coach("yes")})
        out = build_snippet_history(
            arc_id=ARC, snippet_id=SNIP, owner_user_id="user-1",
            take_session_id="sess-1", take_index=2, database=db,
        )
        kinds = [event.get("kind") for event in out["events"]]
        self.assertNotIn("coach_agreed", kinds)
        self.assertNotIn(COACH_DISPLAY, repr(out))

    def test_the_album_still_tells_it_a_regression_guard(self):
        """The Album path is unchanged — this exists so a future edit cannot
        take the lane away from the surface where it IS safe."""
        db = _Db(labels={SNIP: _coach("yes")})
        out = _build(db)
        self.assertIn("coach_agreed",
                      [event.get("kind") for event in out["events"]])


class EveryOtherLaneCarriesOverTests(unittest.TestCase):
    def test_the_speakers_own_answer_is_read_back_to_them(self):
        db = _SnippetDb(reports=[{
            "snippet_id": SNIP, "feedback_family": "confident_voice",
            "response": "no", "created_at": "2026-08-15T09:30:00Z",
        }])
        out = build_snippet_history(
            arc_id=ARC, snippet_id=SNIP, owner_user_id="user-1",
            take_session_id="sess-1", database=db,
        )
        self.assertIn("owner_answer",
                      [event.get("kind") for event in out["events"]])

    def test_the_exercise_and_its_attempts_are_the_point_of_the_story(self):
        db = _SnippetDb(
            practice={"id": "p1", "snippet_id": SNIP,
                      "exercise_snapshot": {
                          "title": "Land the last word",
                          "explanation_video_url": "https://x/v.mp4"}},
            attempts=[{"attempt_index": 1,
                       "created_at": "2026-08-16T09:00:00Z"}],
        )
        out = build_snippet_history(
            arc_id=ARC, snippet_id=SNIP, owner_user_id="user-1",
            take_session_id="sess-1", database=db,
            resolve_audio=lambda ref: None,
        )
        self.assertIn("exercise",
                      [event.get("kind") for event in out["events"]])

    def test_origin_says_where_not_how_well(self):
        out = build_snippet_history(
            arc_id=ARC, snippet_id=SNIP, owner_user_id="user-1",
            take_index=2, database=_SnippetDb(),
        )
        self.assertEqual(out["origin"]["take_index"], 2)
        self.assertEqual(out["origin"]["source"], "snippet")

    def test_nothing_at_all_is_an_empty_story_not_a_raise(self):
        out = build_snippet_history(
            arc_id="", snippet_id="", owner_user_id="u",
            database=_SnippetDb())
        self.assertEqual(out["events"], [])


class ItMustBeTheirOwnMomentTests(unittest.TestCase):
    """The lanes are keyed by snippet and never ask whose it is, so without
    this link a caller could name any snippet id and have its owner's own
    answers and notes read back to them."""

    def test_a_snippet_from_this_session_is_served(self):
        db = _SnippetDb(snippets=[{"id": SNIP}, {"id": "other"}])
        out = owned_snippet_history(
            db, arc_id=ARC, snippet_id=SNIP, session=SESSION,
            owner_user_id="user-1")
        self.assertIsNotNone(out)
        self.assertEqual(out["moment_key"], SNIP)

    def test_a_snippet_that_is_not_in_the_session_is_refused(self):
        db = _SnippetDb(snippets=[{"id": "someone-elses"}])
        self.assertIsNone(owned_snippet_history(
            db, arc_id=ARC, snippet_id=SNIP, session=SESSION,
            owner_user_id="user-1"))

    def test_a_read_that_fails_proves_nothing_so_it_refuses(self):
        db = _SnippetDb(snippets_raise=True)
        self.assertIsNone(owned_snippet_history(
            db, arc_id=ARC, snippet_id=SNIP, session=SESSION,
            owner_user_id="user-1"))

    def test_a_missing_session_is_refused(self):
        db = _SnippetDb()
        for bad in (None, {}, {"id": ""}, "sess-1"):
            self.assertIsNone(owned_snippet_history(
                db, arc_id=ARC, snippet_id=SNIP, session=bad,
                owner_user_id="user-1"))

    def test_the_route_asks_for_all_three_before_it_reads_anything(self):
        import inspect

        from routes.v2 import arcs

        source = inspect.getsource(arcs.v2_moment_history)
        self.assertIn("owned_snippet_history", source)
        # The project is proved first, then the session, then the snippet.
        self.assertLess(source.index("_arc_owned_by_caller"),
                        source.index("owned_snippet_history"))
