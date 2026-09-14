"""The master-doc probe's report-only lane.

A rubric key of the form ``report_only_<check>`` is measured and printed
but never decides the exit code. MDR-14's answer-length cap moved there on
2026-09-14 after it flapped the gate on four unrelated PRs (181–191 chars
against a 180 cap, every other run). These tests pin the lane without a
live LLM: the deterministic checker and the note builder are pure.
"""
from __future__ import annotations

import unittest

from tests.evals.master_doc_probe import (
    CASES,
    Case,
    _deterministic_check,
    _report_only_notes,
)

_LONG = "a" * 200
_SHORT = "a" * 100


class ReportOnlyLengthTests(unittest.TestCase):
    def _case(self, rubric: dict) -> Case:
        return Case(id="X", category="x", user_message="x", rubric=rubric)

    def test_a_hard_cap_still_fails_the_deterministic_check(self):
        case = self._case({"max_answer_chars": 180})
        reason = _deterministic_check(case, {"answer": _LONG})
        self.assertEqual(reason, "answer too long (200 chars > 180)")

    def test_a_report_only_cap_does_not_fail_the_deterministic_check(self):
        case = self._case({"report_only_max_answer_chars": 180})
        self.assertIsNone(_deterministic_check(case, {"answer": _LONG}))

    def test_a_report_only_cap_produces_a_note_when_exceeded(self):
        case = self._case({"report_only_max_answer_chars": 180})
        self.assertEqual(
            _report_only_notes(case, {"answer": _LONG}),
            ["answer length 200 chars > 180 (report-only)"],
        )

    def test_no_note_under_the_cap_or_without_one(self):
        capped = self._case({"report_only_max_answer_chars": 180})
        self.assertEqual(_report_only_notes(capped, {"answer": _SHORT}), [])
        uncapped = self._case({})
        self.assertEqual(_report_only_notes(uncapped, {"answer": _LONG}), [])

    def test_mdr_14_length_is_report_only_and_its_other_checks_still_gate(self):
        (mdr14,) = [c for c in CASES if c.id == "MDR-14"]
        self.assertNotIn("max_answer_chars", mdr14.rubric)
        self.assertEqual(mdr14.rubric["report_only_max_answer_chars"], 180)
        # 191 chars: the longest real flap. Length alone no longer fails it.
        ok = {"answer": "Voice Album " + "x" * 179, "suggested_action": None}
        self.assertIsNone(_deterministic_check(mdr14, ok))
        # The bridge still has to be named and the action still has to be None.
        self.assertIsNotNone(
            _deterministic_check(mdr14, {"answer": "x" * 191, "suggested_action": None})
        )
        self.assertIsNotNone(
            _deterministic_check(mdr14, {"answer": "Voice Album", "suggested_action": "trainings"})
        )


if __name__ == "__main__":
    unittest.main()
