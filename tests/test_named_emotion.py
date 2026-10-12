"""Named emotion on the take (F2 handoff §2, 2026-08-03).

The pre-recording emotion-naming answer rides the upload as a closed-
vocabulary KEY, lands on intake_context, and is coach-visible as the
user's own self-report. It is never converted into a psychological bucket.

Run: python3 -m unittest tests.test_named_emotion
"""
from __future__ import annotations

import unittest

try:
    from routes.v2 import lab_recording as v2_lab_recording
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    _IMPORT_ERROR = e


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class CaptureTests(unittest.TestCase):

    def test_flow_tags_capture_a_valid_key(self):
        tags = v2_lab_recording._recording_flow_tags({"named_emotion": " Excited "})
        self.assertEqual(tags.get("named_emotion"), "excited")


if __name__ == "__main__":
    unittest.main()
