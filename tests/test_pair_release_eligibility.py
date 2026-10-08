"""The release decides every pair afresh (PLF-1.1 "Dataset eligibility";
audit PLF-P5).

The weekly flag only nominates a pair. At the moment of release each
candidate is decided again from the sources: the training yes in force
NOW, the owner's service not ending, the project not leaving and the Take
still there, the texts still a pair. The texts are fingerprinted, the
decision's counts are signed inside the manifest, and a source that cannot
be read stops the surface for the week: nothing leaves on a guess.
"""
from __future__ import annotations

import hashlib
import json
import unittest
from datetime import date, datetime, timezone
from unittest import mock

from services import learning_weekly as lw
from services import pair_release as pr
from services import pair_release_eligibility as pe
from services.db import DatabaseService
from tests.fakes import FakeResult, FakeSupabaseClient

NOW = datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)
WEEK = date(2026, 10, 12)


class _Config:
    MLC2_PAIR_RELEASES_ENABLED = True
    PAIR_RELEASE_SURFACES = frozenset({"praise_line"})
    R2_PAIR_RELEASE_BUCKET = "willab-pair-releases"
    PAIR_RELEASE_SIGNING_KEY = "k" * 32
    PAIR_RELEASE_SIGNING_KEY_ID = "pair-release-key-1"


class _Storage:
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def put(self, bucket, key, body, content_type):
        self.objects[(bucket, key)] = body

    def delete(self, bucket, key):
        self.objects.pop((bucket, key), None)


def _pair(i, owner, take=None, draft=None, final=None, policy="training-only-v0"):
    return {"id": f"pair-{i}", "surface": "praise_line",
            "draft_text": draft if draft is not None else f"draft {i}",
            "final_text": final if final is not None else f"you held the pause {i}",
            "final_kind": "final", "draft_model_version": "m1", "pattern_key": "cue:pause",
            "owner_principal_id": owner, "consent_state": "yes",
            "consent_grant_event_id": "old-grant", "consent_policy_version": policy,
            "take_session_id": take, "created_at": "2026-10-01T10:00:00+00:00"}


class _Db:
    """Every pair arrives flagged releasable by last week's refresh; the
    sources say what is true now."""

    def __init__(self, pairs, *, grants, stopped=(), takes=None, fail=()):
        self.pairs = pairs
        self.grants = grants
        self.stopped = set(stopped)
        self.takes = takes or {}
        self.fail = set(fail)
        self.releases: list[dict] = []
        self.marked: list[tuple[str, list]] = []
        self.release_owners: list[tuple[str, list]] = []
        self.asked_stopped: list[str] = []

    def list_releasable_pairs(self, surface, limit=5000):
        return [p for p in self.pairs if p["surface"] == surface]

    def list_active_training_grants(self, owners):
        if "grants" in self.fail:
            raise RuntimeError("the consent view is down")
        return [{"id": f"grant-{o}", "acquisition_principal_id": o, "consent_policy_version": v}
                for o, v in self.grants.items() if o in owners]

    def phase1_learning_stopped(self, owner):
        if "stopped" in self.fail:
            raise RuntimeError("rpc down")
        self.asked_stopped.append(owner)
        return owner in self.stopped

    def list_take_projects(self, takes):
        return {t: p for t, p in self.takes.items() if t in takes}

    def get_speaker_splits_for_principals(self, owners, policy):
        # Every owner here holds a bound speaker (F-3): the split is the
        # speaker's assignment, read after this decision; not under test here.
        return {o: "train" for o in owners}

    def get_pair_release_for_week(self, surface, week_start):
        return next((r for r in self.releases
                     if (r["surface"], r["week_start"]) == (surface, week_start)), None)

    def insert_pair_release(self, **fields):
        row = {"id": f"rel-{len(self.releases) + 1}", **fields}
        self.releases.append(row)
        return row

    def insert_pair_release_owners(self, release_id, owners):
        self.release_owners.append((release_id, sorted(set(owners))))
        return len(set(owners))

    def mark_feedback_pairs_released(self, release_id, pair_ids):
        self.marked.append((release_id, list(pair_ids)))
        return len(pair_ids)


TAKE_A = "11111111-1111-4111-8111-111111111111"
TAKE_B = "22222222-2222-4222-8222-222222222222"
TAKE_GONE = "33333333-3333-4333-8333-333333333333"


class ReleaseDecisionTests(unittest.TestCase):
    def _export(self, db, leaving=()):
        storage = _Storage()
        with mock.patch.object(pe, "_projects_leaving", return_value=set(leaving)):
            out = pr.export_surface(db, storage, surface="praise_line", week_start=WEEK,
                                    config=_Config(), now=NOW)
        return out, storage

    def test_a_withdrawal_since_the_refresh_keeps_the_pair_out(self):
        # p-2 withdrew after last week's refresh: the flag still says
        # releasable, the view says no yes is in force.
        db = _Db([_pair(1, "p-1"), _pair(2, "p-2")], grants={"p-1": "training-only-v1"})
        out, storage = self._export(db)
        self.assertEqual(out["exported"], 1)
        self.assertEqual(db.marked, [("rel-1", ["pair-1"])])
        self.assertEqual(db.release_owners, [("rel-1", ["p-1"])])
        self.assertEqual(out["eligibility"]["excluded"], {"no_current_yes": 1})
        self.assertEqual(out["waiting"], 1)
        body = storage.objects[("willab-pair-releases",
                                "pair-releases/praise_line/2026-10-12/pairs.jsonl")].decode()
        self.assertNotIn("pair-2", body)
        # Nobody without a yes is even asked about their service.
        self.assertEqual(db.asked_stopped, ["p-1"])

    def test_the_line_carries_the_yes_in_force_now_and_a_fingerprint(self):
        db = _Db([_pair(1, "p-1")], grants={"p-1": "training-only-v1"})
        out, storage = self._export(db)
        key = "pair-releases/praise_line/2026-10-12/pairs.jsonl"
        line = json.loads(storage.objects[("willab-pair-releases", key)].decode().strip())
        self.assertEqual(line["consent_state"], "yes")
        self.assertEqual(line["consent_policy_version"], "training-only-v1")  # not the stamp's v0
        expected = hashlib.sha256(json.dumps(
            {"surface": "praise_line", "draft": "draft 1", "final": "you held the pause 1",
             "final_kind": "final"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(line["item_sha256"], expected)
        self.assertEqual(line["eligibility_decided_at"], NOW.isoformat())
        manifest = json.loads(storage.objects[("willab-pair-releases",
                                               key.replace("pairs.jsonl", "manifest.json"))])
        self.assertEqual(manifest["eligibility"]["decision_version"], pe.DECISION_VERSION)
        self.assertEqual((manifest["eligibility"]["checked"], manifest["eligibility"]["eligible"]), (1, 1))
        self.assertEqual(manifest["consent_policy_versions"], ["training-only-v1"])
        # The decision sits inside what the key signs.
        unsigned = {k: v for k, v in manifest.items()
                    if k not in ("manifest_sha256", "signature", "signing_key_id")}
        self.assertEqual(pr.sha256_text(pr._json(unsigned)), manifest["manifest_sha256"])
        self.assertTrue(pr.verify(manifest["manifest_sha256"], manifest["signature"], "k" * 32))
        self.assertNotIn("p-1", json.dumps(line))
        self.assertNotIn("grant-p-1", json.dumps(line))

    def test_a_service_ending_a_project_leaving_and_a_take_gone_stay_out(self):
        db = _Db([_pair(1, "p-1", take=TAKE_A), _pair(2, "p-2", take=TAKE_B),
                  _pair(3, "p-3", take=TAKE_GONE), _pair(4, "p-4", take=TAKE_A)],
                 grants={o: "training-only-v1" for o in ("p-1", "p-2", "p-3", "p-4")},
                 stopped={"p-4"}, takes={TAKE_A: "proj-a", TAKE_B: "proj-b"})
        out, _storage = self._export(db, leaving={"proj-b"})
        self.assertEqual(db.marked, [("rel-1", ["pair-1"])])
        self.assertEqual(out["eligibility"]["excluded"],
                         {"service_ending": 1, "take_gone": 1, "project_leaving": 1})

    def test_texts_that_are_no_longer_a_pair_stay_out(self):
        db = _Db([_pair(1, "p-1", draft="say it  slowly", final="say it slowly"),
                  _pair(2, "p-1", final="")], grants={"p-1": "training-only-v1"})
        out, storage = self._export(db)
        self.assertEqual(out["exported"], 0)
        self.assertEqual(storage.objects, {})
        self.assertEqual(db.releases, [])
        self.assertIn("nothing eligible at release time", out["why"])
        self.assertIn("2 texts not a pair", out["why"])

    def test_a_source_that_cannot_be_read_stops_the_surface(self):
        for fail in ("grants", "stopped"):
            with self.subTest(fail=fail):
                db = _Db([_pair(1, "p-1")], grants={"p-1": "training-only-v1"}, fail={fail})
                storage = _Storage()
                ledger = {"pairs": {"praise_line": {"total": 1, "unexported": 1}}}
                with mock.patch.object(pe, "_projects_leaving", return_value=set()):
                    rows = lw._export_pairs(db, ledger, _Config(), week_start_day=WEEK,
                                            storage=storage)
                self.assertEqual(rows[0]["exported"], 0)
                self.assertIn("export failed", rows[0]["why"])
                self.assertEqual(storage.objects, {})
                self.assertEqual(db.releases, [])
                self.assertEqual(db.marked, [])

    def test_the_project_check_reads_the_deletion_requests(self):
        proj_a, proj_b, proj_c = (f"{n}{n}{n}{n}{n}{n}{n}{n}-0000-4000-8000-000000000000"
                                  for n in "abc")
        client = FakeSupabaseClient({
            "project_deletion_requests": [{"project_id": proj_b, "state": "pending"}],
            "projects": [{"id": proj_c, "tombstoned_at": "2026-10-02T00:00:00Z"}],
        })
        database = type("D", (), {"client": client})()
        self.assertEqual(pe._projects_leaving(database, [proj_a, proj_b, proj_c]),
                         {proj_b, proj_c})
        self.assertEqual(pe._projects_leaving(database, []), set())


class DatabaseReaderTests(unittest.TestCase):
    def _db(self, client):
        db = DatabaseService.__new__(DatabaseService)
        db.client = client
        return db

    def test_learning_stopped_is_a_boolean_or_an_error(self):
        for answer, expected in ((True, True), (False, False), ([True], True),
                                 ({"phase1_learning_stopped_v1": False}, False)):
            client = FakeSupabaseClient(rpc_rows={})
            client.rpc("phase1_learning_stopped_v1")  # create the query object
            client.rpcs["phase1_learning_stopped_v1"]._rows_or_fn = (
                lambda _q, a=answer: FakeResult(a, count=0))
            self.assertIs(self._db(client).phase1_learning_stopped("p-1"), expected)
        unknown = FakeSupabaseClient(rpc_rows={})
        unknown.rpc("phase1_learning_stopped_v1")
        unknown.rpcs["phase1_learning_stopped_v1"]._rows_or_fn = (
            lambda _q: FakeResult(None, count=0))
        with self.assertRaises(RuntimeError):
            self._db(unknown).phase1_learning_stopped("p-1")

    def test_the_grants_are_read_from_the_view_the_refresh_reads(self):
        client = FakeSupabaseClient({"training_consent_active_grants": [
            {"id": "g1", "acquisition_principal_id": "p-1", "consent_policy_version": "v1"}]})
        rows = self._db(client).list_active_training_grants(["p-1", "p-1", ""])
        self.assertEqual(rows[0]["acquisition_principal_id"], "p-1")
        calls = client.tables["training_consent_active_grants"].calls
        self.assertIn(("in_", ("acquisition_principal_id", ["p-1"]), {}), calls)


if __name__ == "__main__":
    unittest.main()
