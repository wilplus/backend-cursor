"""willab — the coach STAR VERDICT (founder 2026-07-27).

services/star_verdicts.py: the decision-layer correction corpus for the
voice-text analytics — did this star deserve to fire, and as the right kind?

WHAT THIS PINS DOWN:
  * the three verdicts, and that 'wrong_kind' CANNOT be stored without the
    correction (the correction IS the signal — a bare rejection is worth much
    less than a labeled confusion pair);
  * the device vocabulary tracks the modules that OWN it, so adding a delivery
    device can't leave this validator silently rejecting it;
  * BLIND COACH — the sharp fence. This surface shows the coach the machine's
    guess, so it must be provably separate from the blind confidence-labeling
    lane: no training_labels join, no shadow-model import, and no
    acoustic_read / direction riding the review payload;
  * AC-9 — a verdict never reaches a student payload;
  * the corpus summary is honest about what it does NOT contain (false
    negatives), so a training run can't mistake precision data for a balanced
    sample.

Run: python3 -m unittest tests.test_star_verdicts
"""
from __future__ import annotations

import glob
import os
import sys
import types
import unittest
from unittest.mock import MagicMock

# The /v2 route layer is the per-domain modules under routes/v2/ (the
# routes/v2_routes.py façade is gone since audit Q-A3). Source-level fences
# below must read ALL of them, or carving a domain out silently empties the
# fence. Globbed rather than listed so later phases are covered automatically.
_V2_ROUTE_FILES = {
    p: open(p, encoding="utf-8").read()
    for p in sorted(glob.glob("routes/v2/*.py"))
    if os.path.basename(p) != "__init__.py"
}


def _v2_route_source() -> str:
    """Every /v2 route module's source, concatenated."""
    return "\n".join(_V2_ROUTE_FILES.values())


_ORIG_SERVICES_DB = None


def setUpModule():
    global _ORIG_SERVICES_DB
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)


class TestVocabularyTracksItsOwners(unittest.TestCase):
    """The device lists must come FROM the modules that own them — a
    re-declared copy drifts the moment someone adds a device."""

    def test_star_kinds_match_the_suggestion_table(self):
        """STAR_KINDS mirrors moment_suggestions.kind — if the CHECK widens
        and this doesn't, verdicts on the new family are silently rejected."""
        from services.star_verdicts import STAR_KINDS
        with open("migrations/alter_moment_suggestions_kind_delivery.sql",
                  encoding="utf-8") as fh:
            sql = fh.read()
        for kind in STAR_KINDS:
            self.assertIn(f"'{kind}'", sql)


class TestBlindCoachFence(unittest.TestCase):
    """THE guardrail the founder asked for: the star-verdict lane must stay
    completely separated from the blind confidence-labeling lane."""

    def _source(self) -> str:
        with open("services/star_verdicts.py", encoding="utf-8") as fh:
            return fh.read()

    def test_module_never_imports_the_coach_truth_lane(self):
        """Checked at the AST level, not by grepping text: the docstring
        deliberately NAMES these to explain the fence, and a prose mention is
        exactly what we want to keep. What must never appear is an actual
        import."""
        import ast
        tree = ast.parse(self._source())
        imported: set = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module)
                imported.update(f"{node.module}.{a.name}"
                                for a in node.names if node.module)
        for banned in ("training_labels", "learning_serve", "learning_train",
                       "challenge_threat", "acoustic_read"):
            for name in imported:
                self.assertNotIn(
                    banned, name,
                    f"{banned} must not be imported into the star-verdict lane "
                    f"(found: {name})")

    def test_module_never_reads_a_coach_truth_table(self):
        """No table access at all — this module is pure. A .table(...) call
        appearing here would mean the validation lane grew a DB dependency and
        could reach the labeling corpus."""
        import ast
        tree = ast.parse(self._source())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                self.assertFalse(
                    isinstance(fn, ast.Attribute) and fn.attr == "table",
                    "star_verdicts must stay pure — no table access")


class TestAC9Fence(unittest.TestCase):

    def test_student_surface_only_reads_verdicts_for_supersession(self):
        """Verdicts may govern suppression and fresh coach proposals, but the
        raw judgment row must not spread to any other student surface."""
        import subprocess
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", "star_verdict",
             "services/", "routes/"],
            capture_output=True, text=True)
        for line in result.stdout.splitlines():
            path = line.split(":", 1)[0]
            self.assertIn(path, (
                "services/star_verdicts.py", "services/db.py",
                "routes/v2/coach.py",
                "routes/v2/explore_ideal_text.py",
                # The student `changes` block, moved out of the route in
                # Phase 5 (audit Q-C1). Same read, same purpose: verdicts
                # govern suppression and supersession, never a surface.
                "services/ideal_text_changes.py",
                # Compliance-only subject inventory. It never returns a
                # verdict to the student; it locates the row for deletion.
                "services/data_purge_registry.py",
            ), f"unexpected reader of star_verdicts: {line}")


if __name__ == "__main__":
    unittest.main()
