"""Doors 1 and 2, the machinery with both doors closed (founder 2026-09-30,
L1, L2, L5; build plan ML-8, ML-9).

Pins:
  * a pair is stamped at write with its owner's consent; a surface outside
    counsel's list is releasable without a yes; no principal is unknown and
    not releasable; every surface needs the yes today;
  * nothing leaves while door 2 is closed, or open without the founder's
    sentence for the surface, or without a bucket and a key; the reason is
    words;
  * with everything in place only releasable pairs leave, once, under one
    release, with a manifest whose sha256 is signed and verifiable, split
    speaker-disjoint, carrying no user id, coach id or take;
  * a voided release's object is deleted by the sweep and the row marked;
  * the weekly job refreshes first, exports, sweeps, and reports each.
"""
from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timezone
from unittest import mock

from services import pair_consent as pc
from services import pair_release as pr
from services import learning_weekly as lw


class _Config:
    MLC2_PAIR_RELEASES_ENABLED = False
    PAIR_RELEASE_SURFACES: frozenset = frozenset()
    R2_PAIR_RELEASE_BUCKET = ""
    PAIR_RELEASE_SIGNING_KEY = ""
    PAIR_RELEASE_SIGNING_KEY_ID = "pair-release-key-1"


def _open(*surfaces):
    c = _Config()
    c.MLC2_PAIR_RELEASES_ENABLED = True
    c.PAIR_RELEASE_SURFACES = frozenset(surfaces)
    c.R2_PAIR_RELEASE_BUCKET = "willab-pair-releases"
    c.PAIR_RELEASE_SIGNING_KEY = "k" * 32
    return c


class _Storage:
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def put(self, bucket, key, body, content_type):
        self.objects[(bucket, key)] = body

    def delete(self, bucket, key):
        self.objects.pop((bucket, key), None)


def _pair(i, owner="p-1", state="yes"):
    return {"id": f"pair-{i}", "surface": "praise_line", "draft_text": f"draft {i}",
            "final_text": f"final {i}", "final_kind": "final", "draft_model_version": "m1",
            "pattern_key": "cue:volume", "owner_principal_id": owner, "consent_state": state,
            "consent_grant_event_id": "g1", "consent_policy_version": "training-v1",
            "created_at": "2026-09-30T10:00:00+00:00"}


class _Db:
    def __init__(self, pairs=None, voided=None):
        self.pairs = pairs or []
        self.releases: list[dict] = []
        self.owners: list[tuple[str, list]] = []
        self.marked: list[tuple[str, list]] = []
        self.voided = voided or []
        self.purged: list[str] = []
        self.refreshed_with = None

    def list_releasable_pairs(self, surface, limit=5000):
        return [p for p in self.pairs if p["surface"] == surface]

    def insert_pair_release(self, **fields):
        row = {"id": f"rel-{len(self.releases) + 1}", **fields}
        self.releases.append(row)
        return row

    def insert_pair_release_owners(self, release_id, owners):
        self.owners.append((release_id, sorted(set(owners))))
        return len(set(owners))

    def mark_feedback_pairs_released(self, release_id, pair_ids):
        self.marked.append((release_id, list(pair_ids)))
        return len(pair_ids)

    def list_voided_unpurged_pair_releases(self):
        return self.voided

    def mark_pair_release_purged(self, release_id):
        self.purged.append(release_id)

    def refresh_feedback_pair_consent(self, required):
        self.refreshed_with = required
        return {"refreshed": 3, "releasable_waiting": 1, "voided_releases": 0, "pairs_reset": 0}

    def upsert_ledger_snapshot(self, **row):
        self.snapshot = row
        return row


class StampTests(unittest.TestCase):
    def test_every_surface_needs_the_yes_until_counsel_says_otherwise(self):
        self.assertEqual(pc.CONSENT_REQUIRED_SURFACES, frozenset((
            "praise_line", "clearer_version", "exercise_script",
            # The coach's own words (Phase 7, C5-a) need the yes like the rest.
            "coach_moment_line", "coach_take_word")))

    def test_a_yes_makes_the_pair_releasable_and_names_its_grant(self):
        db = mock.Mock()
        db.get_owner_principal_for_user.return_value = {"id": "p-1"}
        db.get_mlc2_training_consent_status.return_value = {
            "active": True, "grant_event_id": "g1", "consent_policy_version": "training-v1"}
        out = pc.stamp(db, surface="praise_line", owner_user_id="u1")
        self.assertEqual(out, {"owner_principal_id": "p-1", "consent_state": "yes",
                               "consent_grant_event_id": "g1",
                               "consent_policy_version": "training-v1", "releasable": True})

    def test_no_yes_no_principal_and_no_need(self):
        db = mock.Mock()
        db.get_owner_principal_for_user.return_value = {"id": "p-1"}
        db.get_mlc2_training_consent_status.return_value = {"active": False}
        self.assertEqual(pc.stamp(db, surface="praise_line", owner_user_id="u1")["consent_state"], "no")
        self.assertFalse(pc.stamp(db, surface="praise_line", owner_user_id="u1")["releasable"])
        db.get_owner_principal_for_user.return_value = None
        out = pc.stamp(db, surface="praise_line", owner_user_id="u1")
        self.assertEqual((out["consent_state"], out["releasable"], out["owner_principal_id"]), ("unknown", False, None))
        with mock.patch.object(pc, "CONSENT_REQUIRED_SURFACES", frozenset(("praise_line",))):
            out = pc.stamp(db, surface="exercise_script", owner_user_id=None)
        self.assertEqual((out["consent_state"], out["releasable"]), ("not_needed", True))

    def test_the_stamp_rides_the_pair_write(self):
        from services.feedback_pairs import record_pair
        db = mock.Mock()
        db.get_owner_principal_for_user.return_value = {"id": "p-1"}
        db.get_mlc2_training_consent_status.return_value = {"active": False}
        db.insert_feedback_pair.return_value = {"id": "x", "surface": "praise_line"}
        db.create_admin_annotation_event.return_value = None
        record_pair(db, surface="praise_line", draft="a b", final="c d", coach_id="coach",
                    owner_user_id="u1", request_id="r1")
        kw = db.insert_feedback_pair.call_args.kwargs
        self.assertEqual((kw["owner_principal_id"], kw["consent_state"], kw["releasable"]), ("p-1", "no", False))

    def test_the_refresh_passes_counsels_list_and_names_a_fault(self):
        db = _Db()
        self.assertEqual(pc.refresh(db)["refreshed"], 3)
        self.assertEqual(db.refreshed_with, sorted(pc.CONSENT_REQUIRED_SURFACES))
        broken = mock.Mock()
        broken.refresh_feedback_pair_consent.side_effect = RuntimeError("down")
        self.assertIn("unavailable", pc.refresh(broken))
        self.assertIn("unavailable", pc.refresh(object()))


class DoorTests(unittest.TestCase):
    def test_nothing_leaves_while_the_door_is_closed_and_the_reason_is_words(self):
        self.assertEqual(pr.authorised_surfaces(_Config()), frozenset())
        self.assertIn("door 2 closed", pr.why_not(_Config(), "praise_line"))
        c = _open()
        self.assertIn("no founder sentence", pr.why_not(c, "praise_line"))
        c = _open("praise_line")
        c.R2_PAIR_RELEASE_BUCKET = ""
        self.assertIn("no release bucket", pr.why_not(c, "praise_line"))
        c = _open("praise_line")
        c.PAIR_RELEASE_SIGNING_KEY = ""
        self.assertIn("no signing key", pr.why_not(c, "praise_line"))
        self.assertIsNone(pr.why_not(_open("praise_line"), "praise_line"))
        self.assertEqual(pr.authorised_surfaces(_open("praise_line", "score")), frozenset(("praise_line",)))

    def test_a_closed_surface_writes_nothing_even_with_pairs_waiting(self):
        db = _Db(pairs=[_pair(1)])
        storage = _Storage()
        out = pr.export_surface(db, storage, surface="praise_line", week_start=date(2026, 9, 28), config=_open())
        self.assertEqual((out["exported"], out["waiting"]), (0, 1))
        self.assertEqual(storage.objects, {})
        self.assertEqual(db.releases, [])

    def test_the_doors_in_config_are_what_the_founder_said(self):
        """Door 1 opened 2026-10-01 ("open door 1"); door 2 opened the same
        day for exercise_script ("open door 2 for surface exercise_script",
        N16) and then for praise_line and clearer_version by their own
        sentences (C4, N18). The retired DPO dataset lane stays dark; the
        Phase 7 coach-word surfaces have no sentence yet."""
        from config import Config
        self.assertTrue(Config.MLC2_TRAINING_SWITCH_ENABLED)
        self.assertTrue(Config.MLC2_PAIR_RELEASES_ENABLED)
        three = frozenset({"exercise_script", "praise_line", "clearer_version"})
        self.assertEqual(Config.PAIR_RELEASE_SURFACES, three)
        self.assertFalse(Config.MLC2_DATASET_RELEASES_ENABLED)
        self.assertEqual(pr.authorised_surfaces(Config), three)
        for surface in sorted(three):
            reason = pr.why_not(Config, surface)
            # With the bucket and key on the service the answer is None; in
            # CI they are unset, so the only reason left is one of those two.
            self.assertTrue(reason is None or "no release bucket" in reason
                            or "no signing key" in reason, (surface, reason))
        for held in ("coach_moment_line", "coach_take_word"):
            self.assertIn("no founder sentence", pr.why_not(Config, held) or "")
        self.assertFalse(Config.MLC2_TRAINING_ENABLED)
        self.assertFalse(Config.MLC2_PROMOTION_ENABLED)


class ExportTests(unittest.TestCase):
    def test_only_releasable_pairs_leave_once_under_one_signed_release(self):
        db = _Db(pairs=[_pair(1, owner="p-1"), _pair(2, owner="p-2")])
        storage = _Storage()
        c = _open("praise_line")
        now = datetime(2026, 9, 30, 6, tzinfo=timezone.utc)
        out = pr.export_surface(db, storage, surface="praise_line", week_start=date(2026, 9, 28), config=c, now=now)
        self.assertEqual(out["exported"], 2)
        self.assertEqual(out["release_id"], "rel-1")
        key = "pair-releases/praise_line/2026-09-28/pairs.jsonl"
        body = storage.objects[("willab-pair-releases", key)].decode()
        lines = [json.loads(line) for line in body.strip().split("\n")]
        self.assertEqual([line["pair_id"] for line in lines], ["pair-1", "pair-2"])
        for line in lines:
            self.assertEqual(set(line), {"pair_id", "surface", "pattern_key", "draft", "final", "final_kind",
                                         "draft_model_version", "split", "owner_split_key", "consent_state",
                                         "consent_policy_version", "recorded_at"})
            self.assertIn(line["split"], ("train", "validation", "test"))
            self.assertNotIn("p-1", json.dumps(line))
        manifest = json.loads(storage.objects[("willab-pair-releases", key.replace("pairs.jsonl", "manifest.json"))])
        self.assertEqual(manifest["file_sha256"], pr.sha256_text(body))
        self.assertEqual(manifest["item_count"], 2)
        self.assertEqual(sum(manifest["split_counts"].values()), 2)
        self.assertEqual(manifest["consent_policy_versions"], ["training-v1"])
        self.assertEqual(manifest["owner_count"], 2)
        self.assertTrue(pr.verify(manifest["manifest_sha256"], manifest["signature"], c.PAIR_RELEASE_SIGNING_KEY))
        self.assertFalse(pr.verify(manifest["manifest_sha256"], manifest["signature"], "other"))
        release = db.releases[0]
        self.assertEqual((release["surface"], release["week_start"], release["item_count"]), ("praise_line", "2026-09-28", 2))
        self.assertEqual(release["manifest_sha256"], manifest["manifest_sha256"])
        self.assertEqual(db.owners, [("rel-1", ["p-1", "p-2"])])
        self.assertEqual(db.marked, [("rel-1", ["pair-1", "pair-2"])])

    def test_the_split_is_by_owner_and_stable(self):
        a = pr.lines_for([_pair(1, owner="p-9"), _pair(2, owner="p-9")])
        self.assertEqual(a[0]["split"], a[1]["split"])
        self.assertEqual(a[0]["owner_split_key"], a[1]["owner_split_key"])
        self.assertEqual(pr.lines_for([_pair(3, owner="p-9")])[0]["split"], a[0]["split"])

    def test_nothing_waiting_is_said_not_written(self):
        db = _Db(pairs=[])
        storage = _Storage()
        out = pr.export_surface(db, storage, surface="praise_line", week_start=date(2026, 9, 28), config=_open("praise_line"))
        self.assertEqual(out["why"], "nothing releasable waiting")
        self.assertEqual(storage.objects, {})


class SweepTests(unittest.TestCase):
    def test_a_voided_release_loses_its_object_and_is_marked_purged(self):
        storage = _Storage()
        key = "pair-releases/praise_line/2026-09-21/pairs.jsonl"
        storage.objects[("b", key)] = b"x"
        storage.objects[("b", key.replace("pairs.jsonl", "manifest.json"))] = b"m"
        db = _Db(voided=[{"id": "rel-7", "storage_bucket": "b", "storage_key": key}])
        out = pr.sweep_voided(db, storage)
        self.assertEqual(out["purged"], 1)
        self.assertEqual(storage.objects, {})
        self.assertEqual(db.purged, ["rel-7"])

    def test_a_failed_delete_is_named_and_retried_next_week(self):
        class _Broken(_Storage):
            def delete(self, bucket, key):
                raise RuntimeError("bucket away")
        db = _Db(voided=[{"id": "rel-8", "storage_bucket": "b", "storage_key": "pair-releases/x/y/pairs.jsonl"}])
        out = pr.sweep_voided(db, _Broken())
        self.assertEqual((out["purged"], out["failed"]), (0, ["rel-8"]))
        self.assertEqual(db.purged, [])


class WeeklyTests(unittest.TestCase):
    def test_the_job_refreshes_exports_and_sweeps_and_reports_each(self):
        db = _Db(pairs=[_pair(1)])
        ledger = {"ledger_version": "learning-ledger-v1",
                  "pairs": {"praise_line": {"total": 1, "unexported": 1}},
                  "exercise_jar": {}, "shadow_cues": {}, "doors": {}, "unavailable": []}
        with mock.patch("services.learning_ledger.ledger", return_value=ledger), \
             mock.patch.object(lw, "_export_pairs", wraps=lw._export_pairs) as export:
            report = lw.run_weekly(db, config=_Config(), now=datetime(2026, 9, 30, tzinfo=timezone.utc))
        self.assertEqual(report["consent_refresh"]["refreshed"], 3)
        self.assertEqual(report["release_sweep"]["purged"], 0)
        self.assertIn("door 2 closed", report["exported"][0]["why"])
        self.assertEqual(db.releases, [])
        self.assertTrue(export.called)
        self.assertEqual(db.snapshot["snapshot"]["doors_pass"]["consent_refresh"]["refreshed"], 3)


if __name__ == "__main__":
    unittest.main()
