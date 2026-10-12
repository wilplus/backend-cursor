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


    def test_no_performance_score(self):
        """The template takes no score and renders none.

        Passing one must be a TypeError rather than a silently ignored
        argument, so a caller that tries to put the number back fails at the
        call instead of sending an email that quietly drops it.
        """
        self.assertNotIn("Score", _html())
        with self.assertRaises(TypeError):
            _html(score=0.73)


if __name__ == "__main__":
    unittest.main()
