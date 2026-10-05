"""Doors 3 and 4, the machinery with both doors closed (founder 2026-09-30,
L6 to L9; counsel 2026-10-01; build plan ML-10, ML-11, ML-12).

Pins:
  * a pair surface's golden moment shows the passage and the coach's final,
    never the draft; a judgement keeps both texts; the evaluation reads only
    a sealed set that is still what was sealed;
  * the evaluation scores candidate against baseline on the founder's
    yes-moments, needs twenty of them, and fails a candidate that
    reproduces an 8-word window of a withdrawn speaker's text;
  * nothing trains while door 3 is closed, or open without the founder's
    sentence, a key, a sealed set, or 200 trainable pairs; with everything
    in place the file is the serving prompt, split by owner, uploaded, the
    job started, the pairs marked once, the owners recorded;
  * the poll finishes a finished job, deletes its files at the provider and
    evaluates a succeeded one; the withdrawal sweep cancels a running job
    and deletes the files;
  * nothing promotes while door 4 is closed; a promotion needs a passed
    report under the current prompt lock; a kill returns the stock model
    with the door shut.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from unittest import mock

from services import golden_evaluation as ge
from services import golden_set as gs
from services import learning_weekly as lw
from services import model_promotion as mp
from services import model_training as mt

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)


class _Config:
    MLC2_TRAINING_ENABLED = False
    MLC2_PROMOTION_ENABLED = False
    MLC2_PAIR_RELEASES_ENABLED = False
    MLC2_TRAINING_SWITCH_ENABLED = False
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
    c.MLC2_TRAINING_ENABLED = True
    c.TRAINING_SURFACES = frozenset(surfaces)
    c.OPENAI_API_KEY = "sk-test"
    return c


def _open4(*surfaces):
    c = _Config()
    c.MLC2_PROMOTION_ENABLED = True
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


def _compose_echo(**kw):
    """A compose that returns the passage's first words: a stand-in model."""
    return {"text": " ".join(kw["passage"].split()[:6])}


class GoldenPairTests(unittest.TestCase):
    def test_the_pair_moment_shows_passage_and_final_never_the_draft(self):
        db = _Db(pairs=[_pair(1)])
        moment = gs.next_moment(db, surface="praise_line", judge="f")
        self.assertEqual(moment["snippet_id"], "pair-1")
        self.assertEqual(moment["final"], "you held the pause before the number 1")
        self.assertNotIn("draft", json.dumps(moment))
        self.assertIsNone(moment["audio_url"])

    def test_a_judgement_keeps_the_texts_and_takes_three_answers(self):
        db = _Db(pairs=[_pair(1)])
        with self.assertRaises(gs.GoldenRefusal):
            gs.record(db, surface="praise_line", judge="f", body={"snippet_id": "pair-1", "value": "in_between"})
        gs.record(db, surface="praise_line", judge="f", body={"snippet_id": "pair-1", "value": "yes"})
        row = db.judgements[0]
        self.assertEqual(row["passage"], _pair(1)["passage_text"])
        self.assertEqual(row["reference"], _pair(1)["final_text"])
        self.assertEqual(row["owner_principal_id"], "o-1")
        self.assertEqual(gs.counts(db, surface="praise_line")["kind"], "pair")

    def test_the_evaluation_reads_only_a_sealed_set_that_is_still_sealed(self):
        db = _judged_db()
        with self.assertRaises(gs.GoldenRefusal) as unsealed:
            gs.sealed_rows(db, surface="praise_line")
        self.assertEqual(unsealed.exception.code, "GOLDEN_SET_UNSEALED")
        gs.seal(db, surface="praise_line", judge="founder@w.com")
        self.assertEqual(len(gs.sealed_rows(db, surface="praise_line")), 50)
        db.judgements.pop()  # erasure took a moment out
        with self.assertRaises(gs.GoldenRefusal) as changed:
            gs.sealed_rows(db, surface="praise_line")
        self.assertEqual(changed.exception.code, "GOLDEN_SET_CHANGED")
        self.assertFalse(gs.counts(db, surface="praise_line")["sealed_intact"])
        # And the founder may judge another moment and re-seal at fifty.
        db.pairs.append(_pair(50))
        gs.record(db, surface="praise_line", judge="founder@w.com",
                  body={"snippet_id": "pair-50", "value": "no"})
        gs.seal(db, surface="praise_line", judge="founder@w.com")
        self.assertEqual(len(gs.sealed_rows(db, surface="praise_line")), 50)
        self.assertTrue(gs.counts(db, surface="praise_line")["sealed_intact"])


class EvaluationTests(unittest.TestCase):
    def test_token_f1_and_windows(self):
        self.assertEqual(ge.token_f1("a b c", "a b c"), 1.0)
        self.assertEqual(ge.token_f1("", "a"), 0.0)
        corpus = ge.windows("one two three four five six seven eight nine")
        self.assertTrue(ge.reproduces("say one two three four five six seven eight now", corpus))
        self.assertFalse(ge.reproduces("one two three", corpus))

    def test_refuses_an_unsealed_set_and_too_few_references(self):
        db = _judged_db()
        with self.assertRaises(gs.GoldenRefusal):
            ge.evaluate(db, surface="praise_line", candidate_model="ft:x", baseline_model="stock",
                        compose=_compose_echo)
        few = _judged_db(n_yes=5, n_no=45)
        gs.seal(few, surface="praise_line", judge="founder@w.com")
        with self.assertRaises(ge.EvaluationRefusal) as refused:
            ge.evaluate(few, surface="praise_line", candidate_model="ft:x", baseline_model="stock",
                        compose=_compose_echo)
        self.assertEqual(refused.exception.code, "TOO_FEW_REFERENCES")

    def test_scores_candidate_against_baseline_and_stores_the_report(self):
        db = _judged_db()
        gs.seal(db, surface="praise_line", judge="founder@w.com")

        def compose(**kw):
            from services.ml_surface_contracts import active_evaluation_override
            if active_evaluation_override("praise_line"):
                i = kw["passage"].split()[5]
                return {"text": f"you held the pause before the number {i}"}
            return {"text": "nice"}
        out = ge.evaluate(db, surface="praise_line", candidate_model="ft:x",
                          baseline_model="stock", compose=compose, now=NOW)
        report = out["report"]
        self.assertEqual(report["references"], 25)
        self.assertEqual(report["candidate_mean_f1"], 1.0)
        self.assertLess(report["baseline_mean_f1"], 0.3)
        self.assertTrue(report["ahead"] and report["passed"])
        self.assertEqual(db.reports[0]["passed"], True)
        self.assertEqual(len(db.reports[0]["golden_sha256"]), 64)

    def test_a_candidate_that_reproduces_a_withdrawn_text_fails(self):
        db = _judged_db()
        gs.seal(db, surface="praise_line", judge="founder@w.com")
        withdrawn = "the quick brown fox jumps over the lazy dog again"

        def compose(**kw):
            from services.ml_surface_contracts import active_evaluation_override
            return {"text": withdrawn if active_evaluation_override("praise_line") else "nice"}
        out = ge.evaluate(db, surface="praise_line", candidate_model="ft:x", baseline_model="stock",
                          compose=compose, withdrawn_texts=[withdrawn], now=NOW)
        self.assertFalse(out["passed"])
        self.assertEqual(out["report"]["regurgitation"]["hits"], 25)


class TrainingTests(unittest.TestCase):
    def test_nothing_trains_while_door_3_is_closed_and_the_reasons_are_words(self):
        db = _Db(pairs=[_pair(i) for i in range(300)])
        out = mt.start_run(db, _Provider(), surface="praise_line", config=_Config(), now=NOW)
        self.assertFalse(out["started"])
        self.assertIn("door 3 closed", out["why"])
        half = _open3("clearer_version")
        self.assertIn("no founder sentence", mt.start_run(db, _Provider(), surface="praise_line", config=half, now=NOW)["why"])
        keyless = _open3("praise_line")
        keyless.OPENAI_API_KEY = ""
        self.assertIn("no OpenAI key", mt.why_not(keyless, "praise_line"))

    def test_an_open_door_still_needs_a_sealed_set_and_two_hundred_pairs(self):
        db = _Db(pairs=[_pair(i) for i in range(300)])
        out = mt.start_run(db, _Provider(), surface="praise_line", config=_open3("praise_line"), now=NOW)
        self.assertFalse(out["started"])
        self.assertIn("not sealed", out["why"])
        db = _judged_db()
        gs.seal(db, surface="praise_line", judge="founder@w.com")
        out = mt.start_run(db, _Provider(), surface="praise_line", config=_open3("praise_line"), now=NOW)
        self.assertFalse(out["started"])
        self.assertIn("of 200", out["why"])

    def test_a_run_uploads_the_serving_prompt_split_by_owner_and_marks_pairs_once(self):
        db = _judged_db()
        gs.seal(db, surface="praise_line", judge="founder@w.com")
        db.pairs = [_pair(i, owner=f"o-{i % 40}") for i in range(260)]
        db.pairs[0]["releasable"] = False            # withdrawn since the release
        db.pairs[1]["passage_text"] = None           # no prompt
        provider = _Provider()
        out = mt.start_run(db, provider, surface="praise_line", config=_open3("praise_line"), now=NOW)
        self.assertTrue(out["started"], out)
        self.assertEqual(len(provider.jobs), 1)
        self.assertEqual(provider.jobs[0]["base_model"], "gpt-4.1-mini-2025-04-14")
        name, body = provider.uploads[0]
        first = json.loads(body.decode().splitlines()[0])
        roles = [m["role"] for m in first["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant"])
        self.assertIn("The passage, as spoken:", first["messages"][1]["content"])
        run_id, marked = db.marked[0]
        self.assertNotIn("pair-0", marked)
        self.assertNotIn("pair-1", marked)
        self.assertEqual(out["trained"], len(marked))
        self.assertEqual(db.runs[0]["item_count"], len(marked))
        self.assertGreater(out["held_out"], 0)
        self.assertEqual(db.owners[0][0], run_id)
        # Once: a second start finds nothing trainable.
        again = mt.start_run(db, provider, surface="praise_line", config=_open3("praise_line"), now=NOW)
        self.assertFalse(again["started"])

    def test_the_poll_finishes_deletes_files_and_evaluates(self):
        db = _judged_db()
        gs.seal(db, surface="praise_line", judge="founder@w.com")
        db.runs.append({"id": "run-1", "surface": "praise_line", "status": "running",
                        "openai_job_id": "job-1", "openai_file_id": "file-1",
                        "openai_validation_file_id": "file-2", "files_deleted_at": None})
        provider = _Provider(status="succeeded")
        with mock.patch("services.golden_evaluation.evaluate",
                        return_value={"passed": True, "id": "rep-1"}) as evaluate:
            out = mt.poll_runs(db, provider, config=_open3("praise_line"), now=NOW)
        self.assertEqual(out[0]["status"], "succeeded")
        self.assertEqual(db.runs[0]["candidate_model"], provider.model)
        self.assertEqual(provider.deleted, ["file-1", "file-2"])
        self.assertIsNotNone(db.runs[0]["files_deleted_at"])
        self.assertEqual(evaluate.call_args.kwargs["candidate_model"], provider.model)
        self.assertEqual(out[0]["evaluation"], {"passed": True, "report_id": "rep-1"})

    def test_a_failed_job_is_recorded_and_still_loses_its_files(self):
        db = _Db()
        db.runs.append({"id": "run-1", "surface": "praise_line", "status": "running",
                        "openai_job_id": "job-1", "openai_file_id": "file-1", "files_deleted_at": None})
        provider = _Provider(status="failed")
        out = mt.poll_runs(db, provider, config=_Config(), now=NOW)
        self.assertEqual(out[0]["status"], "failed")
        self.assertEqual(db.runs[0]["failure"], "boom")
        self.assertEqual(provider.deleted, ["file-1"])

    def test_the_withdrawal_sweep_cancels_and_deletes_whatever_the_door_says(self):
        db = _Db()
        db.runs.append({"id": "run-1", "status": "running"})
        db.withdrawn_runs = [{"run_id": "run-1", "status": "running", "openai_job_id": "job-1",
                              "openai_file_id": "file-1", "openai_validation_file_id": None,
                              "files_deleted_at": None, "withdrawn_at": None}]
        provider = _Provider()
        out = mt.sweep_withdrawn(db, provider, now=NOW)
        self.assertEqual(out["swept"], 1)
        self.assertEqual(provider.cancelled, ["job-1"])
        self.assertEqual(provider.deleted, ["file-1"])
        self.assertEqual(db.runs[0]["status"], "withdrawn")
        self.assertEqual(db.runs[0]["withdrawn_reason"], "consent_withdrawn")

    def test_the_weekly_job_carries_the_training_pass(self):
        class _Weekly(_Db):
            def upsert_ledger_snapshot(self, **row):
                self.row = row
                return row

            def refresh_feedback_pair_consent(self, surfaces):
                return {"refreshed": 0}

            def list_voided_unpurged_pair_releases(self):
                return []

            def list_releasable_pairs(self, surface, limit=5000):
                return []
        db = _Weekly()
        ledger = {"ledger_version": "v", "pairs": {"praise_line": {"total": 0, "unexported": 0}},
                  "shadow_cues": {}, "doors": {}, "unavailable": []}
        with mock.patch("services.learning_ledger.ledger", return_value=ledger):
            out = lw.run_weekly(db, config=_Config(), now=NOW, provider=_Provider())
        self.assertEqual(out["training"]["withdrawn_sweep"]["swept"], 0)
        self.assertEqual([s["surface"] for s in out["training"]["surfaces"]],
                         ["clearer_version", "exercise_script", "praise_line"])
        self.assertTrue(all("door 3 closed" in s["why"] for s in out["training"]["surfaces"]))
        self.assertIn("training", db.row["snapshot"]["doors_pass"])


class PromotionTests(unittest.TestCase):
    def _db_with_report(self, passed=True, lock=None):
        from services.ml_surface_contracts import locked_prompt_hash
        db = _Db()
        db.runs.append({"id": "run-1", "surface": "praise_line", "status": "succeeded",
                        "candidate_model": "ft:x"})
        db.reports.append({"id": "rep-1", "surface": "praise_line", "candidate_model": "ft:x",
                           "passed": passed, "run_id": "run-1",
                           "prompt_lock_sha256": lock or locked_prompt_hash("praise_line")})
        return db

    def test_nothing_promotes_while_door_4_is_closed(self):
        db = self._db_with_report()
        with self.assertRaises(mp.PromotionRefusal) as closed:
            mp.promote(db, surface="praise_line", candidate_model="ft:x",
                       evaluation_report_id="rep-1", by="founder", config=_Config())
        self.assertIn("door 4 closed", closed.exception.message)
        with self.assertRaises(mp.PromotionRefusal):
            mp.promote(db, surface="praise_line", candidate_model="ft:x",
                       evaluation_report_id="rep-1", by="founder", config=_open4("clearer_version"))
        self.assertEqual(db.runtime, {})

    def test_a_promotion_needs_a_passed_report_under_the_current_lock(self):
        db = self._db_with_report(passed=False)
        with self.assertRaises(mp.PromotionRefusal) as failed:
            mp.promote(db, surface="praise_line", candidate_model="ft:x",
                       evaluation_report_id="rep-1", by="founder", config=_open4("praise_line"))
        self.assertEqual(failed.exception.code, "REPORT_FAILED")
        db = self._db_with_report(lock="0" * 64)
        with self.assertRaises(mp.PromotionRefusal) as stale:
            mp.promote(db, surface="praise_line", candidate_model="ft:x",
                       evaluation_report_id="rep-1", by="founder", config=_open4("praise_line"))
        self.assertEqual(stale.exception.code, "PROMPT_LOCK_MISMATCH")

    def test_promote_writes_only_the_named_surface_and_kill_returns_stock(self):
        db = self._db_with_report()
        out = mp.promote(db, surface="praise_line", candidate_model="ft:x",
                         evaluation_report_id="rep-1", by="founder", config=_open4("praise_line"), now=NOW)
        self.assertEqual(out["model"], "ft:x")
        self.assertEqual(db.runtime, {"openai_surface_model_praise_line": "ft:x"})
        self.assertEqual(db.promotions[0]["candidate_model"], "ft:x")
        killed = mp.kill(db, surface="praise_line", by="founder", reason="tone", now=NOW)
        self.assertEqual(db.runtime["openai_surface_model_praise_line"], mp.stock_model())
        self.assertTrue(killed["killed"])
        self.assertEqual(db.promotions[0]["kill_reason"], "tone")

    def test_the_stock_model_is_served_while_the_door_is_shut(self):
        from services.llm import _model_the_promotion_gate_allows
        with mock.patch("services.runtime_model_gate.promotion_is_enabled", return_value=False):
            self.assertEqual(_model_the_promotion_gate_allows("praise_line", "ft:x", "stock"), "stock")


if __name__ == "__main__":
    unittest.main()
