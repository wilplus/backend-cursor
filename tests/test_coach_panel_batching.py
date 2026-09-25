"""The coach panel reads in batches, not once per row.

FOUNDER 2026-09-25: "shorten the loading times on the coach panel when you
click on the lesson from the user and to open the actual bookmarked fragments
and then on each step of the journey."

Three surfaces were doing a database round trip PER ROW for one small field:

  * the students list   — a whole profile per student, to render `domain`
  * the review queue    — snippets AND coach drafts per queued take, for a
                          language match, a count, and a lifecycle pill
  * the student detail  — an ideal-text row per project, to decide a badge

Forty queued takes meant eighty round trips before a coach saw a list.

THESE TESTS ARE THE GUARD, not the optimisation. They fail if a singular
accessor comes back into any of those loops — which is how an N+1 returns:
not by anyone deciding to, but by a later edit reaching for the obvious
per-row call. Asserting "the per-row reader is never called" says that
plainly, and keeps saying it.
"""
from __future__ import annotations

import sys
import types
import unittest

for _module in ("supabase", "sentry_sdk"):
    if _module not in sys.modules:
        sys.modules[_module] = types.ModuleType(_module)
if not hasattr(sys.modules["supabase"], "create_client"):
    sys.modules["supabase"].create_client = lambda *a, **k: None
    sys.modules["supabase"].Client = object
if not hasattr(sys.modules["sentry_sdk"], "capture_exception"):
    sys.modules["sentry_sdk"].capture_exception = lambda *a, **k: None

from flask import Flask, request  # noqa: E402

from routes.v2 import coach as v2_coach  # noqa: E402
from services.db import db  # noqa: E402


def _boom(*_a, **_k):
    raise AssertionError(
        "a per-row read came back into a batched loop — that is the N+1 "
        "returning; use the plural accessor"
    )


class _Swap:
    """Swap attributes on db for the duration of a test, restoring after."""

    def __init__(self, **targets):
        self.targets = targets
        self.saved = {}

    def __enter__(self):
        for name, value in self.targets.items():
            self.saved[name] = getattr(db, name, None)
            setattr(db, name, value)
        return self

    def __exit__(self, *_exc):
        for name, value in self.saved.items():
            if value is not None:
                setattr(db, name, value)
        return False


class TheStudentsListReadsProfilesOnceTests(unittest.TestCase):
    def test_one_batch_read_for_a_whole_page_of_students(self):
        calls = {"batch": 0}

        def batch(uids):
            calls["batch"] += 1
            return {str(u): {"domain": "sales"} for u in uids}

        rows = [
            {"user_id": f"u{i}", "last_active": "2026-06-08T10:00:00Z",
             "session_count": 1}
            for i in range(25)
        ]
        original = db.takes.list_coach_students
        db.takes.list_coach_students = lambda **k: rows
        try:
            with _Swap(get_user_profiles=batch, get_user_profile=_boom):
                app = Flask(__name__)
                with app.test_request_context():
                    request.user_id = "coach-1"
                    resp, status = v2_coach.v2_coach_students.__wrapped__()
        finally:
            db.takes.list_coach_students = original

        self.assertEqual(status, 200)
        self.assertEqual(len(resp.get_json()), 25)
        self.assertEqual(calls["batch"], 1, "one read for the whole page")

    def test_the_displayed_field_still_arrives(self):
        """Speed is not the only requirement: the row must still say what it
        said before."""
        rows = [{"user_id": "u1", "last_active": "x", "session_count": 3}]
        original = db.takes.list_coach_students
        db.takes.list_coach_students = lambda **k: rows
        try:
            with _Swap(
                get_user_profiles=lambda uids: {"u1": {"domain": "law"}},
                get_user_profile=_boom,
            ):
                app = Flask(__name__)
                with app.test_request_context():
                    request.user_id = "coach-1"
                    resp, _status = v2_coach.v2_coach_students.__wrapped__()
        finally:
            db.takes.list_coach_students = original
        row = resp.get_json()[0]
        self.assertEqual(row["domain"], "law")
        self.assertTrue(row["pseudonym"])
        # The red line this route has always held.
        self.assertNotIn("email", row)
        self.assertNotIn("name", row)

    def test_a_student_with_no_profile_reads_blank_not_broken(self):
        rows = [{"user_id": "u1", "last_active": "x", "session_count": 1}]
        original = db.takes.list_coach_students
        db.takes.list_coach_students = lambda **k: rows
        try:
            with _Swap(get_user_profiles=lambda uids: {},
                       get_user_profile=_boom):
                app = Flask(__name__)
                with app.test_request_context():
                    request.user_id = "coach-1"
                    resp, status = v2_coach.v2_coach_students.__wrapped__()
        finally:
            db.takes.list_coach_students = original
        self.assertEqual(status, 200)
        self.assertEqual(resp.get_json()[0]["domain"], "")


class TheQueueReadsEveryTakeAtOnceTests(unittest.TestCase):
    def test_two_reads_for_the_whole_queue_not_two_per_take(self):
        calls = {"snips": 0, "drafts": 0}
        rows = [
            {"id": f"s{i}", "user_id": f"u{i}", "intake_context": {},
             "created_at": "2026-06-08T10:00:00Z"}
            for i in range(40)
        ]

        def snips(ids, **_k):
            calls["snips"] += 1
            return {str(i): [] for i in ids}

        def drafts(ids):
            calls["drafts"] += 1
            return {}

        with _Swap(
            list_review_queue=lambda: rows,
            get_user_proficient_languages=lambda uid: ["en"],
            get_snippets_by_sessions=snips,
            get_coach_snippet_drafts_by_sessions=drafts,
            get_snippets_by_session=_boom,
            get_coach_snippet_drafts=_boom,
        ):
            app = Flask(__name__)
            with app.test_request_context():
                request.user_id = "coach-1"
                v2_coach.v2_coach_queue.__wrapped__()

        self.assertEqual(calls["snips"], 1, "one snippet read for 40 takes")
        self.assertEqual(calls["drafts"], 1, "one draft read for 40 takes")


class TheStudentDetailReadsEveryProjectAtOnceTests(unittest.TestCase):
    def test_the_badge_read_is_one_query_for_every_project(self):
        import inspect

        source = inspect.getsource(v2_coach.v2_coach_student_detail)
        self.assertIn("get_coach_arc_ideal_texts(", source)
        self.assertNotIn("get_coach_arc_ideal_text(", source)


class TheStateMapCanBeHandedItsRowsTests(unittest.TestCase):
    def test_supplied_rows_mean_no_read_at_all(self):
        with _Swap(get_coach_snippet_drafts=_boom):
            out = v2_coach._coach_state_map(
                "s1",
                draft_rows=[{"snippet_id": "n1", "note": "hello",
                             "surfaced": True}],
            )
        self.assertEqual(out["n1"]["note"], "hello")
        self.assertTrue(out["n1"]["surfaced"])

    def test_no_rows_supplied_still_reads_for_itself(self):
        """Every single-session caller must keep working untouched."""
        seen = {"n": 0}

        def read(_sid):
            seen["n"] += 1
            return [{"snippet_id": "n1", "note": "read"}]

        with _Swap(get_coach_snippet_drafts=read):
            out = v2_coach._coach_state_map("s1")
        self.assertEqual(seen["n"], 1)
        self.assertEqual(out["n1"]["note"], "read")


class TheJourneyReadsTheWholeArcAtOnceTests(unittest.TestCase):
    """The library floor on GET /coach/arc/<id>/review-state.

    This scanned take by take and broke on the first hit, so the cost fell
    entirely on the case that matters: an arc with NO notes yet — every new
    student's journey — paid one round trip per take.
    """

    def test_one_read_for_an_arc_with_no_notes_at_all(self):
        calls = {"n": 0}

        def batch(ids):
            calls["n"] += 1
            return {}

        spoken = [{"id": f"s{i}"} for i in range(18)]
        with _Swap(get_coach_snippet_drafts_by_sessions=batch,
                   get_coach_snippet_drafts=_boom):
            out = v2_coach._arc_has_a_surfaced_note(spoken)
        self.assertFalse(out)
        self.assertEqual(calls["n"], 1, "one read for 18 takes")

    def test_a_surfaced_note_anywhere_in_the_arc_counts(self):
        rows = {
            "s0": [{"surfaced": False, "note": "not surfaced"}],
            "s1": [{"surfaced": True, "note": "  "}],
            "s2": [{"surfaced": True, "note": "here it is"}],
        }
        with _Swap(get_coach_snippet_drafts_by_sessions=lambda ids: rows,
                   get_coach_snippet_drafts=_boom):
            self.assertTrue(
                v2_coach._arc_has_a_surfaced_note([{"id": "s0"}]))

    def test_a_read_miss_fails_OPEN_and_never_blocks_the_coach(self):
        """The floor is advisory here and re-checked at publish. A miss must
        not grey out the publish button with a reason the coach cannot act
        on — a false ENABLE costs one clear error, a false DISABLE costs a
        coach who cannot ship work they already did."""

        def explode(_ids):
            raise RuntimeError("supabase said no")

        with _Swap(get_coach_snippet_drafts_by_sessions=explode,
                   get_coach_snippet_drafts=_boom):
            self.assertTrue(
                v2_coach._arc_has_a_surfaced_note([{"id": "s0"}]))


if __name__ == "__main__":
    unittest.main()
