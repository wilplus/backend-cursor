"""Named emotion on the take (F2 handoff §2, 2026-08-03).

The pre-recording emotion-naming answer rides the upload as a closed-
vocabulary KEY, lands on intake_context, and is coach-visible (the
user's own self-report — founder-decided). The threat/challenge BUCKET
mapping is INTERNAL ONLY (CONSTRUCT fence): a log line for the drift
metric, never a wire field.

Run: python3 -m unittest test_named_emotion
"""
from __future__ import annotations

import inspect
import unittest

from services.named_emotion import (
    EMOTION_KEYS,
    log_drift_signal,
    normalize_named_emotion,
)

try:
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    v2 = None
    _IMPORT_ERROR = e


class VocabularyTests(unittest.TestCase):

    def test_vocabulary_is_the_ten_signed_off_keys(self):
        self.assertEqual(EMOTION_KEYS, {
            "calm", "curious", "excited", "determined", "confident",
            "nervous", "tense", "overwhelmed", "doubtful", "tired",
        })

    def test_normalize_accepts_keys_case_and_padding_tolerant(self):
        self.assertEqual(normalize_named_emotion("  Nervous "), "nervous")
        self.assertEqual(normalize_named_emotion("CALM"), "calm")

    def test_unknown_words_and_non_strings_drop(self):
        self.assertIsNone(normalize_named_emotion("furious"))
        self.assertIsNone(normalize_named_emotion(""))
        self.assertIsNone(normalize_named_emotion(None))
        self.assertIsNone(normalize_named_emotion(7))

    def test_drift_log_carries_the_internal_bucket(self):
        with self.assertLogs("services.named_emotion", level="INFO") as cm:
            log_drift_signal("u1", "s1", "nervous")
        self.assertIn("bucket=threat", cm.output[0])
        with self.assertLogs("services.named_emotion", level="INFO") as cm:
            log_drift_signal("u1", "s1", "determined")
        self.assertIn("bucket=challenge", cm.output[0])


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


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class FencePinTests(unittest.TestCase):

    def test_coach_payload_serves_the_key(self):
        src = inspect.getsource(v2.v2_coach_get_session)
        self.assertIn('"named_emotion"', src)

    def test_bucket_mapping_never_reaches_the_route_layer(self):
        # CONSTRUCT fence: routes may import the normalizer and the log
        # helper — never the bucket map. The word "bucket" appearing near
        # named_emotion serialization would be the leak.
        import routes.v2_routes as routes_mod
        src = inspect.getsource(routes_mod)
        self.assertNotIn("_BUCKETS", src)
        self.assertNotIn("bucket_of", src)


if __name__ == "__main__":
    unittest.main()
