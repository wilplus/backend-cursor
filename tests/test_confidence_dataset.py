"""Speaker-disjoint split contract for the Confident Voice corpus."""
from __future__ import annotations

import unittest

from services import confidence_dataset as dataset


def _row(snippet_id, speaker, **extra):
    return {"snippet_id": snippet_id, "speaker_id": speaker, **extra}


class SpeakerIdentityTests(unittest.TestCase):

    def test_immutable_identity_precedes_owner_and_label(self):
        row = {"speaker_id": "speaker-a", "owner_id": "owner-b",
               "speaker_label": "Person C"}
        self.assertEqual(dataset.speaker_key(row), "speaker:speaker-a")

    def test_authenticated_and_guest_owner_ids_are_supported(self):
        self.assertEqual(dataset.speaker_key({"user_id": "u1"}), "owner:u1")
        self.assertEqual(dataset.speaker_key({"guest_owner_id": "g1"}),
                         "owner:g1")

    def test_import_labels_are_normalized_conservatively(self):
        one = {"source_metadata": {"speaker_label": "  Ada   LOVELACE "}}
        two = {"speaker_label": "ada lovelace"}
        self.assertEqual(dataset.speaker_key(one), dataset.speaker_key(two))

    def test_session_and_project_are_never_guessed_as_speaker(self):
        self.assertIsNone(dataset.speaker_key({
            "session_id": "s1", "project_id": "p1", "filename": "voice.wav",
        }))


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

    def test_manifest_is_deterministic_and_versioned(self):
        self.assertEqual(self._manifest(), self._manifest())
        manifest = self._manifest()
        self.assertEqual(manifest["policy_version"],
                         dataset.POLICY_VERSION)
        self.assertEqual(manifest["release_id"], "confidence-2026-08")

    def test_every_clip_from_one_speaker_stays_together(self):
        partitions = dataset.partition_rows(self.rows, self._manifest())
        locations = {
            partition
            for partition, rows in partitions.items()
            if any(row["speaker_id"] == "a" for row in rows)
        }
        self.assertEqual(len(locations), 1)
        self.assertTrue(dataset.split_audit(partitions)["leakage_free"])

    def test_unknown_speaker_fails_closed(self):
        with self.assertRaisesRegex(dataset.DatasetSplitError,
                                    "stable speaker identity"):
            dataset.create_manifest(
                [{"snippet_id": "x", "session_id": "s"}],
                seed="s", release_id="r",
            )

    def test_unreleased_speaker_cannot_sneak_into_export(self):
        with self.assertRaisesRegex(dataset.DatasetSplitError,
                                    "absent from release"):
            dataset.partition_rows(
                self.rows + [_row("new1", "new")], self._manifest(),
            )

    def test_extension_never_changes_or_grows_test(self):
        before = self._manifest()
        after = dataset.extend_manifest(before, [_row("new1", "new")])
        for key, partition in before["assignments"].items():
            self.assertEqual(after["assignments"][key], partition)
        self.assertEqual(after["frozen_test_speakers"],
                         before["frozen_test_speakers"])
        self.assertNotEqual(after["assignments"]["speaker:new"], "test")

    def test_tampered_test_freeze_is_rejected(self):
        manifest = self._manifest()
        manifest["frozen_test_speakers"] = []
        if any(value == "test" for value in manifest["assignments"].values()):
            with self.assertRaisesRegex(dataset.DatasetSplitError, "freeze"):
                dataset.partition_rows(self.rows, manifest)

    def test_duplicate_snippet_is_rejected(self):
        rows = self.rows + [_row("a1", "a")]
        manifest = dataset.create_manifest(
            rows, seed="s", release_id="r",
        )
        with self.assertRaisesRegex(dataset.DatasetSplitError,
                                    "duplicate snippet"):
            dataset.partition_rows(rows, manifest)

    def test_audit_reports_required_balance_dimensions(self):
        partitions = dataset.partition_rows(self.rows, self._manifest())
        audit = dataset.split_audit(partitions)
        for partition in dataset.PARTITIONS:
            dimensions = audit["partitions"][partition]["by_dimension"]
            self.assertEqual(set(dimensions), {
                "language", "device", "source", "acoustic_region",
            })

    def test_audit_detects_speaker_leakage_in_external_partitions(self):
        audit = dataset.split_audit({
            "train": [_row("a1", "a")],
            "validation": [_row("a2", "a")],
            "test": [],
        })
        self.assertFalse(audit["leakage_free"])
        self.assertEqual(audit["speaker_overlap"][0]["speaker_key"],
                         "speaker:a")


if __name__ == "__main__":
    unittest.main()
