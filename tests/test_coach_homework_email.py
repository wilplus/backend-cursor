"""The coach's homework-complete email.

FOUNDER 2026-09-28: restyle it to the student email's look, update the logo,
drop the dead rows, and say who / which lesson / how many moments await.

THREE OF THESE TESTS ARE ABOUT THINGS THAT ARE *NOT* THERE, which is the
point. The email used to carry:

  * "Pace: n/a WPM (target 120-160)" and "Filler words: n/a" — the caller
    passed both as literal None, so neither row could ever show a value for
    any student. They were not missing data; they were rows with no source.
  * "Strength: Loudness (pending)" — a constant default that never became
    anything.
  * a performance score — center_hold_ratio * 100 minus 3 per filler, which
    is the pre-V3 "good public speaker" measure the product stopped
    reasoning about. Founder deferred it.

Deleted rows come back quietly, one helpful-looking commit at a time. These
assertions are what make that noisy.
"""
from __future__ import annotations

import sys
import types
import unittest

for _m in ("supabase", "sentry_sdk"):
    if _m not in sys.modules:
        sys.modules[_m] = types.ModuleType(_m)
if not hasattr(sys.modules["supabase"], "create_client"):
    sys.modules["supabase"].create_client = lambda *a, **k: None
    sys.modules["supabase"].Client = object
if not hasattr(sys.modules["sentry_sdk"], "capture_exception"):
    sys.modules["sentry_sdk"].capture_exception = lambda *a, **k: None

from services.assignment_email import (  # noqa: E402
    build_admin_homework_completed_email_html as build,
)


def _html(**over):
    kw = dict(
        student_email="student@example.com",
        profile_url="https://willpowerlab.com/admin/students/u1",
        moments_awaiting=7,
        lesson_label="Take 2 — 2026-09-28",
        student_name="Artur",
    )
    kw.update(over)
    return build(**kw)


class TheDeadRowsAreGoneTests(unittest.TestCase):
    def test_no_pace_row(self):
        h = _html()
        self.assertNotIn("Pace", h)
        self.assertNotIn("WPM", h)
        self.assertNotIn("120", h, "the target band was a verdict, not data")

    def test_no_filler_row(self):
        self.assertNotIn("Filler", _html())

    def test_no_strength_row(self):
        h = _html()
        self.assertNotIn("Strength", h)
        self.assertNotIn("Loudness", h)

    def test_no_performance_score(self):
        """The template takes no score and renders none.

        Passing one must be a TypeError rather than a silently ignored
        argument, so a caller that tries to put the number back fails at the
        call instead of sending an email that quietly drops it.
        """
        self.assertNotIn("Score", _html())
        with self.assertRaises(TypeError):
            _html(score=0.73)


class TheCoachSeesWhatTheyActOnTests(unittest.TestCase):
    def test_who_which_lesson_how_many_and_the_button(self):
        h = _html()
        self.assertIn("Artur", h)
        self.assertIn("student@example.com", h)
        self.assertIn("Take 2", h)
        self.assertIn("Moments to review", h)
        self.assertIn(">7<", h)
        self.assertIn("https://willpowerlab.com/admin/students/u1", h)

    def test_a_missing_lesson_draws_no_row_rather_than_unknown(self):
        h = _html(lesson_label="")
        self.assertNotIn("Lesson", h)
        self.assertNotIn("unknown", h.lower())

    def test_zero_moments_draws_no_row(self):
        """Nothing waiting is not 'Moments to review: 0'."""
        self.assertNotIn("Moments to review", _html(moments_awaiting=0))
        self.assertNotIn("Moments to review", _html(moments_awaiting=None))

    def test_an_empty_preview_draws_no_card(self):
        """Contract 24f's rule for an honest empty lane: show no card, not a
        card announcing there is nothing."""
        h = _html(transcript_excerpt="")
        self.assertNotIn("Report preview", h)
        self.assertNotIn("No transcript preview available yet", h)

    def test_a_real_preview_does_draw_one(self):
        h = _html(transcript_excerpt="She opened on the cost line.")
        self.assertIn("Report preview", h)
        self.assertIn("She opened on the cost line.", h)


class TheLookMatchesTheStudentEmailTests(unittest.TestCase):
    """Every value here is copied from the frontend's React Email template,
    emails/PostSessionResultsEmail.tsx. That template renders the email the
    speaker gets; this one is hand-written Python. The two CAN drift, so
    these assertions are the only thing that notices when they do."""

    def test_the_wordmark_is_the_real_logo(self):
        """It used to fall back to {frontend}/icon, which is the favicon, and
        then was an <img> of /willab-logo, which a client holding back remote
        images drew as a broken box (founder 2026-09-30). Now it is text."""
        h = _html()
        self.assertIn(">WillpowerLab</span>", h)
        self.assertNotIn("<img", h)

    def test_the_student_email_palette(self):
        h = _html()
        for token in ("#FAF7F2", "#FCFAF6", "#EFE9DE", "#F97316",
                      "#1F1A14", "#6B6256"):
            self.assertIn(token, h, f"{token} is the student email's")

    def test_the_student_email_type_scale(self):
        h = _html()
        for token in ("font-size:28px", "line-height:34px", "padding:40px",
                      "border-radius:16px", "border-radius:9999px",
                      "letter-spacing:0.08em"):
            self.assertIn(token, h, f"{token} is the template's")

    def test_the_eyebrow_carries_the_lesson_not_a_new_phrase(self):
        """The design wants a top line. Filling it with the lesson means the
        layout gains its eyebrow without inventing copy to sign off."""
        head = _html(lesson_label="Take 2 — 28 Sep").split("<h1")[0]
        self.assertIn("Take 2", head)

    def test_the_eyebrow_never_renders_empty(self):
        head = _html(lesson_label="").split("<h1")[0]
        self.assertIn("Homework", head)

    def test_the_name_and_address_are_escaped(self):
        h = _html(student_name='<script>x</script>',
                  student_email='a"b@example.com')
        self.assertNotIn("<script>", h)


if __name__ == "__main__":
    unittest.main()
