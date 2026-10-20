"""
STORY    As the founder, I want feedback pairs released for training only
         with a yes, my sentence, a signed manifest and a speaker-disjoint
         split, at most once a week, with failed exports voided and swept,
         so that no unconsented or partial data leaves.
OUTCOME
  O1  Nothing leaves without the founder's sentence for the surface, a
      bucket and a signing key; the reason is given in words.
  O2  With everything in place only pairs with a yes in force leave, under
      one release whose manifest signature verifies, split by the owner's
      speaker, and carrying no user id, coach id or take.
  O3  One file per surface per week: a second run that week writes nothing.
  O4  A voided release's objects are deleted by the sweep and it is marked.
  O5  A failure after the release row voids it and the same weekly run
      sweeps what was put.
PROVES   O1 -> test_nothing_leaves_without_the_sentence_a_bucket_and_a_key
         O2 -> test_only_releasable_pairs_leave_signed_and_split_by_speaker
         O3 -> test_a_second_run_in_the_same_week_writes_nothing
         O4 -> test_a_voided_release_loses_its_object_and_is_marked_purged
         O5 -> test_the_weekly_job_voids_the_failed_release_and_sweeps_it_in_the_same_run
WHY      Founder 2026-09-30 (L1, L2, L5); build plan ML-8, ML-9; 0405, 0455.
"""
from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timezone
from unittest import mock

from services import learning_weekly as lw
from services import pair_release as pr


class _Config:
    PAIR_RELEASE_SURFACES: frozenset = frozenset()
    R2_PAIR_RELEASE_BUCKET = ""
    PAIR_RELEASE_SIGNING_KEY = ""
    PAIR_RELEASE_SIGNING_KEY_ID = "pair-release-key-1"


def _open(*surfaces):
    c = _Config()
    c.PAIR_RELEASE_SURFACES = frozenset(surfaces)
    c.R2_PAIR_RELEASE_BUCKET = "willab-pair-releases"
    c.PAIR_RELEASE_SIGNING_KEY = "k" * 32
    return c


class _Storage:
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.puts: list[str] = []

    def put(self, bucket, key, body, content_type):
        self.puts.append(key)
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
    # F-3: every owner below has a bound speaker unless a test says not.
    SPEAKER_SPLITS = {"p-1": "train", "p-2": "test", "p-9": "validation"}

    def __init__(self, pairs=None, voided=None, grants=None, stopped=(), takes=None,
                 speaker_splits=None, fail=()):
        self.pairs = pairs or []
        self.speaker_splits = dict(self.SPEAKER_SPLITS if speaker_splits is None
                                   else speaker_splits)
        self.releases: list[dict] = []
        self.owners: list[tuple[str, list]] = []
        self.marked: list[tuple[str, list]] = []
        self.voided = voided or []
        self.purged: list[str] = []
        self.refreshed_with = None
        # The release decides every pair afresh (PLF-P5): the yes in force
        # now, whether the owner's service is ending, where the Take lives.
        self.grants = {"p-1": "training-v1", "p-2": "training-v1"} if grants is None else grants
        self.stopped = set(stopped)
        self.takes = takes or {}
        # The writes, in order ("row", "owners", "mark", "void"), and the
        # ones a test makes fail.
        self.calls: list[str] = []
        self.fail = set(fail)

    def list_releasable_pairs(self, surface, limit=5000):
        return [p for p in self.pairs if p["surface"] == surface]

    def list_active_training_grants(self, owners):
        return [{"id": f"grant-{o}", "acquisition_principal_id": o, "consent_policy_version": v}
                for o, v in self.grants.items() if o in owners]

    def phase1_learning_stopped(self, owner):
        return owner in self.stopped

    def list_take_projects(self, takes):
        return {t: p for t, p in self.takes.items() if t in takes}

    def get_speaker_splits_for_principals(self, owners, policy):
        assert policy == "speaker-sha256-80-10-10-v1"
        return {o: self.speaker_splits[o] for o in owners if o in self.speaker_splits}

    def get_pair_release_for_week(self, surface, week_start):
        return next((r for r in self.releases
                     if (r["surface"], r["week_start"]) == (surface, week_start)), None)

    def insert_pair_release(self, **fields):
        # pair_releases_one_per_week: the database refuses a second row,
        # whatever the export read before.
        if any((r["surface"], r["week_start"]) == (fields["surface"], fields["week_start"])
               for r in self.releases):
            raise RuntimeError('duplicate key value violates unique constraint '
                               '"pair_releases_one_per_week"')
        self.calls.append("row")
        row = {"id": f"rel-{len(self.releases) + 1}", "voided_at": None,
               "voided_reason": None, "purged_at": None, **fields}
        self.releases.append(row)
        return row

    def insert_pair_release_owners(self, release_id, owners):
        self.calls.append("owners")
        if "owners" in self.fail:
            raise RuntimeError("owner rows refused")
        self.owners.append((release_id, sorted(set(owners))))
        return len(set(owners))

    def mark_feedback_pairs_released(self, release_id, pair_ids):
        self.calls.append("mark")
        if "mark" in self.fail:
            # 0405: one pair stopped being releasable since it was read.
            raise RuntimeError("PAIR_RELEASE_PAIRS_NOT_RELEASABLE")
        self.marked.append((release_id, list(pair_ids)))
        return len(pair_ids)

    def void_failed_pair_release(self, release_id):
        self.calls.append("void")
        if "void" in self.fail:
            raise RuntimeError("rpc down")
        release = next(r for r in self.releases if r["id"] == release_id)
        if release["voided_at"]:
            return False
        release.update(voided_at="2026-09-30T06:00:00Z", voided_reason="export_failed")
        return True

    def list_voided_unpurged_pair_releases(self):
        return self.voided + [r for r in self.releases
                              if r.get("voided_at") and not r.get("purged_at")]

    def mark_pair_release_purged(self, release_id):
        self.purged.append(release_id)
        for release in self.releases:
            if release["id"] == release_id:
                release["purged_at"] = "2026-09-30T06:00:01Z"

    def refresh_feedback_pair_consent(self, required):
        self.refreshed_with = required
        return {"refreshed": 3, "releasable_waiting": 1, "voided_releases": 0, "pairs_reset": 0}

    def upsert_ledger_snapshot(self, **row):
        self.snapshot = row
        return row


WEEK = date(2026, 9, 28)
NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)


def _export(db, storage, config):
    return pr.export_surface(db, storage, surface="praise_line",
                             week_start=WEEK, config=config, now=NOW)


class GateTests(unittest.TestCase):
    def test_nothing_leaves_without_the_sentence_a_bucket_and_a_key(self):
        no_bucket = _open("praise_line")
        no_bucket.R2_PAIR_RELEASE_BUCKET = ""
        no_key = _open("praise_line")
        no_key.PAIR_RELEASE_SIGNING_KEY = " "
        for config, words in ((_open(), "no founder sentence"),
                              (no_bucket, "no release bucket"),
                              (no_key, "no signing key")):
            with self.subTest(words=words):
                db, storage = _Db(pairs=[_pair(1)]), _Storage()
                out = _export(db, storage, config)
                self.assertEqual(out["exported"], 0)
                self.assertIn(words, out["why"])
                self.assertEqual((db.releases, storage.puts), ([], []))


class ExportTests(unittest.TestCase):
    def _released(self):
        # p-9 has a speaker but no yes in force: nominated, but the release
        # decides afresh.
        db = _Db(pairs=[_pair(1, "p-1"), _pair(2, "p-2"), _pair(3, "p-9")])
        storage = _Storage()
        out = _export(db, storage, _open("praise_line"))
        return db, storage, out

    def test_only_releasable_pairs_leave_signed_and_split_by_speaker(self):
        db, storage, out = self._released()
        self.assertEqual(out["exported"], 2)
        self.assertEqual(len(db.releases), 1)
        self.assertEqual(db.marked, [(out["release_id"], ["pair-1", "pair-2"])])
        key = "pair-releases/praise_line/2026-09-28/pairs.jsonl"
        bucket = "willab-pair-releases"
        lines = [json.loads(line) for line in
                 storage.objects[(bucket, key)].decode().splitlines()]
        self.assertEqual({(r["pair_id"], r["split"]) for r in lines},
                         {("pair-1", "train"), ("pair-2", "test")})
        body = storage.objects[(bucket, key)].decode()
        for leak in ("p-1", "p-2", "p-9", "user_id", "coach", "take"):
            self.assertNotIn(leak, body)
        manifest = json.loads(storage.objects[
            (bucket, key.replace("pairs.jsonl", "manifest.json"))])
        self.assertEqual(manifest["file_sha256"], pr.sha256_text(body))
        signed = {k: v for k, v in manifest.items()
                  if k not in ("manifest_sha256", "signature", "signing_key_id")}
        self.assertEqual(manifest["manifest_sha256"],
                         pr.sha256_text(pr._json(signed)))
        self.assertTrue(pr.verify(manifest["manifest_sha256"],
                                  manifest["signature"], "k" * 32))
        self.assertFalse(pr.verify(manifest["manifest_sha256"],
                                   manifest["signature"], "x" * 32))

    def test_a_second_run_in_the_same_week_writes_nothing(self):
        db, storage, _ = self._released()
        puts = list(storage.puts)
        again = _export(db, storage, _open("praise_line"))
        self.assertEqual(again["exported"], 0)
        self.assertIn("one file per surface per week", again["why"])
        self.assertEqual((len(db.releases), storage.puts), (1, puts))


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


LEDGER = {"ledger_version": "learning-ledger-v1",
          "pairs": {"praise_line": {"total": 1, "unexported": 1}},
          "exercise_jar": {}, "shadow_cues": {}, "unavailable": []}


class FailedExportTests(unittest.TestCase):
    """Anything after the release row fails: the release is voided
    ('export_failed', 0455), so the sweep deletes whatever was put and no
    file is left that no void can reach."""


    def test_the_weekly_job_voids_the_failed_release_and_sweeps_it_in_the_same_run(self):
        db = _Db(pairs=[_pair(1)], fail={"mark"})
        storage = _Storage()
        with mock.patch("services.learning_ledger.ledger", return_value=LEDGER), \
             mock.patch.object(pr, "R2ReleaseStorage", return_value=storage):
            report = lw.run_weekly(db, config=_open("praise_line"),
                                   now=datetime(2026, 9, 30, tzinfo=timezone.utc))
        self.assertTrue(report["exported"][0]["voided"])
        self.assertEqual(report["release_sweep"], {"purged": 1, "failed": []})
        self.assertEqual(storage.objects, {})
        # The voided release is never read back as one this run wrote.
        self.assertEqual(report["verifications"]["read_back"], 0)


if __name__ == "__main__":
    unittest.main()
