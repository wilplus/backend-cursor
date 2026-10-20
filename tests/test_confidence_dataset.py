"""
STORY    As the founder, I want each speaker's clips kept in one split, so
         that the confidence model is never tested on voices it trained on.
OUTCOME
  O1  All of one speaker's clips fall in one partition.
  O2  The split check reports no leakage.
PROVES   O1, O2 -> ManifestTests::test_every_clip_from_one_speaker_stays_together
"""
from __future__ import annotations

import unittest

from services import confidence_dataset as dataset


def _row(snippet_id, speaker, **extra):
    return {"snippet_id": snippet_id, "speaker_id": speaker, **extra}


class ManifestTests(unittest.TestCase):

    def setUp(self):
        self.rows = [
            _row("a1", "a", language="en", device="phone"),
            _row("a2", "a", language="en", device="phone"),
            _row("b1", "b", language="pl", device="laptop"),
            _row("c1", "c", language="de", device="studio"),
            _row("d1", "d", language="en", device="phone"),
            _row("e1", "e", language="pl", device="phone"),
            _row("f1", "f", language="de", device="laptop"),
            _row("g1", "g", language="en", device="studio"),
            _row("h1", "h", language="pl", device="phone"),
            _row("i1", "i", language="de", device="phone"),
        ]

    def _manifest(self):
        return dataset.create_manifest(
            self.rows, seed="release-seed", release_id="confidence-2026-08",
        )


    def test_every_clip_from_one_speaker_stays_together(self):
        partitions = dataset.partition_rows(self.rows, self._manifest())
        locations = {
            partition
            for partition, rows in partitions.items()
            if any(row["speaker_id"] == "a" for row in rows)
        }
        self.assertEqual(len(locations), 1)
        self.assertTrue(dataset.split_audit(partitions)["leakage_free"])


if __name__ == "__main__":
    unittest.main()
