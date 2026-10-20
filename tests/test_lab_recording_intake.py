"""
STORY    As a speaker, I want the topic, target length, special words, slides and
         slide timings I send with my recording read correctly, so that my
         transcript can be split by slide.
OUTCOME
  O1  The flat form fields sent with a recording become the recording's
      context, with numbers, lists and slide data in their proper types.
PROVES   O1 -> SessionContextParsingTests::test_flat_multipart_fields_become_the_canonical_context
"""
from __future__ import annotations

import unittest

from services.lab_recording_intake import (
    parse_session_context,
)


class SessionContextParsingTests(unittest.TestCase):

    @staticmethod
    def _vocabulary(raw):
        return [part.strip() for part in str(raw or "").split(",") if part.strip()] or None

    def test_flat_multipart_fields_become_the_canonical_context(self):
        context = parse_session_context(
            {
                "topic": "Pitch",
                "audience": "investors",
                "strategic_context": "board decision",
                "target_length_seconds": "120",
                "domain_vocabulary": "ARR, churn",
                "slides": '[{"title":"Opening"}]',
                "presentation_ref": "https://deck.pdf",
                "slide_advances": '[{"index":0,"t_ms":0}]',
                "slide_clock_offset_ms": "300.9",
            },
            parse_vocabulary=self._vocabulary,
        )

        self.assertEqual(context["topic"], "Pitch")
        self.assertEqual(context["target_length_seconds"], 120)
        self.assertEqual(context["domain_vocabulary"], ["ARR", "churn"])
        self.assertEqual(context["slides"][0]["title"], "Opening")
        self.assertEqual(context["slide_advances"][0]["t_ms"], 0)
        self.assertEqual(context["slide_clock_offset_ms"], 300)


if __name__ == "__main__":
    unittest.main()
