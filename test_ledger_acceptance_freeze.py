"""Accepted text is immutable; later coach revisions form a chain."""
from __future__ import annotations

import unittest

from services.ideal_decision_ledger import (
    bake_piece, frozen_approved_replacement,
)


class AcceptanceFreezeTests(unittest.TestCase):
    def test_reload_uses_the_accepted_ledger_text_not_mutable_coach_final(self):
        rows = [{
            "decision": "approved", "source": "user_star",
            "snippet_id": "s1", "replacement_text": "Accepted machine words",
            "version": 1,
        }]
        suggestion = {
            "replacement_text_draft": "Accepted machine words",
            "replacement_text": "Later coach words",
        }
        self.assertEqual(
            frozen_approved_replacement(rows, "s1", suggestion),
            "Accepted machine words",
        )

    def test_without_acceptance_machine_draft_is_the_only_safe_fallback(self):
        suggestion = {
            "replacement_text_draft": "Machine draft",
            "replacement_text": "Mutable coach final",
        }
        self.assertEqual(
            frozen_approved_replacement([], "s1", suggestion),
            "Machine draft",
        )

    def test_accepting_a_coach_revision_applies_after_machine_acceptance(self):
        rows = [
            {"decision": "approved", "source": "user_star",
             "kind": "replace", "display_phrase": "Original words",
             "replacement_text": "Machine accepted words"},
            {"decision": "approved", "source": "user_star",
             "kind": "replace", "display_phrase": "Machine accepted words",
             "replacement_text": "Coach final words"},
        ]
        self.assertEqual(bake_piece("Original words", rows),
                         "Coach final words")


if __name__ == "__main__":
    unittest.main()
