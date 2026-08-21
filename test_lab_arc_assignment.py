"""Unit tests for Lab project-arc assignment and take numbering."""
from __future__ import annotations

import unittest
from unittest.mock import Mock

from services.lab_arc_assignment import assign_recording_arc


def _assign(
    *,
    form=None,
    context=None,
    kind="spoken",
    pair=None,
    explicit=None,
    intent=None,
    user="user-1",
    database=None,
    deck=None,
    topic=None,
):
    if database is None:
        database = Mock()
        database.v2_get_session_by_id.return_value = None
        database.count_arc_sessions.return_value = 0
    return assign_recording_arc(
        {} if form is None else form,
        session_context={"topic": "Talk"} if context is None else context,
        recording_kind=kind,
        paired_session_id=pair,
        explicit_arc_id=explicit,
        project_intent=intent,
        user_id=user,
        session_id="session-1",
        database=database,
        continue_deck_arc=deck or Mock(side_effect=lambda _u, _s, a, i: (a, i)),
        continue_topic_arc=topic or Mock(side_effect=lambda _u, _t, a, i: (a, i)),
    )


class ArcAssignmentTests(unittest.TestCase):

    def test_explicit_project_uses_server_spoken_count_and_no_inference(self):
        database = Mock()
        database.get_arc_sessions.return_value = [
            {"recording_kind": "spoken"},
            {"recording_kind": "read", "paired_session_id": "s1"},
            {"recording_kind": "spoken"},
        ]
        database.v2_get_session_by_id.return_value = None
        database.count_arc_sessions.return_value = 2
        deck = Mock()
        topic = Mock()
        result = _assign(
            form={"take_index": "99"},
            explicit="arc-selected",
            database=database,
            deck=deck,
            topic=topic,
        )
        self.assertEqual(result.arc_id, "arc-selected")
        self.assertEqual(result.take_index, 3)
        deck.assert_not_called()
        topic.assert_not_called()

    def test_uploaded_deck_and_deckless_talk_use_distinct_legacy_matchers(self):
        for context, expected in (
            ({"topic": "Talk", "slides": [{"title": "One"}],
              "presentation_ref": "https://deck.pdf"}, "deck"),
            ({"topic": "Talk", "slides": [{"title": "Default"}],
              "presentation_ref": None}, "topic"),
        ):
            with self.subTest(expected=expected):
                deck = Mock(return_value=("deck-arc", 2))
                topic = Mock(return_value=("topic-arc", 2))
                result = _assign(context=context, deck=deck, topic=topic)
                self.assertEqual(result.arc_id, f"{expected}-arc")
                if expected == "deck":
                    deck.assert_called_once()
                    topic.assert_not_called()
                else:
                    topic.assert_called_once()
                    deck.assert_not_called()

    def test_explicit_new_never_runs_legacy_inference(self):
        deck = Mock()
        topic = Mock()
        _assign(intent="new", deck=deck, topic=topic)
        deck.assert_not_called()
        topic.assert_not_called()

    def test_read_inherits_parent_coordinates_and_never_counts(self):
        database = Mock()
        database.v2_get_session_by_id.return_value = {
            "arc_id": "parent-arc",
            "take_index": 2,
        }
        result = _assign(
            kind="read",
            pair="parent-session",
            database=database,
        )
        self.assertEqual(result.arc_id, "parent-arc")
        self.assertEqual(result.take_index, 2)
        self.assertEqual(result.take_count, 2)
        database.count_arc_sessions.assert_not_called()
        database.set_session_recording_kind.assert_called_once_with(
            "session-1",
            "read",
            "parent-session",
        )

    def test_retry_keeps_existing_coordinates_without_double_counting(self):
        database = Mock()
        database.v2_get_session_by_id.return_value = {
            "arc_id": "existing-arc",
            "take_index": 4,
        }
        result = _assign(database=database, user=None)
        self.assertEqual(result.arc_id, "existing-arc")
        self.assertEqual(result.take_index, 4)
        database.count_arc_sessions.assert_not_called()
        database.set_session_arc.assert_not_called()

    def test_failed_count_preserves_the_carried_take_index(self):
        database = Mock()
        database.v2_get_session_by_id.return_value = None
        database.count_arc_sessions.return_value = None
        result = _assign(
            form={"arc_id": "arc-1", "take_index": "3"},
            database=database,
            user=None,
        )
        self.assertEqual(result.take_index, 3)
        database.set_session_arc.assert_called_once_with(
            "session-1",
            "arc-1",
            3,
        )


if __name__ == "__main__":
    unittest.main()
