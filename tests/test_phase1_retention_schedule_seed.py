"""The retention seed must cover the categories the orchestrator ACTUALLY uses.

THE BUG THIS EXISTS TO PREVENT (2026-09-17). Doc 06 §2 was written as a
seed-ready table of twelve rules whose `evidence_category` column holds values
like `r2_object`, `transcript`, `cache` and `coach_packet`. Those are
`data_purge_targets.target_kind` values. The lookup at
`services/data_purge.py:231` matches `data_retention_rules.evidence_category`
against `PurgeDependency.retention_category`, which is a different and
non-overlapping vocabulary of five strings.

Seeding the document verbatim would have produced twelve active rows that
resolve nothing. Every retain-disposition dependency would still land on
`RETENTION_RULE_UNRESOLVED`, and because `resolve_targets` is all-or-nothing
("Unknown inventory means zero deletion", data_purge.py:720) a full-account
purge would still delete nothing — while the table looked populated and the
control version named something real. A silent failure dressed as a fix.

So these tests compare the seed against the registry itself rather than against
the document. A sixth `retention_category` added by a future dependency fails
here instead of quietly reintroducing the outage.

Run: python3 -m unittest tests.test_phase1_retention_schedule_seed
"""
from __future__ import annotations

import re
import sys
import types
import unittest
from pathlib import Path

for _m in ("supabase", "sentry_sdk"):
    if _m not in sys.modules:
        sys.modules[_m] = types.ModuleType(_m)
if not hasattr(sys.modules["supabase"], "create_client"):
    sys.modules["supabase"].create_client = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["supabase"].Client = object  # type: ignore[attr-defined]
if not hasattr(sys.modules["sentry_sdk"], "capture_exception"):
    sys.modules["sentry_sdk"].capture_exception = lambda *a, **k: None  # type: ignore[attr-defined]

from services.data_purge_registry import DEPENDENCIES  # noqa: E402

SEED_PATH = Path("migrations/pending/seed_phase1_retention_schedule.sql")
SEED = SEED_PATH.read_text(encoding="utf-8")

#: Exactly the categories a 'retain' dependency can ask for. Anything else is
#: deleted outright and never consults data_retention_rules.
REQUIRED = {
    str(d.retention_category)
    for d in DEPENDENCIES
    if d.disposition == "retain" and d.retention_category
}

#: ('rule-code', 'evidence_category') pairs the seed inserts.
SEEDED = set(re.findall(
    r"\('([a-z0-9-]+)',\s*'([a-z_]+)',", SEED,
))


class TheSeedMatchesTheRegistry(unittest.TestCase):
    def test_the_registry_still_has_exactly_five_retained_categories(self):
        """A canary. If this changes, the seed and doc 06 both need a look —
        and the failure should be noticed here, not in a purge that silently
        deletes nothing."""
        self.assertEqual(REQUIRED, {
            "authorization_evidence",
            "deletion_evidence",
            "financial_evidence",
            "processor_evidence",
            "transparency_evidence",
        })

    def test_every_retained_category_has_a_rule(self):
        seeded_categories = {category for _, category in SEEDED}
        missing = REQUIRED - seeded_categories
        self.assertEqual(missing, set(), f"no retention rule for: {sorted(missing)}")

    def test_no_rule_is_seeded_for_a_category_nothing_can_ask_for(self):
        """A rule that resolves nothing is not harmless: it makes the table
        look covered. Doc 06's twelve target_kind rows are exactly this."""
        seeded_categories = {category for _, category in SEEDED}
        extra = seeded_categories - REQUIRED
        self.assertEqual(extra, set(), f"unreachable rule(s) for: {sorted(extra)}")

    def test_the_deliberate_omissions_stay_omitted(self):
        """dataset_lineage, model_lineage and unknown get NO rule, on purpose.
        A catch-all converts 'we do not know what this is' into 'we have
        handled it'."""
        for banned in ("dataset_lineage", "model_lineage", "unknown"):
            self.assertNotIn(
                f"'{banned}'", SEED,
                f"{banned} must reach review_required, not a catch-all rule",
            )

    def test_every_rule_code_is_unique(self):
        codes = [code for code, _ in SEEDED]
        self.assertEqual(len(codes), len(set(codes)))


class TheMigrationIsSafeToSitUnmerged(unittest.TestCase):
    def test_it_is_not_in_the_manifest(self):
        """MIGRATE_ON_BOOT=1 means a manifest entry RUNS in production. This
        one cannot run until the schedule PDF is signed."""
        manifest = Path("migrations/manifest.txt").read_text(encoding="utf-8")
        self.assertNotIn("seed_phase1_retention_schedule.sql", manifest)

    def test_it_no_ops_rather_than_raising_when_unsigned(self):
        """A raising migration would fail container start under
        MIGRATE_ON_BOOT — an accidental merge would take production down
        rather than merely not seed a table. RAISE NOTICE, then RETURN."""
        gate = SEED.split("IF v_sha256 IS NULL", 1)[1].split("END IF;", 1)[0]
        self.assertIn("RAISE NOTICE", gate)
        self.assertIn("RETURN;", gate)
        self.assertNotIn("RAISE EXCEPTION", gate)

    def test_it_degrades_when_the_boundary_is_absent(self):
        self.assertIn("to_regclass('public.data_retention_rules')", SEED)

    def test_it_never_updates_or_deletes_evidence(self):
        """processing_legal_artifacts carries an append-only trigger that
        rejects UPDATE and DELETE even from the owner."""
        for forbidden in ("UPDATE public.processing_legal_artifacts",
                          "DELETE FROM public.processing_legal_artifacts",
                          "DROP TABLE"):
            self.assertNotIn(forbidden, SEED)

    def test_re_application_is_a_no_op(self):
        self.assertIn("ON CONFLICT (rule_code) DO NOTHING", SEED)


if __name__ == "__main__":
    unittest.main()
