"""Unit tests for presentation-context assembly on persisted readouts."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.readout_context import (
    attach_readout_context,
    attach_suggestions_to_chunks,
)


class SuggestionChunkAttachmentTests(unittest.TestCase):

    def test_each_suggestion_attaches_to_only_its_first_containing_chunk(self):
        card = {"upgrades": [{"text": "clearer"}]}
        snippets = [{
            "id": "snip-1",
            "start_offset_ms": 1000,
            "duration_ms": 2000,
            "say_it_stronger": card,
        }]
        chunks = [
            {"index": 0, "start_offset_ms": 0, "duration_ms": 3000},
            {"index": 1, "start_offset_ms": 0, "duration_ms": 4000},
        ]

        output = attach_suggestions_to_chunks(chunks, snippets)

        self.assertEqual(output[0]["snippet_id"], "snip-1")
        self.assertEqual(output[0]["say_it_stronger"], card)
        self.assertIsNone(output[1]["snippet_id"])
        self.assertIsNone(output[1]["say_it_stronger"])
        self.assertNotIn("snippet_id", chunks[0])


class ReadoutContextTests(unittest.TestCase):

    def _database(self, context=None, transcripts=None):
        database = MagicMock()
        database.get_session_intake_context.return_value = context or {}
        database.get_session_slide_transcripts.return_value = transcripts
        return database

    def test_canonical_pieces_are_deduplicated_and_outrank_context_chunks(self):
        database = self._database(
            context={},
            transcripts=[{"index": 0, "transcript": "stored transcript"}],
        )
        first_card = {"upgrades": [{"text": "first"}]}
        output_snippets = [
            {
                "id": "first",
                "piece_index": 0,
                "transcript": "canonical first",
                "start_offset_ms": 0,
                "duration_ms": 1000,
                "say_it_stronger": first_card,
            },
            {
                "id": "retry-duplicate",
                "piece_index": 0,
                "transcript": "must not duplicate",
            },
            {
                "id": "second",
                "piece_index": 1,
                "slide_index": 2,
                "recording_kind": "spoken",
                "transcript": "canonical second",
                "applied_upgrade_indexes": [0],
            },
        ]
        result = {}

        attach_readout_context(
            database,
            "session-1",
            [],
            output_snippets,
            result,
            edits_by_chunk={1: "edited second"},
            include_upgrade_cards=True,
        )

        chunks = result["instant_chunks"]
        self.assertEqual([chunk["index"] for chunk in chunks], [0, 1])
        self.assertEqual(chunks[0]["transcript"], "canonical first")
        self.assertEqual(chunks[0]["say_it_stronger"], first_card)
        self.assertEqual(chunks[1]["slide_index"], 2)
        self.assertEqual(chunks[1]["recording_kind"], "spoken")
        self.assertEqual(chunks[1]["user_edited_text"], "edited second")
        self.assertEqual(chunks[1]["applied_upgrade_indexes"], [0])

    def test_deck_context_restores_setup_maps_slides_and_uses_persisted_stx(self):
        slides = [{"title": "Opening"}]
        slide_transcripts = [{
            "index": 0,
            "transcript": "what was said",
            "start_offset_ms": 0,
            "duration_ms": 2500,
        }]
        database = self._database(
            context={
                "topic": "Pitch",
                "audience": "  investors  ",
                "target_length_seconds": 300,
                "slides": slides,
                "slide_advances": [{"index": 0, "t_ms": 0}],
                "presentation_ref": "https://deck.pdf",
            },
            transcripts=slide_transcripts,
        )
        output_snippets = [{
            "id": "snip-1",
            "start_offset_ms": 0,
            "duration_ms": 2000,
            "say_it_stronger": {"upgrades": [{"text": "stronger"}]},
        }]
        result = {}

        with patch(
            "services.slide_alignment.slide_for_snippet",
            return_value=slides[0],
        ):
            attach_readout_context(
                database,
                "session-1",
                [],
                output_snippets,
                result,
                edits_by_chunk={},
                include_upgrade_cards=True,
            )

        self.assertEqual(result["setup"]["topic"], "Pitch")
        self.assertEqual(result["audience"], "investors")
        self.assertEqual(result["presentation_ref"], "https://deck.pdf")
        self.assertEqual(result["slides"], slides)
        self.assertEqual(result["slide_transcripts"], slide_transcripts)
        self.assertEqual(output_snippets[0]["slide"], slides[0])
        self.assertEqual(result["instant_chunks"][0]["snippet_id"], "snip-1")

    def test_deckless_context_preserves_chunk_edits_and_full_transcript(self):
        slide_transcripts = [
            {"index": 0, "transcript": "first part"},
            {"index": 1, "transcript": "second part"},
        ]
        database = self._database(context={}, transcripts=slide_transcripts)
        chunks = [
            {
                "index": 0,
                "transcript": "first part",
                "start_offset_ms": 0,
                "duration_ms": 2000,
            },
            {
                "index": 1,
                "transcript": "second part",
                "start_offset_ms": 2000,
                "duration_ms": 2000,
            },
        ]
        output_snippets = [{
            "id": "snip-1",
            "start_offset_ms": 500,
            "duration_ms": 1000,
            "say_it_stronger": {"upgrades": [{"text": "clearer"}]},
        }]
        result = {}

        with patch(
            "services.slide_word_split.deckless_chunks_from_stx",
            return_value=chunks,
        ):
            attach_readout_context(
                database,
                "session-1",
                [],
                output_snippets,
                result,
                edits_by_chunk={1: "edited second"},
                include_upgrade_cards=True,
            )

        self.assertEqual(result["full_transcript"], "first part second part")
        self.assertIsNone(result["full_transcript_chunks"][0]["user_edited_text"])
        self.assertEqual(
            result["full_transcript_chunks"][1]["user_edited_text"],
            "edited second",
        )
        self.assertEqual(result["instant_chunks"][0]["snippet_id"], "snip-1")

    def test_context_lookup_failure_is_non_fatal(self):
        database = self._database()
        database.get_session_intake_context.side_effect = RuntimeError("down")
        database.get_session_slide_transcripts.side_effect = RuntimeError("down")
        result = {}

        attach_readout_context(
            database,
            "session-1",
            [],
            [],
            result,
            edits_by_chunk={},
            include_upgrade_cards=True,
        )

        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
