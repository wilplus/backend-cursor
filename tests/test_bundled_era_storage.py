"""F4 storage step: which references are ours, and what happens to each.

Pinned without storage or a database:
  * our refs (s3 marker, presigned, our public base, Supabase URL, export
    URI, bare path) are placed exactly; foreign URLs and non-paths are not ours;
  * preview never deletes; execute deletes, then verifies absence, and a file
    still there after delete raises rather than being recorded;
  * a provider error is never absence — it raises;
  * the run records every outcome only in execute mode, exports included.
"""
from __future__ import annotations

import unittest
from unittest import mock

from services import bundled_era_storage as storage
from services.bundled_era_storage import Place, classify, resolve


class ClassifyTests(unittest.TestCase):

    def test_our_references_are_placed(self):
        self.assertEqual(classify("s3://coach-feedback-videos/a/b.webm").places,
                         (Place("r2", "coach-feedback-videos", "a/b.webm"),))
        supa = classify("https://proj.supabase.co/storage/v1/object/public/audio_recordings/u/1.wav")
        self.assertEqual(supa.places, (Place("supabase", "audio_recordings", "u/1.wav"),))
        self.assertEqual(classify("storage://exports/annotation-events/x.jsonl").places,
                         (Place("supabase", "exports", "annotation-events/x.jsonl"),))

    def test_a_bare_path_is_checked_in_both_known_places(self):
        with mock.patch.object(storage, "r2_bucket_name", return_value="coach"):
            found = classify("u/1.wav")
        self.assertEqual(found.kind, "bare")
        self.assertEqual(found.places, (Place("supabase", "audio_recordings", "u/1.wav"),
                                        Place("r2", "coach", "u/1.wav")))

    def test_foreign_urls_and_non_paths_are_not_ours(self):
        with mock.patch.object(storage, "media_key_from_ref", return_value=None):
            self.assertEqual(classify("https://youtube.com/watch?v=1").kind, "not_ours")
        for value in ("", "lbl", "  "):
            self.assertEqual(classify(value).kind, "not_ours")


class ResolveTests(unittest.TestCase):

    def _fakes(self, present):
        state = {"present": set(present), "deleted": []}

        def is_absent(place):
            return place not in state["present"]

        def delete(place):
            state["deleted"].append(place)
            state["present"].discard(place)

        return state, is_absent, delete

    def test_preview_never_deletes(self):
        place = Place("r2", "b", "k/x.webm")
        state, absent, delete = self._fakes([place])
        outcome, _ = resolve("s3://b/k/x.webm", execute=False, is_absent=absent, delete=delete)
        self.assertEqual(outcome, "would_delete")
        self.assertEqual(state["deleted"], [])

    def test_execute_deletes_then_verifies(self):
        place = Place("r2", "b", "k/x.webm")
        state, absent, delete = self._fakes([place])
        self.assertEqual(resolve("s3://b/k/x.webm", execute=True, is_absent=absent,
                                 delete=delete)[0], "deleted")
        self.assertEqual(state["deleted"], [place])

    def test_already_gone_everywhere_is_absent(self):
        _state, absent, delete = self._fakes([])
        self.assertEqual(resolve("u/1.wav", execute=True, is_absent=absent, delete=delete)[0],
                         "absent")

    def test_a_file_still_there_after_delete_raises(self):
        place = Place("r2", "b", "k/x.webm")
        with self.assertRaises(RuntimeError):
            resolve("s3://b/k/x.webm", execute=True,
                    is_absent=lambda p: False, delete=lambda p: None)
        del place

    def test_a_provider_error_is_never_absence(self):
        def broken(_place):
            raise ConnectionError("network")
        with self.assertRaises(ConnectionError):
            resolve("s3://b/k/x.webm", execute=True, is_absent=broken, delete=lambda p: None)


class RunTests(unittest.TestCase):

    class _Db:
        def __init__(self, refs):
            self.refs, self.recorded = refs, []
            self.client = self

        def rpc(self, name, params):
            outer = self

            class Call:
                def execute(self_inner):
                    if name == "bundled_era_erasure_storage_refs_v1":
                        return type("R", (), {"data": outer.refs})()
                    outer.recorded.append(params)
                    return type("R", (), {"data": None})()
            return Call()

    def test_preview_records_nothing(self):
        database = self._Db(["s3://b/a"])
        out = storage.run(database, "snap", execute=False, export_refs=["storage://e/x"],
                          resolver=lambda ref, execute: ("would_delete", ""))
        self.assertEqual(out["tally"], {"would_delete": 2})
        self.assertEqual(database.recorded, [])

    def test_execute_records_every_outcome_exports_included(self):
        database = self._Db(["s3://b/a", "lbl"])
        storage.run(database, "snap", execute=True, export_refs=["storage://e/x"],
                    resolver=lambda ref, execute: ("not_ours" if ref == "lbl" else "deleted", "d"))
        self.assertEqual([r["p_ref"] for r in database.recorded],
                         ["s3://b/a", "lbl", "storage://e/x"])
        self.assertEqual({r["p_snapshot"] for r in database.recorded}, {"snap"})

    def test_an_unreadable_snapshot_stops_everything(self):
        with self.assertRaises(RuntimeError):
            storage.run(self._Db(None), "snap", execute=True, export_refs=[])

    def test_exports_are_listed_under_their_prefix(self):
        refs = storage.annotation_export_refs(
            bucket="exports", prefix="/annotation-events/",
            lister=lambda b, p: [{"name": "b.jsonl"}, {"name": "a.jsonl"}, {"id": 1}])
        self.assertEqual(refs, ["storage://exports/annotation-events/a.jsonl",
                                "storage://exports/annotation-events/b.jsonl"])
        self.assertEqual(storage.annotation_export_refs(bucket=None, prefix="x"), [])


if __name__ == "__main__":
    unittest.main()
