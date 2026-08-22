"""Named emotion on the take (F2 handoff §2, 2026-08-03).

The pre-recording emotion-naming answer rides the upload as a closed-
vocabulary KEY, lands on intake_context, and is coach-visible as the
user's own self-report. It is never converted into a psychological bucket.

Run: python3 -m unittest test_named_emotion
"""
from __future__ import annotations

import unittest

from services.named_emotion import (
    EMOTION_KEYS,
    normalize_named_emotion,
)

try:
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    v2 = None
    _IMPORT_ERROR = e


class VocabularyTests(unittest.TestCase):

    def test_vocabulary_is_the_signed_off_keys(self):
        self.assertEqual(EMOTION_KEYS, {
            "calm", "curious", "excited", "determined", "confident",
            "nervous", "tense", "overwhelmed", "doubtful", "tired",
            "unsure",
        })

    def test_unsure_is_captured_verbatim(self):
        self.assertEqual(normalize_named_emotion("unsure"), "unsure")

    def test_normalize_accepts_keys_case_and_padding_tolerant(self):
        self.assertEqual(normalize_named_emotion("  Nervous "), "nervous")
        self.assertEqual(normalize_named_emotion("CALM"), "calm")

    def test_unknown_words_and_non_strings_drop(self):
        self.assertIsNone(normalize_named_emotion("furious"))
        self.assertIsNone(normalize_named_emotion(""))
        self.assertIsNone(normalize_named_emotion(None))
        self.assertIsNone(normalize_named_emotion(7))

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class CaptureTests(unittest.TestCase):

    def test_flow_tags_capture_a_valid_key(self):
        tags = v2._recording_flow_tags({"named_emotion": " Excited "})
        self.assertEqual(tags.get("named_emotion"), "excited")

    def test_flow_tags_drop_an_unknown_word_silently(self):
        tags = v2._recording_flow_tags({"named_emotion": "rage"})
        self.assertNotIn("named_emotion", tags)

    def test_absent_field_adds_nothing(self):
        self.assertNotIn("named_emotion", v2._recording_flow_tags({}))

if __name__ == "__main__":
    unittest.main()
