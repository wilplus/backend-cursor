"""
STORY    As the founder, I want every measurement stamped with a hash of the
         detector that made it, and the rating write never broken by the
         stamp, so that I can tell if fillers or other definitions changed
         under my data.
OUTCOME
  O1  The hash ignores reordering and moves when a word is added.
  O2  The live filler lexicon hashes to a seed a migration records.
  O3  Unknown (no recorded hash, unknown detector) is SUSPECT; an unreadable
      detector_version table stamps nothing (UNSTAMPED); a match stamps ok.
  O4  A missing label_revision table never fails a rating write.
PROVES   O1 -> test_the_hash_ignores_order_and_moves_when_a_word_is_added
         O2 -> test_the_live_filler_lexicon_matches_a_recorded_seed
         O3 -> test_unknown_is_suspect, test_the_stamp_on_a_measurement_row
         O4 -> test_missing_table_never_unsucceeds_the_rating
WHY      "If fillers are corrupted all my data goes nuts" (founder, 2026-08-10).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest import mock

from services import provenance, provenance_check
from tests.fakes import FakeSupabaseClient, swap_attr

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
SEED_ROW = re.compile(
    r"INSERT INTO public\.detector_version.*?VALUES\s*\(\s*'(\w+)'.*?'([0-9a-f]{64})'",
    re.S)


class TestTheHash(unittest.TestCase):

    def test_the_hash_ignores_order_and_moves_when_a_word_is_added(self):
        base = {"lexicon": ["um", "uh", "so"], "match": "whole_word_ci"}
        reordered = {"match": "whole_word_ci", "lexicon": ["so", "um", "uh"]}
        grown = {"lexicon": ["um", "uh", "so", "actually"], "match": "whole_word_ci"}
        self.assertEqual(provenance.definition_hash(base),
                         provenance.definition_hash(reordered))
        self.assertNotEqual(provenance.definition_hash(base),
                            provenance.definition_hash(grown))

    def test_the_live_filler_lexicon_matches_a_recorded_seed(self):
        seeds = {h for path in MIGRATIONS.glob("*.sql")
                 for detector, h in SEED_ROW.findall(path.read_text())
                 if detector == provenance.FILLERS}
        self.assertTrue(seeds, "no fillers seed found in migrations/")
        live = provenance.definition_hash(provenance.live_definition(provenance.FILLERS))
        self.assertIn(live, seeds, "DEFAULT_FILLERS changed without a new "
                      "detector_version row: mint the next version")

    def test_unknown_is_suspect(self):
        live = provenance.definition_hash(provenance.live_definition(provenance.FILLERS))
        self.assertEqual(provenance.check(provenance.FILLERS, live)[0], provenance.OK)
        self.assertEqual(provenance.check(provenance.FILLERS, None)[0], provenance.SUSPECT)
        self.assertEqual(provenance.check(provenance.FILLERS, "0" * 64)[0],
                         provenance.SUSPECT)
        self.assertEqual(provenance.check("pause_ms", live)[0], provenance.SUSPECT)


class TestTheStamp(unittest.TestCase):

    def setUp(self):
        from services.db import db
        self.db = db
        provenance_check.reset_cache()
        self.addCleanup(provenance_check.reset_cache)

    def _stamp_with(self, client):
        with swap_attr(self.db, "client", client):
            return provenance_check.stamp("fillers")

    def test_the_stamp_on_a_measurement_row(self):
        missing = mock.MagicMock()
        missing.table.side_effect = Exception('relation "detector_version" does not exist')
        self.assertEqual(self._stamp_with(missing), {})

        live = provenance.definition_hash(provenance.live_definition(provenance.FILLERS))
        found = mock.MagicMock()
        chain = found.table.return_value
        for step in ("select", "eq", "is_", "order", "limit"):
            getattr(chain, step).return_value = chain
        chain.execute.return_value = mock.Mock(
            data=[{"version": "fillers-v1", "definition_hash": live}])
        self.assertEqual(self._stamp_with(found),
                         {"provenance": "ok", "detector_version": "fillers-v1"})
        self.assertEqual(provenance_check.stamp("pauses"), {})


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
