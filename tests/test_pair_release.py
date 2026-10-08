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
  * one file per surface per week: a week that has a release, standing or
    voided, is refused before anything is written; the row and its owners
    are written before any object, so a fire racing another is refused at
    its own row and puts nothing (0455);
  * anything after the row that fails voids the release ('export_failed')
    and the sweep deletes what was put; a void that fails too is named;
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
    def __init__(self, fail_on=None, log=None):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.puts: list[str] = []
        self.fail_on = fail_on      # the object name whose put fails
        self.log = log              # the order the export writes in, with the database's

    def put(self, bucket, key, body, content_type):
        self.puts.append(key)
        if self.log is not None:
            self.log.append(f"put {key.rsplit('/', 1)[-1]}")
        if self.fail_on and key.endswith(self.fail_on):
            raise RuntimeError("bucket away")
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
        sentences (C4, N18). Doors 3 and 4 opened 2026-10-08 for the same
        three surfaces (founder: "turn it all ON"). The retired DPO dataset
        lane stays dark; the Phase 7 coach-word surfaces have no sentence
        yet."""
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
        self.assertTrue(Config.MLC2_TRAINING_ENABLED)
        self.assertTrue(Config.MLC2_PROMOTION_ENABLED)
        self.assertEqual(Config.TRAINING_SURFACES, three)
        self.assertEqual(Config.PROMOTION_SURFACES, three)


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
                                         "consent_policy_version", "recorded_at",
                                         # PLF-P5: the release-time decision, per item.
                                         "item_sha256", "eligibility_decided_at"})
            self.assertEqual(line["eligibility_decided_at"], now.isoformat())
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

    def test_the_split_is_the_owners_speaker_assignment_not_the_principal_hash(self):
        """F-3: the release reads ml_speaker_split_assignments through the
        owner's bound speaker; the owner-principal hash no longer decides."""
        from services.dataset_releases import speaker_split
        owner = next(f"p-x{i}" for i in range(1000) if speaker_split(f"p-x{i}")[0] == "train")
        db = _Db(pairs=[_pair(1, owner=owner)], speaker_splits={owner: "test"},
                 grants={owner: "training-v1"})
        storage = _Storage()
        out = pr.export_surface(db, storage, surface="praise_line", week_start=date(2026, 9, 28),
                                config=_open("praise_line"))
        self.assertEqual(out["exported"], 1)
        body = storage.objects[("willab-pair-releases", "pair-releases/praise_line/2026-09-28/pairs.jsonl")]
        self.assertEqual(json.loads(body.decode().strip())["split"], "test")
        manifest = json.loads(storage.objects[("willab-pair-releases",
                                               "pair-releases/praise_line/2026-09-28/manifest.json")])
        self.assertEqual(manifest["split_counts"], {"train": 0, "validation": 0, "test": 1})
        self.assertEqual(manifest["split_source"], "speaker_assignment")

    def test_a_pair_whose_owner_has_no_speaker_waits_and_the_job_says_why(self):
        db = _Db(pairs=[_pair(1, owner="p-1"), _pair(2, owner="p-unbound")],
                 grants={"p-1": "training-v1", "p-unbound": "training-v1"})
        storage = _Storage()
        out = pr.export_surface(db, storage, surface="praise_line", week_start=date(2026, 9, 28),
                                config=_open("praise_line"))
        self.assertEqual((out["exported"], out["waiting"]), (1, 1))
        self.assertIn("speaker binding", out["why_waiting"])
        # The signed manifest says how many eligible pairs waited.
        manifest = db.releases[0]["manifest"]
        self.assertEqual(manifest["eligibility"]["waiting_for_speaker"], 1)
        self.assertEqual(manifest["eligibility"]["eligible"], 2)
        self.assertEqual(manifest["item_count"], 1)
        self.assertEqual(db.marked, [("rel-1", ["pair-1"])])
        self.assertEqual(db.owners, [("rel-1", ["p-1"])])

    def test_when_no_owner_is_bound_nothing_is_written(self):
        db = _Db(pairs=[_pair(1, owner="p-1")], speaker_splits={})
        storage = _Storage()
        out = pr.export_surface(db, storage, surface="praise_line", week_start=date(2026, 9, 28),
                                config=_open("praise_line"))
        self.assertEqual((out["exported"], out["waiting"]), (0, 1))
        self.assertIn("speaker binding", out["why"])
        self.assertEqual((storage.objects, db.releases, db.marked), ({}, [], []))

    def test_an_unreadable_speaker_table_reads_as_nobody_bound(self):
        db = _Db(pairs=[_pair(1, owner="p-1")])

        def broken(owners, policy):
            raise RuntimeError("table away")
        db.get_speaker_splits_for_principals = broken
        out = pr.export_surface(db, _Storage(), surface="praise_line", week_start=date(2026, 9, 28),
                                config=_open("praise_line"))
        self.assertEqual(out["exported"], 0)
        self.assertEqual(db.releases, [])

    def test_door_3_reads_the_same_split_door_2_released_under(self):
        from services import model_training as mt
        pair = {**_pair(1, owner="p-2"), "passage_text": "the passage as spoken", "releasable": True}
        released = pr.lines_for([pair], {"p-2": "test"})[0]["split"]
        trained = mt.split_examples([pair], {"p-2": "test"})
        self.assertEqual(released, "test")
        self.assertEqual((trained["held_out"], trained["train"], trained["validation"]), (1, [], []))

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


WEEK = date(2026, 9, 28)
FILE = ("willab-pair-releases", "pair-releases/praise_line/2026-09-28/pairs.jsonl")
MANIFEST = ("willab-pair-releases", "pair-releases/praise_line/2026-09-28/manifest.json")
LEDGER = {"ledger_version": "learning-ledger-v1",
          "pairs": {"praise_line": {"total": 1, "unexported": 1}},
          "exercise_jar": {}, "shadow_cues": {}, "doors": {}, "unavailable": []}


def _export(db, storage):
    return pr.export_surface(db, storage, surface="praise_line", week_start=WEEK,
                             config=_open("praise_line"))


class OneFilePerWeekTests(unittest.TestCase):
    """The cron may fire twice in one ISO week (services/learning_weekly.py).
    A second fire never puts the week's key again over the standing
    release's objects: it is refused before it writes anything."""

    def test_a_second_fire_in_the_same_week_writes_nothing_and_says_why(self):
        db = _Db(pairs=[_pair(1)])
        storage = _Storage()
        self.assertEqual(_export(db, storage)["exported"], 1)
        standing = dict(storage.objects)
        db.pairs = [_pair(2)]     # a pair became releasable between the fires
        out = _export(db, storage)
        self.assertEqual((out["exported"], out["waiting"]), (0, 1))
        self.assertEqual(out["why"], "this week's release already stands: one file per "
                                     "surface per week, so nothing was written and the "
                                     "pairs wait for next week")
        # Never read back as a release this run wrote.
        self.assertNotIn("release_id", out)
        self.assertEqual(storage.objects, standing)
        self.assertEqual(storage.puts, [FILE[1], MANIFEST[1]])
        self.assertEqual(len(db.releases), 1)
        self.assertEqual(db.marked, [("rel-1", ["pair-1"])])
        self.assertEqual(db.calls, ["row", "owners", "mark"])

    def test_a_voided_week_is_refused_too_and_names_its_reason(self):
        db = _Db(pairs=[_pair(1)])
        db.releases.append({"id": "rel-0", "surface": "praise_line", "week_start": "2026-09-28",
                            "voided_at": "2026-09-29T06:00:00Z",
                            "voided_reason": "consent_withdrawn", "purged_at": None})
        storage = _Storage()
        out = _export(db, storage)
        self.assertEqual(out["exported"], 0)
        self.assertIn("this week's release was voided (consent_withdrawn)", out["why"])
        self.assertEqual((storage.puts, db.calls, db.marked), ([], [], []))

    def test_the_week_is_read_before_any_source_is(self):
        db = _Db(pairs=[_pair(1)])
        db.releases.append({"id": "rel-0", "surface": "praise_line", "week_start": "2026-09-28",
                            "voided_at": None, "voided_reason": None, "purged_at": None})
        db.list_active_training_grants = mock.Mock(side_effect=AssertionError("decided"))
        self.assertIn("already stands", _export(db, _Storage())["why"])

    def test_a_fire_racing_another_is_refused_at_its_own_row_and_puts_nothing(self):
        # Both fires read the week as free; the row is written before any
        # object, so pair_releases_one_per_week refuses the later fire first.
        db = _Db(pairs=[_pair(1)])
        storage = _Storage()
        _export(db, storage)
        standing = dict(storage.objects)
        db.pairs = [_pair(2)]
        db.get_pair_release_for_week = lambda surface, week_start: None
        rows = lw._export_pairs(db, LEDGER, _open("praise_line"), week_start_day=WEEK,
                                storage=storage)
        self.assertEqual(rows[0]["exported"], 0)
        self.assertIn("export failed", rows[0]["why"])
        self.assertIn("pair_releases_one_per_week", rows[0]["why"])
        self.assertEqual(storage.objects, standing)
        self.assertEqual(storage.puts, [FILE[1], MANIFEST[1]])
        self.assertEqual(db.marked, [("rel-1", ["pair-1"])])
        # The standing release is not this fire's to void.
        self.assertNotIn("void", db.calls)
        self.assertIsNone(db.releases[0]["voided_at"])


class FailedExportTests(unittest.TestCase):
    """Anything after the release row fails: the release is voided
    ('export_failed', 0455), so the sweep deletes whatever was put and no
    file is left that no void can reach."""

    def test_the_row_and_its_owners_come_before_any_object_and_the_pairs_last(self):
        db = _Db(pairs=[_pair(1)])
        _export(db, _Storage(log=db.calls))
        self.assertEqual(db.calls, ["row", "owners", "put pairs.jsonl", "put manifest.json",
                                    "mark"])

    def test_a_mark_that_refuses_voids_the_release_and_the_sweep_deletes_its_objects(self):
        # A pair stopped being releasable between the read and the mark (a
        # withdrawal, a deletion request), and 0405's mark refuses the set:
        # no pair points at the release, so only this void reaches it.
        db = _Db(pairs=[_pair(1), _pair(2, owner="p-2")], fail={"mark"})
        storage = _Storage()
        out = _export(db, storage)
        self.assertEqual((out["exported"], out["waiting"]), (0, 2))
        self.assertEqual((out["failed_release_id"], out["voided"]), ("rel-1", True))
        self.assertEqual(out["why"], "export failed: PAIR_RELEASE_PAIRS_NOT_RELEASABLE; its "
                                     "release is voided and the sweep deletes what was written")
        self.assertNotIn("release_id", out)
        self.assertEqual(db.releases[0]["voided_reason"], "export_failed")
        self.assertEqual(db.calls[-1], "void")
        self.assertEqual(set(storage.objects), {FILE, MANIFEST})
        self.assertEqual(pr.sweep_voided(db, storage), {"purged": 1, "failed": []})
        self.assertEqual(storage.objects, {})
        self.assertEqual(db.purged, ["rel-1"])

    def test_a_failed_put_voids_the_release_and_the_file_put_before_it_goes_too(self):
        db = _Db(pairs=[_pair(1)])
        storage = _Storage(fail_on="manifest.json")
        out = _export(db, storage)
        self.assertTrue(out["voided"])
        self.assertIn("bucket away", out["why"])
        self.assertEqual(set(storage.objects), {FILE})
        self.assertEqual(db.marked, [])
        pr.sweep_voided(db, storage)
        self.assertEqual(storage.objects, {})

    def test_a_refused_owner_list_voids_the_release_before_anything_is_put(self):
        db = _Db(pairs=[_pair(1)], fail={"owners"})
        storage = _Storage()
        out = _export(db, storage)
        self.assertTrue(out["voided"])
        self.assertEqual((storage.puts, db.marked), ([], []))
        self.assertEqual(db.releases[0]["voided_reason"], "export_failed")

    def test_a_void_that_fails_too_is_named_and_says_which_release_stands(self):
        db = _Db(pairs=[_pair(1)], fail={"mark", "void"})
        out = _export(db, _Storage())
        self.assertEqual((out["failed_release_id"], out["voided"]), ("rel-1", False))
        self.assertIn("could not be voided (rpc down) and still stands", out["why"])
        self.assertIn("void_failed_pair_release_v1", out["why"])
        self.assertIsNone(db.releases[0]["voided_at"])

    def test_a_row_that_comes_back_without_an_id_puts_nothing(self):
        db = _Db(pairs=[_pair(1)])
        db.insert_pair_release = lambda **fields: None
        storage = _Storage()
        with self.assertRaises(RuntimeError):
            _export(db, storage)
        self.assertEqual((storage.puts, db.marked), ([], []))

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


class FoundationHealthTests(unittest.TestCase):
    """F-9: the weekly job reads get_mlc2_foundation_health_v1 and keeps it,
    aggregate only, beside the doors; a failure is named, never fatal."""

    HEALTH = {"generated_at": "2026-10-05T06:00:00Z", "pending_outbox_count": 2,
              "failed_outbox_count": 0, "oldest_pending_outbox_at": None,
              "unresolved_principal_count": 40, "unverified_object_count": 3,
              "pending_purge_count": 0, "learning_surface_count": 8,
              "dataset_creation_enabled": False, "training_enabled": False,
              "promotion_enabled": False}

    def test_the_weekly_row_carries_the_foundation_health(self):
        db = _Db(pairs=[])
        db.get_mlc2_foundation_health = lambda: dict(self.HEALTH)
        ledger = {"ledger_version": "learning-ledger-v1", "pairs": {},
                  "exercise_jar": {}, "shadow_cues": {}, "doors": {}, "unavailable": []}
        with mock.patch("services.learning_ledger.ledger", return_value=ledger):
            report = lw.run_weekly(db, config=_Config(), now=datetime(2026, 10, 5, tzinfo=timezone.utc))
        health = report["foundation_health"]
        self.assertEqual(health["pending_outbox_count"], 2)
        self.assertEqual(health["unverified_object_count"], 3)
        self.assertTrue(health["learning_capabilities_closed"])
        self.assertNotIn("learning_surface_count", health)
        self.assertEqual(db.snapshot["snapshot"]["foundation_health"], health)

    def test_an_open_capability_is_visible(self):
        db = _Db()
        db.get_mlc2_foundation_health = lambda: {**self.HEALTH, "training_enabled": True}
        self.assertFalse(lw.foundation_health(db)["learning_capabilities_closed"])

    def test_a_failure_is_named_and_never_stops_the_job(self):
        db = _Db()

        def broken():
            raise RuntimeError("rpc down")
        db.get_mlc2_foundation_health = broken
        self.assertIn("rpc down", lw.foundation_health(db)["unavailable"])
        self.assertIn("unavailable", lw.foundation_health(object()))


if __name__ == "__main__":
    unittest.main()
