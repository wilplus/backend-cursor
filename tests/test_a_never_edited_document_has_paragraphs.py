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
    agrees_with_text, bind_pieces_to_parts, mint_machine_parts,
)

FIRST = "The opening paragraph of the talk."
SECOND = "A second paragraph, on the very same slide."
SERVED = f"{FIRST}\n\n{SECOND}"


class ItMintsIdentityForTheMachinesOwnParagraphs(unittest.TestCase):
    def test_one_part_per_paragraph_in_document_order(self):
        parts = mint_machine_parts(SERVED)
        assert parts is not None
        self.assertEqual([p["text"] for p in parts], [FIRST, SECOND])
        self.assertEqual([p["ord"] for p in parts], [0, 1])

    def test_the_list_joins_back_to_the_exact_words_it_came_from(self):
        # THE INVARIANT THE WHOLE MODULE RESTS ON. A parts list that does not
        # join back describes a document the student is not looking at, and
        # every lock set against it afterwards is anchored to the wrong words.
        parts = mint_machine_parts(SERVED)
        self.assertTrue(agrees_with_text(parts, SERVED))

    def test_the_ids_are_real_uuids_the_seed_validator_would_accept(self):
        # `validate` and `_seed_parts_for_lock` both refuse a non-UUID id, so
        # a minted id that they would reject is identity nothing can build on.
        from services.ideal_text_parts import _UUID_RE, validate
        parts = mint_machine_parts(SERVED)
        assert parts is not None
        for part in parts:
            self.assertRegex(part["id"], _UUID_RE)
        self.assertEqual(len(validate([{"id": p["id"], "text": p["text"]}
                                       for p in parts])), 2)

    def test_two_documents_do_not_share_an_id(self):
        first = mint_machine_parts(SERVED) or []
        second = mint_machine_parts(SERVED) or []
        self.assertFalse({p["id"] for p in first} & {p["id"] for p in second})


class ItRefusesRatherThanApproximating(unittest.TestCase):
    """None means "behave exactly as today", and it is always the safe answer."""

    def test_an_empty_document_mints_nothing(self):
        for empty in ("", "   \n\n  ", None, 42, []):
            self.assertIsNone(mint_machine_parts(empty))

    def test_a_paragraph_split_inside_a_marker_token_is_refused(self):
        # `_balanced`, the same guard `compose_locked` uses: an odd count of
        # style tokens is evidence the split landed inside one, and serving
        # half a token as a part's text leaks raw syntax into the document.
        self.assertIsNone(mint_machine_parts("Open **bold\n\nstill bold**."))

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
    def test_a_never_edited_document_leaves_the_publish_with_identity(self):
        database = _Database(rows=[])
        payload = _snapshot(database)
        self.assertEqual(len(database.writes), 1)
        self.assertEqual([p["text"] for p in payload["parts"]],
                         [FIRST, SECOND])

    def test_every_published_piece_carries_its_part_id(self):
        # WHAT THE DECK JOINS ON. `part_id: None` on every piece is what made
        # the FE decline the whole set and re-mint ids the server never saw.
        payload = _snapshot(_Database(rows=[]))
        ids = [piece["part_id"] for piece in payload["pieces"]]
        self.assertEqual(len(ids), 2)
        self.assertTrue(all(isinstance(i, str) and i for i in ids))

    def test_the_words_are_not_touched(self):
        # L1. Identity is added where there was none; the canonical document
        # is the same string it was before the publish.
        self.assertEqual(_snapshot(_Database(rows=[]))["text"], SERVED)

    def test_a_document_with_stored_identity_is_never_rewritten(self):
        kept = [{"id": "11111111-1111-4111-8111-111111111111", "ord": 0,
                 "text": FIRST, "locked_at": None, "iteration": 0},
                {"id": "22222222-2222-4222-8222-222222222222", "ord": 1,
                 "text": SECOND, "locked_at": None, "iteration": 0}]
        database = _Database(rows=kept)
        payload = _snapshot(database)
        self.assertEqual(database.writes, [])
        self.assertEqual([p["id"] for p in payload["parts"]],
                         [row["id"] for row in kept])

    def test_stale_stored_identity_is_kept_not_replaced(self):
        # Parts that no longer join to the served text are the ONE case where
        # minting would look attractive and would be wrong: those rows may
        # carry locks, and replacing them wholesale would drop a lock the
        # student set. Today's behaviour (`parts: None`, offsets unused) is
        # the safe answer and stays.
        database = _Database(rows=[
            {"id": "11111111-1111-4111-8111-111111111111", "ord": 0,
             "text": "Words from a document that has since moved.",
             "locked_at": None, "iteration": 0}])
        payload = _snapshot(database)
        self.assertEqual(database.writes, [])
        self.assertIsNone(payload["parts"])

    def test_a_failed_write_costs_the_publish_nothing(self):
        # Best-effort, like every other stage at this boundary: the snapshot
        # still publishes, without parts, exactly as it does today.
        database = _Database(rows=[])
        database.replace_ideal_text_parts = lambda *a, **k: False
        payload = _snapshot(database)
        self.assertIsNone(payload["parts"])
        self.assertEqual(payload["text"], SERVED)


class TheBinderNowHasSomethingToPlaceAgainst(unittest.TestCase):
    """The end of the chain the founder's `parts=0` line pointed at."""

    def test_pieces_bind_to_the_minted_paragraphs(self):
        parts = mint_machine_parts(SERVED)
        assert parts is not None
        regions = {0: (0, len(FIRST)), 1: (len(FIRST) + 2, len(SERVED))}
        bound = bind_pieces_to_parts(
            {"take_session_id": "take-1", "text": SERVED,
             "pieces": [{"snippet_id": "s1", "slide_index": 0},
                        {"snippet_id": "s2", "slide_index": 1}]},
            served_text=SERVED, slide_regions=regions, parts=parts,
        )
        self.assertEqual([p.get("part_id") for p in bound["pieces"]],
                         [parts[0]["id"], parts[1]["id"]])

    def test_without_the_mint_the_same_pieces_bind_to_nothing(self):
        # The production state, reproduced: `parts=0`, and every piece is
        # rejected downstream with `piece_has_no_part_id`.
        regions = {0: (0, len(FIRST)), 1: (len(FIRST) + 2, len(SERVED))}
        bound = bind_pieces_to_parts(
            {"take_session_id": "take-1", "text": SERVED,
             "pieces": [{"snippet_id": "s1", "slide_index": 0}]},
            served_text=SERVED, slide_regions=regions, parts=[],
        )
        self.assertEqual([p.get("part_id") for p in bound["pieces"]], [None])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
