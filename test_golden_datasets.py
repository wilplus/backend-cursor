"""Golden-dataset structural gate (unit tier — no credentials, no LLM).

Every tests/evals/golden/*.jsonl must parse and validate BEFORE it can
gate anything: a malformed golden case failing at eval time would read
as a prompt regression when it's actually a dataset typo. This is the
free half of the check; the live half is tests/evals/run_prompt_evals.py.

Also pins the adapter contract: every dataset has an adapter, every
case's surface matches its filename.
"""
import unittest

from tests.evals import harness
from tests.evals.surfaces import ADAPTERS


class TestGoldenDatasets(unittest.TestCase):
    def test_datasets_parse_and_validate(self):
        for surface in harness.available_surfaces():
            with self.subTest(surface=surface):
                cases = harness.load_golden(surface)  # raises on invalid
                self.assertTrue(cases, f"{surface}.jsonl has no cases")

    def test_case_surface_matches_filename(self):
        for surface in harness.available_surfaces():
            for case in harness.load_golden(surface):
                self.assertEqual(
                    case.surface, surface,
                    f"{case.id}: surface field {case.surface!r} does not "
                    f"match its file {surface}.jsonl",
                )

    def test_every_dataset_has_an_adapter(self):
        for surface in harness.available_surfaces():
            self.assertIn(
                surface, ADAPTERS,
                f"golden/{surface}.jsonl exists but tests/evals/surfaces.py "
                "has no adapter for it — the eval would silently skip",
            )

    def test_known_failing_cases_document_themselves(self):
        """A quarantined case must say what the bug is. Without this the
        marker is indistinguishable from someone silencing a case they
        did not want to fix."""
        for surface in harness.available_surfaces():
            for case in harness.load_golden(surface):
                if case.known_failing:
                    with self.subTest(case=case.id):
                        self.assertTrue(
                            case.notes.strip(),
                            f"{case.id} is known_failing but has no notes",
                        )


class KnownFailingQuarantineTests(unittest.TestCase):
    """The quarantine must stay self-expiring: a documented bug does not
    gate, but its FIX must force the marker's removal. Without the
    second half, a known_failing marker silently outlives the bug and
    the case is never gated again."""

    def _verdict(self, *, known_failing, passed):
        return harness.Verdict(
            case_id="X-1", surface="s", passed=passed,
            known_failing=known_failing)

    def test_normal_failure_blocks(self):
        self.assertTrue(harness.is_blocking_failure(
            self._verdict(known_failing=False, passed=False)))

    def test_normal_pass_does_not_block(self):
        self.assertFalse(harness.is_blocking_failure(
            self._verdict(known_failing=False, passed=True)))

    def test_quarantined_failure_does_not_block(self):
        self.assertFalse(harness.is_blocking_failure(
            self._verdict(known_failing=True, passed=False)))

    def test_quarantined_pass_blocks_so_the_marker_cannot_rot(self):
        self.assertTrue(harness.is_blocking_failure(
            self._verdict(known_failing=True, passed=True)))

    def test_known_failing_requires_notes(self):
        base = {"id": "X", "surface": "s", "input": {},
                "rubric": {"no_digits": True}}
        self.assertFalse(harness.validate_case_dict(dict(base)))
        problems = harness.validate_case_dict(
            dict(base, known_failing=True))
        self.assertTrue(any("notes" in p for p in problems), problems)
        self.assertFalse(harness.validate_case_dict(
            dict(base, known_failing=True, notes="real bug, founder owns")))

    def test_known_failing_must_be_boolean(self):
        problems = harness.validate_case_dict(
            {"id": "X", "surface": "s", "input": {},
             "rubric": {"no_digits": True}, "known_failing": "yes"})
        self.assertTrue(any("boolean" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
