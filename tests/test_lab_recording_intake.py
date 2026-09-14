"""Unit tests for pure Lab recording multipart-field parsing."""
from __future__ import annotations

import unittest

from services.lab_recording_intake import (
    RecordingIntakeError,
    parse_recording_lane,
    parse_session_context,
)


PAIR = "3f7c1b6e-6f5a-4a7e-9f2b-8c1d0e5a4b39"
SNIPPET = "aaaa1111-aaaa-1111-aaaa-111111111111"


def _valid_uuid(value: str) -> bool:
    return value in (PAIR, SNIPPET)


class RecordingLaneTests(unittest.TestCase):

    def test_spoken_is_the_default_and_needs_no_pair(self):
        lane = parse_recording_lane({}, is_valid_uuid=_valid_uuid)
        self.assertEqual(lane.recording_kind, "spoken")
        self.assertIsNone(lane.paired_session_id)

    def test_read_requires_a_valid_parent_before_storage(self):
        for form in (
            {"recording_kind": "read"},
            {"recording_kind": "read", "paired_session_id": "bad"},
        ):
            with self.subTest(form=form), self.assertRaises(
                RecordingIntakeError
            ) as raised:
                parse_recording_lane(form, is_valid_uuid=_valid_uuid)
            self.assertEqual(raised.exception.status, 422)
            self.assertIn("paired_session_id", raised.exception.message)

    def test_read_requires_a_delivery_star_target(self):
        with self.assertRaises(RecordingIntakeError) as raised:
            parse_recording_lane(
                {"recording_kind": "read", "paired_session_id": PAIR},
                is_valid_uuid=_valid_uuid,
            )
        self.assertEqual(raised.exception.status, 422)
        self.assertIn("retired", raised.exception.message)

    def test_valid_read_is_normalized_case_insensitively(self):
        lane = parse_recording_lane(
            {
                "recording_kind": "  READ ",
                "paired_session_id": PAIR,
                "paired_snippet_id": SNIPPET,
            },
            is_valid_uuid=_valid_uuid,
        )
        self.assertEqual(lane.recording_kind, "read")
        self.assertEqual(lane.paired_session_id, PAIR)

    def test_unknown_kind_keeps_the_previous_spoken_fallback(self):
        lane = parse_recording_lane(
            {"recording_kind": "unknown", "paired_session_id": PAIR},
            is_valid_uuid=_valid_uuid,
        )
        self.assertEqual(lane.recording_kind, "spoken")
        self.assertEqual(lane.paired_session_id, PAIR)


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

    def test_malformed_optional_values_degrade_to_absent(self):
        context = parse_session_context(
            {
                "topic": "Pitch",
                "target_length_seconds": "120.5",
                "slides": "not json",
                "slide_advances": "not json",
                "slide_clock_offset_ms": "not a number",
            },
            parse_vocabulary=self._vocabulary,
        )

        self.assertIsNone(context["target_length_seconds"])
        self.assertIsNone(context["slides"])
        self.assertIsNone(context["slide_advances"])
        self.assertIsNone(context["slide_clock_offset_ms"])

    def test_topic_validation_still_comes_from_the_canonical_validator(self):
        from services.intake_context import IntakeContextError

        with self.assertRaises(IntakeContextError):
            parse_session_context({}, parse_vocabulary=self._vocabulary)


if __name__ == "__main__":
    unittest.main()
