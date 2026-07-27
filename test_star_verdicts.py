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

Run: python3 -m unittest test_star_verdicts
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock

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


class TestVerdictValidation(unittest.TestCase):

    def test_keep_is_the_minimal_valid_verdict(self):
        from services.star_verdicts import validate_verdict
        row, err = validate_verdict({"star_kind": "delivery",
                                     "star_device": "emphasis",
                                     "verdict": "keep"})
        self.assertIsNone(err)
        self.assertEqual(row["verdict"], "keep")
        self.assertEqual(row["star_kind"], "delivery")
        self.assertEqual(row["star_device"], "emphasis")
        self.assertIsNone(row["corrected_device"])

    def test_should_not_fire_needs_no_correction(self):
        from services.star_verdicts import validate_verdict
        row, err = validate_verdict({"star_kind": "structure",
                                     "star_device": "contrast",
                                     "verdict": "should_not_fire"})
        self.assertIsNone(err)
        self.assertEqual(row["verdict"], "should_not_fire")

    def test_wrong_kind_without_a_correction_is_rejected(self):
        """The whole value of 'wrong kind' is WHICH kind it should have been —
        a bare rejection is nearly worthless as training signal."""
        from services.star_verdicts import validate_verdict
        row, err = validate_verdict({"star_kind": "delivery",
                                     "star_device": "emphasis",
                                     "verdict": "wrong_kind"})
        self.assertIsNone(row)
        self.assertIn("corrected_device", err)

    def test_wrong_kind_with_a_correction_is_stored(self):
        from services.star_verdicts import validate_verdict
        row, err = validate_verdict({"star_kind": "delivery",
                                     "star_device": "emphasis",
                                     "verdict": "wrong_kind",
                                     "corrected_device": "pace_slow"})
        self.assertIsNone(err)
        self.assertEqual(row["corrected_device"], "pace_slow")

    def test_correction_may_name_another_family(self):
        """delivery -> structure is a legitimate confusion; the correction
        validates against devices AND kinds."""
        from services.star_verdicts import validate_verdict
        row, err = validate_verdict({"star_kind": "delivery",
                                     "star_device": "pause",
                                     "verdict": "wrong_kind",
                                     "corrected_device": "contrast"})
        self.assertIsNone(err)
        self.assertEqual(row["corrected_device"], "contrast")

    def test_correction_equal_to_the_original_is_rejected(self):
        from services.star_verdicts import validate_verdict
        row, err = validate_verdict({"star_kind": "delivery",
                                     "star_device": "pause",
                                     "verdict": "wrong_kind",
                                     "corrected_device": "pause"})
        self.assertIsNone(row)
        self.assertIn("differ", err)

    def test_correction_on_a_keep_is_rejected(self):
        from services.star_verdicts import validate_verdict
        row, err = validate_verdict({"star_kind": "delivery",
                                     "star_device": "pause",
                                     "verdict": "keep",
                                     "corrected_device": "pace_fast"})
        self.assertIsNone(row)

    def test_unknown_verdict_and_kind_are_rejected(self):
        from services.star_verdicts import validate_verdict
        self.assertIsNone(validate_verdict(
            {"star_kind": "delivery", "verdict": "maybe"})[0])
        self.assertIsNone(validate_verdict(
            {"star_kind": "vibes", "verdict": "keep"})[0])
        self.assertIsNone(validate_verdict("not a dict")[0])
        self.assertIsNone(validate_verdict(None)[0])

    def test_device_must_belong_to_its_family(self):
        from services.star_verdicts import validate_verdict
        row, err = validate_verdict({"star_kind": "delivery",
                                     "star_device": "contrast",
                                     "verdict": "keep"})
        self.assertIsNone(row)
        self.assertIn("star_device", err)

    def test_single_device_families_reject_a_device(self):
        from services.star_verdicts import validate_verdict
        row, err = validate_verdict({"star_kind": "emphasize",
                                     "star_device": "emphasis",
                                     "verdict": "keep"})
        self.assertIsNone(row)

    def test_note_is_captured_and_bounded(self):
        from services.star_verdicts import validate_verdict
        row, _ = validate_verdict({"star_kind": "emphasize",
                                   "verdict": "should_not_fire",
                                   "note": "x" * 5000})
        self.assertEqual(len(row["note"]), 1000)


class TestVocabularyTracksItsOwners(unittest.TestCase):
    """The device lists must come FROM the modules that own them — a
    re-declared copy drifts the moment someone adds a device."""

    def test_delivery_devices_match_delivery_stars(self):
        from services.delivery_stars import DELIVERY_DEVICES
        from services.star_verdicts import valid_devices
        self.assertEqual(set(valid_devices("delivery")), set(DELIVERY_DEVICES))

    def test_structural_devices_match_moment_suggestions(self):
        from services.moment_suggestions import _STRUCT_DEVICES
        from services.star_verdicts import valid_devices
        self.assertEqual(set(valid_devices("structure")), set(_STRUCT_DEVICES))

    def test_star_kinds_match_the_suggestion_table(self):
        """STAR_KINDS mirrors moment_suggestions.kind — if the CHECK widens
        and this doesn't, verdicts on the new family are silently rejected."""
        from services.star_verdicts import STAR_KINDS
        with open("migrations/alter_moment_suggestions_kind_delivery.sql",
                  encoding="utf-8") as fh:
            sql = fh.read()
        for kind in STAR_KINDS:
            self.assertIn(f"'{kind}'", sql)

    def test_unknown_kind_has_no_devices(self):
        from services.star_verdicts import valid_devices
        self.assertEqual(valid_devices("nope"), ())
        self.assertEqual(valid_devices(None), ())


class TestReviewList(unittest.TestCase):

    _SUGGESTIONS = [
        {"snippet_id": "s1", "kind": "delivery", "trigger": "pace_fast",
         "why": "faster than usual"},
        {"snippet_id": "s2", "kind": "structure", "trigger": "contrast",
         "why": "it's not X, it's Y"},
        {"snippet_id": "s3", "kind": "replace", "replacement_text": "try this",
         "trigger": "profanity"},
    ]

    def test_unjudged_stars_carry_a_null_verdict(self):
        from services.star_verdicts import stars_with_verdicts
        rows = stars_with_verdicts(self._SUGGESTIONS, {})
        self.assertEqual(len(rows), 3)
        for r in rows:
            self.assertIsNone(r["verdict"])
            self.assertFalse(r["judged"])

    def test_existing_verdicts_are_attached(self):
        from services.star_verdicts import stars_with_verdicts
        rows = stars_with_verdicts(self._SUGGESTIONS, {
            "s2": {"verdict": "should_not_fire", "note": "not a real contrast"},
        })
        by_id = {r["snippet_id"]: r for r in rows}
        self.assertEqual(by_id["s2"]["verdict"], "should_not_fire")
        self.assertTrue(by_id["s2"]["judged"])
        self.assertFalse(by_id["s1"]["judged"])

    def test_delivery_device_comes_from_trigger(self):
        from services.star_verdicts import stars_with_verdicts
        by_id = {r["snippet_id"]: r
                 for r in stars_with_verdicts(self._SUGGESTIONS, {})}
        self.assertEqual(by_id["s1"]["star_device"], "pace_fast")
        # Non-delivery families are single-device — no device, and the UI gets
        # an empty option list rather than a misleading one.
        self.assertIsNone(by_id["s3"]["star_device"])
        self.assertEqual(by_id["s3"]["device_options"], [])

    def test_device_options_drive_the_wrong_kind_picker(self):
        from services.star_verdicts import stars_with_verdicts
        by_id = {r["snippet_id"]: r
                 for r in stars_with_verdicts(self._SUGGESTIONS, {})}
        self.assertIn("pause", by_id["s1"]["device_options"])
        self.assertIn("list_of_three", by_id["s2"]["device_options"])

    def test_junk_rows_are_skipped_not_fatal(self):
        from services.star_verdicts import stars_with_verdicts
        rows = stars_with_verdicts(
            [None, 7, {}, {"snippet_id": "ok", "kind": "emphasize"}], {})
        self.assertEqual(len(rows), 1)
        self.assertEqual(stars_with_verdicts(None, None), [])


class TestCorpusSummary(unittest.TestCase):

    _ROWS = [
        {"star_kind": "delivery", "star_device": "emphasis", "verdict": "keep"},
        {"star_kind": "delivery", "star_device": "pace_fast",
         "verdict": "wrong_kind", "corrected_device": "pace_slow"},
        {"star_kind": "structure", "star_device": "contrast",
         "verdict": "should_not_fire"},
    ]

    def test_counts_by_verdict_and_kind(self):
        from services.star_verdicts import corpus_summary
        s = corpus_summary(self._ROWS)
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["by_verdict"]["keep"], 1)
        self.assertEqual(s["by_verdict"]["wrong_kind"], 1)
        self.assertEqual(s["by_verdict"]["should_not_fire"], 1)
        self.assertEqual(s["by_kind"]["delivery"], 2)

    def test_confusion_pairs_are_surfaced(self):
        from services.star_verdicts import corpus_summary
        s = corpus_summary(self._ROWS)
        self.assertEqual(s["confusions"], {"pace_fast->pace_slow": 1})

    def test_summary_declares_the_missing_half(self):
        """A corpus of judgments on stars that FIRED is precision data only.
        Saying so in the payload is what stops a later training run from
        treating it as a balanced sample and overfitting toward silence."""
        from services.star_verdicts import corpus_summary
        self.assertFalse(corpus_summary(self._ROWS)["false_negatives_captured"])
        self.assertFalse(corpus_summary([])["false_negatives_captured"])

    def test_empty_and_junk_are_safe(self):
        from services.star_verdicts import corpus_summary
        self.assertEqual(corpus_summary(None)["total"], 0)
        self.assertEqual(corpus_summary([None, 3, "x"])["total"], 0)


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

    def test_review_payload_carries_no_confidence_signal(self):
        """A coach judging ADVICE must not be shown the machine's read of the
        VOICE in the same payload — that's what would anchor their blind
        label."""
        from services.star_verdicts import stars_with_verdicts
        rows = stars_with_verdicts([{
            "snippet_id": "s1", "kind": "delivery", "trigger": "pause",
            # Even if a caller hands over a suggestion row polluted with these,
            # the allowlisted payload must not carry them through.
            "acoustic_read": {"potentiometer": 0.9},
            "direction": "challenge",
            "shadow_label": "challenge",
            "voice_confidence": {"score": 0.8},
        }], {})
        self.assertEqual(len(rows), 1)
        for banned in ("acoustic_read", "direction", "shadow_label",
                       "voice_confidence", "potentiometer"):
            self.assertNotIn(banned, rows[0])

    def test_verdict_row_carries_no_confidence_signal(self):
        from services.star_verdicts import validate_verdict
        row, err = validate_verdict({
            "star_kind": "delivery", "star_device": "pause", "verdict": "keep",
            "direction": "challenge", "acoustic_read": {"potentiometer": 1.0},
        })
        self.assertIsNone(err)
        for banned in ("direction", "acoustic_read"):
            self.assertNotIn(banned, row)

    def test_the_two_surfaces_are_different_endpoints(self):
        """Separation is enforced by routing, not by discipline: the verdict
        endpoints must not be bolted onto the labeling route."""
        with open("routes/v2_routes.py", encoding="utf-8") as fh:
            source = fh.read()
        self.assertIn('"/coach/snippets/<snippet_id>/star-verdict"', source)
        self.assertIn('"/coach/arc/<arc_id>/stars"', source)
        # The labeling route is its own path and must stay that way.
        self.assertIn('"/user/snippets/<snippet_id>/label"', source)


class TestAC9Fence(unittest.TestCase):

    def test_no_student_surface_reads_star_verdicts(self):
        """A verdict is coach->machine. If a student payload ever joined this
        table, the student would be reading the coach's judgment of the advice
        they were given."""
        import subprocess
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", "star_verdict",
             "services/", "routes/"],
            capture_output=True, text=True)
        for line in result.stdout.splitlines():
            path = line.split(":", 1)[0]
            self.assertIn(path, (
                "services/star_verdicts.py", "services/db.py",
                "routes/v2_routes.py",
            ), f"unexpected reader of star_verdicts: {line}")

    def test_the_routes_are_coach_gated(self):
        with open("routes/v2_routes.py", encoding="utf-8") as fh:
            source = fh.read()
        for route in ('"/coach/arc/<arc_id>/stars"',
                      '"/coach/snippets/<snippet_id>/star-verdict"'):
            idx = source.find(route)
            self.assertGreater(idx, 0)
            # The decorator immediately under the route must be the coach gate.
            self.assertIn("@require_admin_or_coach",
                          source[idx:idx + 400])


if __name__ == "__main__":
    unittest.main()
