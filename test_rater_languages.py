import unittest

from services.rater_languages import (
    can_rate_language,
    evaluate_rater_access,
    session_language,
    validate_proficient_languages,
)


class RaterLanguageContractTests(unittest.TestCase):
    def test_profile_requires_at_least_one_real_iso_code(self):
        self.assertIsNotNone(validate_proficient_languages([])[1])
        self.assertIsNotNone(validate_proficient_languages(["english"])[1])
        self.assertEqual(
            validate_proficient_languages([" PL ", "en", "pl"]),
            (["en", "pl"], None),
        )

    def test_declared_language_outranks_detected_language(self):
        self.assertEqual(session_language(
            {"intake_context": {"language": "pl"}},
            recording={"transcription_language": "en"},
        ), "pl")

    def test_detected_language_precedes_snippet_majority(self):
        self.assertEqual(session_language(
            {}, recording={"transcription_language": "de"},
            snippets=[{"language": "pl"}, {"language": "pl"}],
        ), "de")

    def test_unknown_language_is_never_guessed_from_transcript(self):
        self.assertIsNone(session_language(
            {}, snippets=[{"transcript": "To jest po polsku"}],
        ))

    def test_routing_requires_an_exact_match(self):
        self.assertTrue(can_rate_language(["en", "pl"], "PL"))
        self.assertFalse(can_rate_language(["en"], "pl"))
        self.assertFalse(can_rate_language(["en"], None))

    def test_access_states_never_collapse_into_a_rating(self):
        self.assertEqual(evaluate_rater_access(None, "en"), "profile_required")
        self.assertEqual(evaluate_rater_access(["en"], None), "language_unknown")
        self.assertEqual(evaluate_rater_access(["en"], "pl"), "mismatch")
        self.assertEqual(evaluate_rater_access(["en"], "EN"), "matched")


if __name__ == "__main__":
    unittest.main()
