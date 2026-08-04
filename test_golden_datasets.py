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


if __name__ == "__main__":
    unittest.main()
