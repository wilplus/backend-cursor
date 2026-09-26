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

SEED_PATH = Path("migrations/the_retention_schedule_is_loaded.sql")
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
    def test_the_registry_still_has_exactly_six_retained_categories(self):
        """A canary. If this changes, the seed and doc 06 both need a look —
        and the failure should be noticed here, not in a purge that silently
        deletes nothing.

        Six since 2026-09-26: `consent_evidence`, the record of a training
        yes and no (founder N10 answer 9, N11 answer 1; doc 11, retention
        schedule v1.1 §2)."""
        self.assertEqual(REQUIRED, {
            "authorization_evidence",
            "consent_evidence",
            "deletion_evidence",
            "financial_evidence",
            "processor_evidence",
            "transparency_evidence",
        })

    #: Deliberately unseeded pending a counsel decision (doc 06 §3). Named
    #: here so "missing" and "open" cannot be confused for one another.
    #: `consent_evidence` waits for retention schedule v1.1 (doc 11), which
    #: counsel checks and the founder signs; it is not in the v1.0 seed.
    OPEN = {"financial_evidence", "consent_evidence"}

    def test_every_retained_category_has_a_rule_except_the_open_one(self):
        seeded_categories = {category for _, category in SEEDED}
        missing = REQUIRED - seeded_categories - self.OPEN
        self.assertEqual(missing, set(), f"no retention rule for: {sorted(missing)}")

    def test_financial_evidence_is_still_open_and_still_blocking(self):
        """It must stay unseeded until counsel answers doc 06 §3.

        The retired justification was Polish accounting law; the service is
        free and takes no payment, so there are no accounting records. Three
        options are open (detach the user reference, bound the period, change
        the disposition) and engineering must not pick one.

        Failing here means someone re-added a default. That is the failure
        worth catching: a plausible-looking period in a published retention
        schedule that nobody approved.
        """
        seeded_categories = {category for _, category in SEEDED}
        self.assertNotIn("financial_evidence", seeded_categories)
        # The CALL, not the word — the file names the retired rule in a
        # comment explaining why it is gone, which is exactly the context a
        # future reader needs.
        self.assertNotIn("('billing-record-5y-v1',", SEED)

    def test_the_file_says_the_purge_stays_blocked(self):
        """Seeding four of five is necessary and not sufficient, because
        resolve_targets is all-or-nothing. If that consequence is not written
        down next to the omission, the next reader sees four green rows and
        concludes the purge works."""
        self.assertIn("all-or-nothing", SEED)
        self.assertIn("deletes NOTHING", SEED)

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


class TheMigrationRegistersExactlyTheSignedSchedule(unittest.TestCase):
    def test_it_is_in_the_manifest_once(self):
        """MIGRATE_ON_BOOT=1 means a manifest entry RUNS in production. It
        runs because the founder decided it (N13, 2026-09-26), once."""
        manifest = Path("migrations/manifest.txt").read_text(encoding="utf-8")
        self.assertEqual(manifest.count("the_retention_schedule_is_loaded.sql"), 1)
        self.assertNotIn("seed_phase1_retention_schedule.sql", manifest)

    def test_it_registers_the_signed_pdf_row_06_names(self):
        """Replaces "not in the manifest": the values it writes into an
        append-only table must be exactly the ones SIGNED-ARTIFACTS.md
        records for the signed schedule, never a placeholder."""
        signed = Path("legal/phase1-2026.1/SIGNED-ARTIFACTS.md").read_text(
            encoding="utf-8")
        row = next(line for line in signed.splitlines()
                   if line.startswith("| 06 |"))
        key = re.search(r"`([^`]+\.pdf)`", row).group(1)
        sha = re.search(r"`([0-9a-f]{64})`", row).group(1)
        self.assertIn(f"v_object_key TEXT := '{key}';", SEED)
        self.assertIn(f"'{sha}';", SEED)
        self.assertNotIn("[[FOUNDER", SEED)

    def test_it_no_ops_rather_than_raising_when_unsigned(self):
        """A raising migration would fail container start under
        MIGRATE_ON_BOOT — an accidental merge would take production down
        rather than merely not seed a table. RAISE NOTICE, then RETURN."""
        gate = SEED.split("IF v_sha256 IS NULL", 1)[1].split("END IF;", 1)[0]
        self.assertIn("RAISE NOTICE", gate)
        self.assertIn("RETURN;", gate)
        self.assertNotIn("RAISE EXCEPTION", gate)

    def test_a_version_conflict_never_stops_production_starting(self):
        """It runs on boot now: a different 1.0 already registered must seed
        nothing and say so, never RAISE and fail container start."""
        branch = SEED.split("RETENTION_SCHEDULE_VERSION_CONFLICT", 1)[0]
        branch = branch.rsplit("ELSIF NOT EXISTS", 1)[1]
        self.assertNotIn("RAISE EXCEPTION", branch)
        self.assertNotIn("RAISE EXCEPTION", SEED)

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
