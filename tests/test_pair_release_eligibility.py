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

import unittest
from datetime import date, datetime, timezone
from unittest import mock

from services import pair_release as pr
from services import pair_release_eligibility as pe

NOW = datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)
WEEK = date(2026, 10, 12)


class _Config:
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


if __name__ == "__main__":
    unittest.main()
