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

import sys
import types
import unittest

for _m in ("supabase", "sentry_sdk"):
    if _m not in sys.modules:
        sys.modules[_m] = types.ModuleType(_m)
if not hasattr(sys.modules["supabase"], "create_client"):
    sys.modules["supabase"].create_client = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["supabase"].Client = object  # type: ignore[attr-defined]
if not hasattr(sys.modules["sentry_sdk"], "capture_exception"):
    sys.modules["sentry_sdk"].capture_exception = lambda *a, **k: None  # type: ignore[attr-defined]

from services.data_purge_registry import DEPENDENCIES  # noqa: E402

#: Exactly the categories a 'retain' dependency can ask for. Anything else is
#: deleted outright and never consults data_retention_rules.
REQUIRED = {
    str(d.retention_category)
    for d in DEPENDENCIES
    if d.disposition == "retain" and d.retention_category
}


class TheSeedMatchesTheRegistry(unittest.TestCase):
    def test_the_registry_still_has_exactly_six_retained_categories(self):
        """A canary. If this changes, the seed and doc 06 both need a look —
        and the failure should be noticed here, not in a purge that silently
        deletes nothing.

        Six since 2026-09-26: `consent_evidence`, the record of a training
        yes and no (founder N10 answer 9, N11 answer 1; doc 11, retention
        schedule v1.1 §2). Seven since 2026-10-05: `job_evidence`, the
        processing job evidence kept 12 months (founder N48.4 Q15 A;
        retention schedule v1.4 §2)."""
        self.assertEqual(REQUIRED, {
            "authorization_evidence",
            "consent_evidence",
            "deletion_evidence",
            "financial_evidence",
            "job_evidence",
            "processor_evidence",
            "transparency_evidence",
        })

    #: Deliberately unseeded pending a counsel decision (doc 06 §3). Named
    #: here so "missing" and "open" cannot be confused for one another.
    #: `consent_evidence` waits for retention schedule v1.1 (doc 11), which
    #: counsel checks and the founder signs; it is not in the v1.0 seed.
    #: `job_evidence` is seeded by the hand-run v1.4 script once the founder
    #: signs v1.4 (scripts/phase1_retention_rules_v1_4.sql), never by 0381.
    OPEN = {"financial_evidence", "consent_evidence", "job_evidence"}


if __name__ == "__main__":
    unittest.main()
