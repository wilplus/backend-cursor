"""Unit tests for services.insights_payload (publish pivot §3.9/§3.10).

The publish-contract validator: the library floor (≥1 tagged snippet
note) + tag enum + overall_message OPTIONAL (design §6b/§14, resolving
the §3.10 'required' conflict).

Run: python3 -m unittest test_insights_payload
"""
from __future__ import annotations

import unittest


class ValidateInsightsPayloadTests(unittest.TestCase):

    def _v(self, body):
        from services.insights_payload import validate_insights_payload
        return validate_insights_payload(body)

    def _note(self, **over):
        base = {"snippet_id": "s1", "note": "Strong open.", "tag": "strong"}
        base.update(over)
        return base

    # ── Happy paths ────────────────────────────────────────────────

    def test_minimal_valid_one_note_no_overall(self):
        """overall_message OPTIONAL — one tagged note satisfies the floor."""
        out = self._v({"snippet_notes": [self._note()]})
        self.assertIsNone(out["overall_message"])
        self.assertEqual(len(out["snippet_notes"]), 1)
        self.assertEqual(out["snippet_notes"][0]["tag"], "strong")

    def test_with_overall_message(self):
        out = self._v({
            "overall_message": "  Great session overall.  ",
            "snippet_notes": [self._note()],
        })
        self.assertEqual(out["overall_message"], "Great session overall.")

    def test_multiple_notes_both_tags(self):
        out = self._v({"snippet_notes": [
            self._note(snippet_id="a", tag="strong"),
            self._note(snippet_id="b", tag="to_work_on"),
        ]})
        self.assertEqual(len(out["snippet_notes"]), 2)

    def test_empty_overall_collapses_to_none(self):
        out = self._v({
            "overall_message": "   ",
            "snippet_notes": [self._note()],
        })
        self.assertIsNone(out["overall_message"])

    # ── Library floor ──────────────────────────────────────────────

    def test_no_snippet_notes_rejected(self):
        from services.insights_payload import InsightsPayloadError
        with self.assertRaises(InsightsPayloadError) as cm:
            self._v({"snippet_notes": []})
        self.assertIn("library floor", str(cm.exception).lower())

    def test_missing_snippet_notes_rejected(self):
        from services.insights_payload import InsightsPayloadError
        with self.assertRaises(InsightsPayloadError):
            self._v({"overall_message": "hi"})

    # ── Per-note validation ────────────────────────────────────────

    def test_note_without_tag_defaults_strong(self):
        # §1.C (FE handoff 2026-06-19): a missing/blank tag is no longer
        # rejected — it defaults to "strong" (the lenient publish floor; a
        # present note is what gates publish, not the tag).
        out = self._v({"snippet_notes": [{"snippet_id": "s1", "note": "x"}]})
        self.assertEqual(out["snippet_notes"][0]["tag"], "strong")
        # a null tag defaults too
        out2 = self._v({"snippet_notes": [
            {"snippet_id": "s1", "note": "x", "tag": None}]})
        self.assertEqual(out2["snippet_notes"][0]["tag"], "strong")

    def test_bad_tag_rejected(self):
        from services.insights_payload import InsightsPayloadError
        with self.assertRaises(InsightsPayloadError):
            self._v({"snippet_notes": [self._note(tag="amazing")]})

    def test_empty_note_rejected(self):
        from services.insights_payload import InsightsPayloadError
        with self.assertRaises(InsightsPayloadError) as cm:
            self._v({"snippet_notes": [self._note(note="   ")]})
        self.assertIn("note", str(cm.exception))

    def test_missing_snippet_id_rejected(self):
        from services.insights_payload import InsightsPayloadError
        with self.assertRaises(InsightsPayloadError):
            self._v({"snippet_notes": [{"note": "x", "tag": "strong"}]})

    def test_duplicate_snippet_id_rejected(self):
        from services.insights_payload import InsightsPayloadError
        with self.assertRaises(InsightsPayloadError) as cm:
            self._v({"snippet_notes": [
                self._note(snippet_id="dup"),
                self._note(snippet_id="dup", tag="to_work_on"),
            ]})
        self.assertIn("duplicate", str(cm.exception).lower())

    def test_over_long_note_rejected(self):
        from services.insights_payload import (
            InsightsPayloadError, _MAX_NOTE_LEN,
        )
        with self.assertRaises(InsightsPayloadError):
            self._v({"snippet_notes": [self._note(note="x" * (_MAX_NOTE_LEN + 1))]})

    def test_non_dict_body_rejected(self):
        from services.insights_payload import InsightsPayloadError
        for bad in ["x", 42, [1], None]:
            with self.assertRaises(InsightsPayloadError):
                self._v(bad)

    def test_valid_tags_constant(self):
        from services.insights_payload import VALID_TAGS
        self.assertEqual(set(VALID_TAGS), {"strong", "to_work_on"})

    # ── PR-2: coach `when` + `examples` (optional, stable shape) ────

    def test_absent_when_examples_normalize(self):
        """A note that omits when/examples still gets the stable shape —
        when=None, examples=[] — so the readout/FE 'hidden when absent'
        round-trip is predictable and backward-compatible."""
        out = self._v({"snippet_notes": [self._note()]})
        n = out["snippet_notes"][0]
        self.assertIsNone(n["when"])
        self.assertEqual(n["examples"], [])

    def test_when_examples_round_trip(self):
        out = self._v({"snippet_notes": [self._note(
            when="  when you opened the close  ",
            examples=["  We should ship it.  ", "Let's go."],
        )]})
        n = out["snippet_notes"][0]
        self.assertEqual(n["when"], "when you opened the close")
        self.assertEqual(n["examples"], ["We should ship it.", "Let's go."])

    def test_empty_when_collapses_to_none(self):
        out = self._v({"snippet_notes": [self._note(when="   ")]})
        self.assertIsNone(out["snippet_notes"][0]["when"])

    def test_examples_drops_empty_strings(self):
        out = self._v({"snippet_notes": [self._note(
            examples=["keep", "  ", "", "also keep"],
        )]})
        self.assertEqual(out["snippet_notes"][0]["examples"], ["keep", "also keep"])

    def test_when_non_string_rejected(self):
        from services.insights_payload import InsightsPayloadError
        with self.assertRaises(InsightsPayloadError) as cm:
            self._v({"snippet_notes": [self._note(when=42)]})
        self.assertIn("when", str(cm.exception))

    def test_examples_non_list_rejected(self):
        from services.insights_payload import InsightsPayloadError
        with self.assertRaises(InsightsPayloadError) as cm:
            self._v({"snippet_notes": [self._note(examples="not a list")]})
        self.assertIn("examples", str(cm.exception))

    def test_examples_non_string_item_rejected(self):
        from services.insights_payload import InsightsPayloadError
        with self.assertRaises(InsightsPayloadError):
            self._v({"snippet_notes": [self._note(examples=["ok", 7])]})

    def test_examples_over_cap_rejected(self):
        from services.insights_payload import InsightsPayloadError, _MAX_EXAMPLES
        with self.assertRaises(InsightsPayloadError):
            self._v({"snippet_notes": [self._note(
                examples=[f"e{i}" for i in range(_MAX_EXAMPLES + 1)],
            )]})

    def test_over_long_when_rejected(self):
        from services.insights_payload import InsightsPayloadError, _MAX_WHEN_LEN
        with self.assertRaises(InsightsPayloadError):
            self._v({"snippet_notes": [self._note(when="x" * (_MAX_WHEN_LEN + 1))]})

    # ── breakthrough_video_ref (per-snippet coach video URL) ───────

    def test_breakthrough_video_ref_default_none(self):
        # Always present on the cleaned note, None when omitted.
        out = self._v({"snippet_notes": [self._note()]})
        self.assertIsNone(out["snippet_notes"][0]["breakthrough_video_ref"])

    def test_breakthrough_video_ref_preserved(self):
        url = "https://media.willpowerlab.com/coach/bt/abc.mp4"
        out = self._v({"snippet_notes": [self._note(breakthrough_video_ref=url)]})
        self.assertEqual(
            out["snippet_notes"][0]["breakthrough_video_ref"], url
        )

    def test_breakthrough_video_ref_empty_to_none(self):
        out = self._v({"snippet_notes": [
            self._note(breakthrough_video_ref="   ")
        ]})
        self.assertIsNone(out["snippet_notes"][0]["breakthrough_video_ref"])

    def test_breakthrough_video_ref_non_string_rejected(self):
        from services.insights_payload import InsightsPayloadError
        with self.assertRaises(InsightsPayloadError):
            self._v({"snippet_notes": [self._note(breakthrough_video_ref=123)]})

    def test_breakthrough_video_ref_non_url_rejected(self):
        # It lands in a learner's <video> src — must be http(s), not
        # javascript:/data:/a bare string.
        from services.insights_payload import InsightsPayloadError
        for bad in ("javascript:alert(1)", "data:video/mp4;base64,AAA", "clip.mp4"):
            with self.assertRaises(InsightsPayloadError):
                self._v({"snippet_notes": [
                    self._note(breakthrough_video_ref=bad)
                ]})

    def test_breakthrough_video_ref_over_long_rejected(self):
        from services.insights_payload import (
            InsightsPayloadError, _MAX_VIDEO_REF_LEN,
        )
        with self.assertRaises(InsightsPayloadError):
            self._v({"snippet_notes": [self._note(
                breakthrough_video_ref="h" * (_MAX_VIDEO_REF_LEN + 1),
            )]})

    # ── transcript_corrected (founder 2026-07-06 — a real coach-authored
    # correction of the transcript, FREE unconditionally once surfaced) ──

    def test_transcript_corrected_default_none(self):
        out = self._v({"snippet_notes": [self._note()]})
        self.assertIsNone(out["snippet_notes"][0]["transcript_corrected"])

    def test_transcript_corrected_preserved(self):
        text = "The corrected line, verbatim."
        out = self._v({"snippet_notes": [
            self._note(transcript_corrected=text),
        ]})
        self.assertEqual(
            out["snippet_notes"][0]["transcript_corrected"], text)

    def test_transcript_corrected_whitespace_to_none(self):
        out = self._v({"snippet_notes": [
            self._note(transcript_corrected="   "),
        ]})
        self.assertIsNone(out["snippet_notes"][0]["transcript_corrected"])

    def test_transcript_corrected_non_string_rejected(self):
        from services.insights_payload import InsightsPayloadError
        with self.assertRaises(InsightsPayloadError):
            self._v({"snippet_notes": [
                self._note(transcript_corrected=123),
            ]})

    def test_transcript_corrected_over_long_rejected(self):
        from services.insights_payload import (
            InsightsPayloadError, _MAX_TRANSCRIPT_CORRECTED_LEN,
        )
        with self.assertRaises(InsightsPayloadError):
            self._v({"snippet_notes": [self._note(
                transcript_corrected="x" * (_MAX_TRANSCRIPT_CORRECTED_LEN + 1),
            )]})


if __name__ == "__main__":
    unittest.main()
