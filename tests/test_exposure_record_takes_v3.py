"""The third copy of V2's exactly-three rule is registered for removal.

PRODUCTION, 2026-09-21, minutes after #599 and #600: every V3 open logged
``take feedback exposure insert failed 23514 ... violates check constraint
"take_feedback_exposure_selected_keys_check"``. 0347 relaxed the frozen
set, #599 relaxed the client-side guards; this table's inline CHECK was the
copy nobody listed. 0349 gives it the same rule as the frozen set, and the
freeze rehearsal lane inserts V3-shaped rows against it for real.
"""
from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIX = ROOT / "migrations" / "the_exposure_record_takes_the_v3_selection.sql"
MANIFEST = ROOT / "migrations" / "manifest.txt"
TIER = ROOT / "scripts" / "rehearsal_tier.sh"


class TheFixIsRegistered(unittest.TestCase):
    def test_the_migration_exists(self):
        self.assertTrue(FIX.is_file())

    def test_it_is_in_the_manifest_after_0348(self):
        lines = MANIFEST.read_text(encoding="utf-8").splitlines()
        self.assertIn(f"0349\t{FIX.name}", lines)
        self.assertLess(
            lines.index("0348\tthe_candidate_set_writer_resolves_its_own_variable.sql"),
            lines.index(f"0349\t{FIX.name}"))

    def test_it_carries_the_frozen_set_s_rule(self):
        body = FIX.read_text(encoding="utf-8")
        self.assertIn("DROP CONSTRAINT IF EXISTS "
                      "take_feedback_exposure_selected_keys_check", body)
        self.assertIn("BETWEEN 1 AND 64", body)
        self.assertIn('[{"feedback_family":"confident_voice"}]', body)

    def test_the_freeze_lane_rehearses_it(self):
        self.assertIn(FIX.stem, TIER.read_text(encoding="utf-8"))
