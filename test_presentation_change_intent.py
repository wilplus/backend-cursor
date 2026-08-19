import unittest

from services.presentation_change_intent import (
    deck_matches_recorded_project,
    handle_presentation_change,
)


class PresentationChangeIntentTests(unittest.TestCase):
    def test_new_presentation_is_always_a_new_project(self):
        result = handle_presentation_change(
            "I want to rehearse a new presentation",
            {"has_current_project": True, "completed_takes": 0},
        )
        self.assertEqual(result["intent"], "new_presentation")
        self.assertEqual(result["suggested_actions"], ["create_new_project"])

    def test_deck_can_be_replaced_before_take_one(self):
        result = handle_presentation_change(
            "Can I replace the PDF?",
            {"has_current_project": True, "completed_takes": 0},
        )
        self.assertEqual(result["intent"], "replace_pre_take_deck")
        self.assertEqual(
            result["suggested_actions"],
            ["replace_pdf", "create_new_project"],
        )

    def test_deck_is_locked_after_any_completed_take(self):
        result = handle_presentation_change(
            "Upload updated slides",
            {"has_current_project": True, "completed_takes": 1},
        )
        self.assertEqual(result["intent"], "protect_recorded_presentation")
        self.assertEqual(
            result["suggested_actions"],
            ["create_project_from_updated_deck", "keep_current_project"],
        )

    def test_small_wording_change_routes_to_slide_editor(self):
        result = handle_presentation_change(
            "I need to edit the wording on this slide",
            {"has_current_project": True, "completed_takes": 2},
        )
        self.assertEqual(result["intent"], "edit_presentation_wording")
        self.assertEqual(result["suggested_actions"], ["edit_current_slide"])

    def test_audio_upload_is_not_mistaken_for_deck_change(self):
        self.assertIsNone(
            handle_presentation_change(
                "I want to upload an audio recording",
                {"has_current_project": True, "completed_takes": 2},
            )
        )

    def test_recorded_project_rejects_a_different_pdf(self):
        prior = [{"take_index": 1, "intake_context": {
            "presentation_ref": "https://cdn/one.pdf",
            "slides": [{"title": "One", "body": "Body"}],
        }}]
        incoming = {
            "presentation_ref": "https://cdn/two.pdf",
            "slides": [{"title": "One", "body": "Body"}],
        }
        self.assertFalse(deck_matches_recorded_project(prior, incoming))

    def test_recorded_project_accepts_the_same_deck(self):
        context = {
            "presentation_ref": "https://cdn/one.pdf",
            "slides": [{"title": "One", "body": "Body"}],
        }
        self.assertTrue(deck_matches_recorded_project(
            [{"take_index": 1, "intake_context": context}], dict(context)
        ))


if __name__ == "__main__":
    unittest.main()
