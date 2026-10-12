"""Where a Paragraph is born: identity for a document nobody edited.

PRODUCTION, 2026-09-19. The founder asked the right question -- "investigate
why it can't put the paragraph in the right place, maybe none is put in the
right place and that is why nothing displays" -- and the log line shipped in
#567 answered it in one number:

    services.ideal_text_parts: piece->part binding skipped
    parts=0 pieces=3 take=34e2c19c-e1d6-4efa-b2df-0a5fff6cb48d

``parts=0``. The binder was not mis-placing anything. It had NOTHING to place
against, so #564's gate fix and #567's per-row exclusion both bought exactly
nothing: three healthy pieces, zero Paragraphs, every row rejected with
``piece_has_no_part_id``.

THE CAUSE IS A GAP IN THE LIFECYCLE, NOT A BUG IN A FUNCTION. Every writer of
``ideal_text_part`` needs identity to already exist -- the edit PUT stores the
client's list, seed-on-lock adopts the client's list, and ``compose_locked``
refreshes a list that has stored locks. Nothing mints. So a document acquires
Paragraph identity only when the student EDITS or LOCKS a paragraph, and a
student who has done neither has none. That is the normal state of a fresh
project, which is why V3 has produced nothing for anyone.

TWO SURFACES WERE DARK FOR THE ONE REASON, and this is what makes it worth
fixing at the source rather than in the binder:

  1. V3's last gate, above.
  2. The deck's slide join. ``_exact_pieces`` reads ``part.get("id")`` from
     the same empty list, so it publishes ``part_id: None`` on every piece;
     the FE's ``partsFromCorePieces`` then declines the whole set (it refuses
     a partial adoption, correctly) and re-mints ids the server has never
     seen. That is #411's regression, still live for any never-edited
     document.

MINTED AT THE PUBLISH BOUNDARY, ONCE. ``build_snapshot`` already persists a
composed list and already documents why it may: it "runs only while
publishing; the GET path never calls it". Nothing else changes -- the words
are untouched (L1), and a document with any identity of its own is never
written to.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.ideal_text_parts import (
    mint_machine_parts,
)

FIRST = "The opening paragraph of the talk."
SECOND = "A second paragraph, on the very same slide."
SERVED = f"{FIRST}\n\n{SECOND}"


class ItRefusesRatherThanApproximating(unittest.TestCase):
    """None means "behave exactly as today", and it is always the safe answer."""

    def test_an_empty_document_mints_nothing(self):
        for empty in ("", "   \n\n  ", None, 42, []):
            self.assertIsNone(mint_machine_parts(empty))


    def test_an_unpaired_moment_bracket_is_refused(self):
        self.assertIsNone(mint_machine_parts("Says [[moment:a|b]]\n\nmore]]"))

    def test_more_parts_than_a_person_arranges_is_refused(self):
        from services.ideal_text_parts import MAX_PARTS
        self.assertIsNone(
            mint_machine_parts("\n\n".join(["Line."] * (MAX_PARTS + 1))))

    def test_a_document_past_the_stored_ceiling_is_refused(self):
        from services.ideal_text_parts import MAX_DOCUMENT_CHARS
        self.assertIsNone(mint_machine_parts("x" * (MAX_DOCUMENT_CHARS + 1)))

    def test_whitespace_that_does_not_round_trip_is_refused(self):
        # Three blank lines split the same way but join back as two, so the
        # offsets would be wrong from the first paragraph onward. The list is
        # checked against its own source before anything is written.
        with patch("services.ideal_text_parts.agrees_with_text",
                   return_value=False):
            self.assertIsNone(mint_machine_parts(SERVED))


class _Database:
    """The two parts calls `build_snapshot` makes, and nothing else."""

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.writes: list = []

    def get_ideal_text_parts(self, arc_id, user_id, *, with_lock=False):
        return list(self.rows)

    def replace_ideal_text_parts(self, arc_id, user_id, parts,
                                 revision_action=None):
        self.writes.append(parts)
        self.rows = [{**p, "locked_at": None, "iteration": 0} for p in parts]
        return True


def _snapshot(database, text=SERVED):
    """`build_snapshot` with everything but the parts lifecycle stubbed out."""
    from services import ideal_text_core_snapshot as mod
    # `type()` rather than a class body: a class body cannot close over
    # `text`, and binding it through the namespace keeps the stub honest.
    _Source = type("_Source", (), {"machine_text": text, "version": 1})
    _Live = type("_Live", (), {"text": text, "user_edited": False,
                               "status": "ready", "prior_edit": None})
    _Display = type("_Display", (), {"text": text, "enabled": False})

    class _Project:
        spoken_rows = [{"owner_principal_id": "owner", "project_id": "proj"}]
        latest_take_session_id = "take-1"
        title = "A talk"
        can_record_take = True
        presentation_ref = None
        slide_titles = []

    database.ideal_text = type(
        "_I", (), {"get_coach_arc_ideal_text": staticmethod(
            lambda arc: {"document": {}, "auto_text": text})})()
    with patch.object(mod, "resolve_ideal_text_source",
                      return_value=_Source()), \
        patch.object(mod, "resolve_live_text", return_value=_Live()), \
        patch.object(mod, "resolve_suggestion_display",
                     return_value=_Display()), \
        patch.object(mod, "resolve_project_read", return_value=_Project()):
        payload, _seed, _lineage = mod.build_snapshot(
            database, "arc-1", "user-1", sessions=[])
    return payload


class ThePublishBoundaryMintsWhatNobodyElseWill(unittest.TestCase):


    def test_the_words_are_not_touched(self):
        # L1. Identity is added where there was none; the canonical document
        # is the same string it was before the publish.
        self.assertEqual(_snapshot(_Database(rows=[]))["text"], SERVED)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
