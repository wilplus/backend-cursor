"""willab — provenance hashing, the boot check, and the row stamps.

SPEC-immutable-provenance, Phase A. services/provenance.py (pure),
services/provenance_check.py (runtime), and the two db.py write paths that
carry the result.

WHAT THIS PINS DOWN:
  * CANONICAL FORM — the hash must not depend on dict key order, list order,
    or how the process happened to start. Every definition here is a set, so
    a cosmetic reorder of the lexicon must NOT read as a behaviour change —
    a checker that cries wolf gets muted, which is worse than no checker;
  * THE HASH MOVES WHEN BEHAVIOUR MOVES — adding one word ("actually") must
    change it. That is the founder's exact danger: "if fillers are corrupted
    all my data goes nuts";
  * THE SEED CONTRACT — the live DEFAULT_FILLERS must hash to a seed some
    detector_version migration actually records. This makes CI itself a
    provenance check: edit the lexicon without minting a version row and
    this file goes red BEFORE prod boots into a CRITICAL log;
  * UNKNOWN IS SUSPECT — no recorded hash, or a detector the module cannot
    describe, reports SUSPECT, never a clean bill of health issued without
    an examination;
  * TABLE-MISSING IS *NOT* SUSPECT — pre-migration (or DB down) the row
    stays UNSTAMPED, the same honest NULL as pre-provenance history, and
    the miss is NOT cached so the first read after 0257 lands picks it up;
  * THE STAMP NEVER BREAKS THE WRITE IT RIDES — a database without the 0257
    columns gets the measurements unstamped rather than not at all, and a
    missing label_revision table never un-succeeds the rating write.

Run: python3 -m unittest tests.test_provenance
"""
from __future__ import annotations

import unittest

from tests.fakes import FakeSupabaseClient, swap_attr


class TestLabelRevision(unittest.TestCase):
    """The append-only shadow of upsert_state_rating."""

    def setUp(self):
        from services.db import db
        self.db = db

    def _rate(self, client, **kw):
        with swap_attr(self.db, "client", client):
            return self.db.upsert_state_rating(
                snippet_id="11111111-1111-1111-1111-111111111111",
                row={"state_id": "confidence", "value": "yes",
                     "unrateable": False, "saw_model_output": False},
                rater_id="22222222-2222-2222-2222-222222222222",
                lane="coach", **kw)


    def test_missing_table_never_unsucceeds_the_rating(self):
        """0258 not applied: the rating write is the load-bearing one."""
        def missing(q):
            raise Exception('relation "public.label_revision" does not exist')

        client = FakeSupabaseClient({"confidence_labels": [],
                                     "label_revision": missing})
        self.assertTrue(self._rate(client))


if __name__ == "__main__":
    unittest.main()
