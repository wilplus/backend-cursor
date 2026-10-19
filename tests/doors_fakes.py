"""Doors 3 and 4, the machinery (founder 2026-09-30,
L6 to L9; counsel 2026-10-01; build plan ML-10, ML-11, ML-12).

Pins:
  * a pair surface's golden moment shows the passage and the coach's final,
    never the draft; a judgement keeps both texts; the evaluation reads only
    a sealed set that is still what was sealed;
  * the evaluation scores candidate against baseline on the founder's
    yes-moments, needs twenty of them, and fails a candidate that
    reproduces an 8-word window of a withdrawn speaker's text;
  * nothing trains without the founder's sentence, a key, a sealed set, or 200 trainable pairs; with everything
    in place the file is the serving prompt, split by owner, uploaded, the
    job started, the pairs marked once, the owners recorded;
  * the poll finishes a finished job, deletes its files at the provider and
    evaluates a succeeded one; the withdrawal sweep cancels a running job
    and deletes the files;
  * nothing promotes on a surface the founder did not name; a promotion
    needs a passed report under the current prompt lock; a kill returns the
    stock model.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from services import golden_set as gs

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)


class _Config:
    TRAINING_SURFACES: frozenset = frozenset()
    PROMOTION_SURFACES: frozenset = frozenset()
    PAIR_RELEASE_SURFACES: frozenset = frozenset()
    OPENAI_API_KEY = ""
    OPENAI_FINE_TUNE_BASE_MODEL = "gpt-4.1-mini-2025-04-14"
    R2_PAIR_RELEASE_BUCKET = ""
    PAIR_RELEASE_SIGNING_KEY = ""
    PAIR_RELEASE_SIGNING_KEY_ID = "k"


def _open3(*surfaces):
    c = _Config()
    c.TRAINING_SURFACES = frozenset(surfaces)
    c.OPENAI_API_KEY = "sk-test"
    return c


def _open4(*surfaces):
    c = _Config()
    c.PROMOTION_SURFACES = frozenset(surfaces)
    return c


def _pair(i, owner="o-1", surface="praise_line", **over):
    row = {"id": f"pair-{i}", "surface": surface, "draft_text": f"draft {i}",
           "final_text": f"you held the pause before the number {i}", "final_kind": "final",
           "passage_text": f"so the figure was about {i} million and we held it there",
           "prompt_context": {"kind": "praise", "pattern_key": "cue:pause"},
           "owner_principal_id": owner, "releasable": True, "release_id": "rel-1",
           "trained_run_id": None, "created_at": "2026-10-01T00:00:00+00:00"}
    row.update(over)
    return row


class _Provider:
    def __init__(self, status="running"):
        self.uploads: list[tuple[str, bytes]] = []
        self.jobs: list[dict] = []
        self.deleted: list[str] = []
        self.cancelled: list[str] = []
        self.status = status
        self.model = "ft:gpt-4.1-mini:willab:praise:abc"

    def upload(self, name, body):
        self.uploads.append((name, body))
        return f"file-{len(self.uploads)}"

    def create_job(self, **kw):
        self.jobs.append(kw)
        return {"id": f"job-{len(self.jobs)}", "status": "queued"}

    def get_job(self, job_id):
        return {"id": job_id, "status": self.status, "fine_tuned_model": self.model,
                "error": {"message": "boom"} if self.status == "failed" else None}

    def cancel_job(self, job_id):
        self.cancelled.append(job_id)

    def delete_file(self, file_id):
        self.deleted.append(file_id)


class _Db:
    def __init__(self, pairs=None):
        self.pairs = pairs or []
        self.judgements: list[dict] = []
        self.sealed: dict[str, dict] = {}
        self.runs: list[dict] = []
        self.owners: list[tuple[str, list]] = []
        self.marked: list[tuple[str, list]] = []
        self.reports: list[dict] = []
        self.promotions: list[dict] = []
        self.runtime: dict[str, str] = {}
        self.withdrawn_runs: list[dict] = []
        # The yes in force now, per owner (None: everyone's yes stands).
        self.active: set | None = None

    # golden
    def list_golden_pair_pool(self, surface, limit=500):
        return [p for p in self.pairs if p["surface"] == surface]

    def get_feedback_pair(self, pair_id):
        return next((p for p in self.pairs if p["id"] == pair_id), None)

    def list_golden_judgements(self, *, surface, judge=None):
        return [j for j in self.judgements if j["surface"] == surface
                and (judge is None or j["judge_email"] == judge)]

    def insert_golden_judgement(self, **fields):
        self.judgements.append(fields)
        return fields

    def get_golden_set(self, surface):
        return self.sealed.get(surface)

    def seal_golden_set(self, **fields):
        self.sealed[fields["surface"]] = fields
        return fields

    # training
    def list_trainable_pairs(self, surface, limit=5000):
        return [p for p in self.pairs if p["surface"] == surface]

    #: rel-1 left before F-3: its manifest has no split_source, so its
    #: pairs train under the owner-principal hash they were released under.
    release_manifests: dict = {"rel-1": {"split_strategy": "speaker-sha256-80-10-10-v1"}}
    speaker_assignments: dict = {}

    def get_pair_release_manifests(self, release_ids):
        return {r: self.release_manifests[r] for r in release_ids
                if r in self.release_manifests}

    def get_speaker_splits_for_principals(self, owners, policy):
        return {o: self.speaker_assignments[o] for o in owners
                if o in self.speaker_assignments}

    def insert_fine_tune_run(self, **fields):
        row = {"id": f"run-{len(self.runs) + 1}", "files_deleted_at": None, **fields}
        self.runs.append(row)
        return row

    def insert_fine_tune_run_owners(self, run_id, owners):
        self.owners.append((run_id, list(owners)))
        return len(owners)

    def mark_feedback_pairs_trained(self, run_id, pair_ids):
        self.marked.append((run_id, list(pair_ids)))
        for p in self.pairs:
            if p["id"] in pair_ids:
                p["trained_run_id"] = run_id
        return len(pair_ids)

    def update_fine_tune_run(self, run_id, **fields):
        for r in self.runs:
            if r["id"] == run_id:
                r.update(fields)

    def list_fine_tune_runs(self, status=None, limit=20):
        return [r for r in self.runs if status is None or r.get("status") == status]

    def list_fine_tune_runs_with_withdrawn_owner(self):
        return self.withdrawn_runs

    def list_trained_pairs(self, run_id):
        return [p for p in self.pairs if p.get("trained_run_id") == run_id]

    def list_active_training_grants(self, owners):
        return [{"id": f"g-{o}", "acquisition_principal_id": o, "consent_policy_version": "v1"}
                for o in owners if self.active is None or o in self.active]

    def get_fine_tune_run(self, run_id):
        return next((r for r in self.runs if r["id"] == run_id), None)

    def get_latest_evaluation_report(self, run_id):
        mine = [r for r in self.reports if r.get("run_id") == run_id]
        return mine[-1] if mine else None

    def insert_evaluation_report(self, **fields):
        row = {"id": f"rep-{len(self.reports) + 1}", **fields}
        self.reports.append(row)
        return row

    def get_evaluation_report(self, report_id):
        return next((r for r in self.reports if r["id"] == report_id), None)

    # promotion
    def get_runtime_config(self, key):
        return self.runtime.get(key)

    def promote_runtime_surface_model(self, *, key, value, updated_by=None, metadata=None):
        self.runtime[key] = value
        return {"key": key, "value": value}

    def insert_model_promotion(self, **fields):
        row = {"id": f"promo-{len(self.promotions) + 1}", "killed_at": None, **fields}
        self.promotions.append(row)
        return row

    def kill_model_promotions(self, *, surface, killed_by, kill_reason, killed_at):
        for p in self.promotions:
            if p["surface"] == surface and not p["killed_at"]:
                p.update(killed_at=killed_at, killed_by=killed_by, kill_reason=kill_reason)


def _judged_db(n_yes=25, n_no=25):
    db = _Db(pairs=[_pair(i, owner=f"o-{i % 7}") for i in range(n_yes + n_no)])
    for i in range(n_yes + n_no):
        gs.record(db, surface="praise_line", judge="founder@w.com",
                  body={"snippet_id": f"pair-{i}", "value": "yes" if i < n_yes else "no"})
    return db


if __name__ == "__main__":
    unittest.main()
