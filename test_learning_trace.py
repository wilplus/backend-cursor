"""Backlog item 11 + the two confirmed learning-pipeline bug fixes.

1) StressTrainerFeatureParityTests — training/serving feature-vector skew:
   the trainer's empty-frame path must emit the SAME 17-dim vector shape as
   its populated path and as the serving twin
   (services/stress_snippet_service._feature_vector_for_model).
2) StressModelTrainWebhookGateTests — the train webhook's promotion is
   quality-gate-guarded (PHASE-A0 A3.4 "Promote stays human-gated"):
   gate-fail/missing → no promote; force_promote overrides the gate (never
   the storage requirement); storage-upload failure → never promote a local
   ephemeral path.
3) LearningTraceServiceTests — GET /v2/admin/learning/trace aggregation:
   all sections present, per-section failures degrade to null + errors[],
   the charisma-uses-stress-model known gap is surfaced.

Flask/Supabase-dependent → skips locally without deps, runs in CI
(same gotcha as test_credits_admin).

Run: python3 -m unittest test_learning_trace
"""
from __future__ import annotations

import importlib
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    import numpy as np
    from flask import Flask
    from routes import internal_webhooks as iw
    from services.db import db as real_db
    from services import learning_serve
    from services import learning_trace
    trainer = importlib.import_module("scripts.train_stress_classifier_baseline")
    from services.stress_snippet_service import _feature_vector_for_model
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    np = None
    Flask = None
    iw = None
    real_db = None
    learning_serve = None
    learning_trace = None
    trainer = None
    _feature_vector_for_model = None
    _IMPORT_ERROR = e


# ── 1) 16-vs-17 feature-vector training/serving skew ───────────────────────

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class StressTrainerFeatureParityTests(unittest.TestCase):

    def test_feature_names_is_17(self):
        self.assertEqual(len(trainer.FEATURE_NAMES), 17)
        # 12 scalars + the 5 scenario one-hots, in serving order.
        self.assertEqual(trainer.FEATURE_NAMES[-5:], [
            "scenario_after_pause", "scenario_before_pause",
            "scenario_high_filler_density", "scenario_low_filler_density",
            "scenario_uncertain",
        ])

    def test_empty_frame_path_matches_populated_path_shape(self):
        empty = trainer._extract_features(
            np.zeros((0,), dtype=np.float32), "after_pause", {}, 1000,
        )
        rng = np.random.default_rng(0)
        signal = rng.standard_normal(16000).astype(np.float32) * 0.1
        populated = trainer._extract_features(
            signal, "after_pause",
            {"pause_strength": 0.5, "filler_density": 0.2, "energy_std": 0.01},
            1000,
        )
        self.assertEqual(empty.shape, populated.shape)
        self.assertEqual(empty.shape[0], len(trainer.FEATURE_NAMES))

    def test_trainer_matches_serving_twin_dimension(self):
        # Serving twin (stress_snippet_service) — both the zeros path and the
        # populated path are 17; the trainer must agree on every path.
        serve_empty = _feature_vector_for_model(
            np.zeros((0,), dtype=np.float32), "uncertain", {}, 1000,
        )
        rng = np.random.default_rng(1)
        signal = rng.standard_normal(16000).astype(np.float32) * 0.1
        serve_full = _feature_vector_for_model(
            signal, "uncertain",
            {"pause_strength": 0.1, "filler_density": 0.1, "energy_std": 0.01},
            1000,
        )
        train_empty = trainer._extract_features(
            np.zeros((0,), dtype=np.float32), "uncertain", {}, 1000,
        )
        self.assertEqual(serve_empty.shape[0], len(trainer.FEATURE_NAMES))
        self.assertEqual(serve_full.shape[0], len(trainer.FEATURE_NAMES))
        self.assertEqual(train_empty.shape[0], serve_full.shape[0])


# ── 2) quality-gate-guarded auto-promote in the train webhook ──────────────

_SECRET = "test-train-secret"


def _gate(ok: bool) -> dict:
    return {
        "targets": {"recall_stress_min": 0.85, "precision_stress_min": 0.75,
                    "fpr_no_stress_max": 0.30},
        "actual": {"recall_stress": 0.9 if ok else 0.2,
                   "precision_stress": 0.8 if ok else 0.2,
                   "fpr_no_stress": 0.1 if ok else 0.9},
        "passes": {"recall_stress": ok, "precision_stress": ok,
                   "fpr_no_stress": ok},
        "ok": ok,
    }


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class StressModelTrainWebhookGateTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(iw.internal_webhooks_bp)
        self.client = self.app.test_client()
        self.created_files: list[str] = []
        self.metrics_obj: dict = {"train": {}, "val": {},
                                  "quality_gate": _gate(True)}
        self.uploads: list[tuple] = []
        self.upsert_calls: list[dict] = []
        self.upload_raises = False

        def fake_run(cmd, **kwargs):
            if any("train_stress_classifier_baseline" in c for c in cmd):
                model_out = cmd[cmd.index("--model-out") + 1]
                metrics_out = cmd[cmd.index("--metrics-out") + 1]
                artifact = {
                    "model_type": "logreg_baseline_v1",
                    "weights": [0.0] * 17,
                    "norm_mean": [0.0] * 17,
                    "norm_std": [1.0] * 17,
                    "bias": 0.0,
                    "metrics": {k: v for k, v in self.metrics_obj.items()},
                }
                for path, obj in ((model_out, artifact),
                                  (metrics_out, self.metrics_obj)):
                    with open(path, "w", encoding="utf-8") as fh:
                        json.dump(obj, fh)
                    self.created_files.append(path)
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        def fake_upload(bucket, key, data, content_type=None):
            if self.upload_raises:
                raise RuntimeError("storage down")
            self.uploads.append((bucket, key))

        def fake_upsert(**kwargs):
            self.upsert_calls.append(kwargs)
            return {"key": kwargs.get("key"), "value": kwargs.get("value"),
                    "metadata": kwargs.get("metadata")}

        self._p = [
            patch.object(iw.config, "STRESS_MODEL_TRAIN_SECRET", _SECRET,
                         create=True),
            patch.object(iw.subprocess, "run", side_effect=fake_run),
            patch.object(iw.db, "upload_audio", side_effect=fake_upload),
            patch.object(iw.db, "upsert_runtime_config",
                         side_effect=fake_upsert),
        ]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()
        for path in self.created_files:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _post(self, body=None):
        return self.client.post(
            "/v2/internal/stress-model/train",
            json=body or {},
            headers={"X-Internal-Secret": _SECRET},
        )

    def test_gate_pass_promotes(self):
        r = self._post()
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["promoted"])
        self.assertIsNone(data["promotion_skipped_reason"])
        self.assertEqual(len(self.upsert_calls), 1)
        call = self.upsert_calls[0]
        self.assertTrue(call["value"].startswith("storage://"))
        md = call["metadata"]
        self.assertTrue(md["quality_gate_ok"])
        self.assertFalse(md["force_promote"])
        self.assertEqual(md["promoted_via"], "quality_gate_pass")

    def test_gate_fail_does_not_promote(self):
        self.metrics_obj["quality_gate"] = _gate(False)
        r = self._post()
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertFalse(data["promoted"])
        self.assertEqual(data["promotion_skipped_reason"], "quality_gate_failed")
        self.assertFalse(data["quality_gate"]["ok"])
        self.assertEqual(self.upsert_calls, [])

    def test_gate_missing_does_not_promote(self):
        self.metrics_obj.pop("quality_gate")
        r = self._post()
        data = r.get_json()
        self.assertFalse(data["promoted"])
        self.assertEqual(data["promotion_skipped_reason"], "quality_gate_missing")
        self.assertEqual(self.upsert_calls, [])

    def test_force_promote_overrides_failed_gate(self):
        self.metrics_obj["quality_gate"] = _gate(False)
        r = self._post({"force_promote": True})
        data = r.get_json()
        self.assertTrue(data["promoted"])
        self.assertIsNone(data["promotion_skipped_reason"])
        md = self.upsert_calls[0]["metadata"]
        self.assertTrue(md["force_promote"])
        self.assertFalse(md["quality_gate_ok"])
        self.assertEqual(md["promoted_via"], "force_promote")

    def test_storage_failure_never_promotes_even_forced(self):
        self.upload_raises = True
        r = self._post({"force_promote": True})
        data = r.get_json()
        self.assertFalse(data["promoted"])
        self.assertEqual(data["promotion_skipped_reason"],
                         "artifact_not_in_storage")
        self.assertEqual(self.upsert_calls, [])

    def test_auto_promote_false_skips_silently(self):
        r = self._post({"auto_promote": False})
        data = r.get_json()
        self.assertFalse(data["promoted"])
        self.assertIsNone(data["promotion_skipped_reason"])
        self.assertEqual(self.upsert_calls, [])


# ── 3) learning trace aggregation ──────────────────────────────────────────

class _FakeQuery:
    def __init__(self, store, table):
        self._store = store
        self._table = table
        self._eq: list[tuple] = []

    def select(self, *a, **k):
        return self

    def eq(self, key, val):
        self._eq.append((key, val))
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def gt(self, *a, **k):
        return self

    @property
    def not_(self):
        return self

    def is_(self, *a, **k):
        return self

    def execute(self):
        if self._table in self._store.get("raise_tables", set()):
            raise RuntimeError(f"{self._table} unavailable")
        rows = list(self._store["tables"].get(self._table, []))
        for key, val in self._eq:
            rows = [r for r in rows if r.get(key) == val]
        return SimpleNamespace(data=rows, count=len(rows))


class _FakeClient:
    def __init__(self, store):
        self._store = store

    def table(self, name):
        return _FakeQuery(self._store, name)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class LearningTraceServiceTests(unittest.TestCase):

    def setUp(self):
        self.store = {
            "tables": {
                "model_versions": [{
                    "version": "direction-v1-20260701T000000Z",
                    "created_at": "2026-07-01T00:00:00+00:00",
                    "status": "shadow", "corpus_size": 60,
                    "metrics": {"accuracy": 0.7},
                    # no artifact_ref → coefficients section stays None
                }],
                "shadow_predictions": [
                    {"created_at": "2026-07-06T10:00:00+00:00",
                     "predicted_label": "challenge",
                     "coach_actual_label": "challenge"},
                    {"created_at": "2026-07-07T10:00:00+00:00",
                     "predicted_label": "threat",
                     "coach_actual_label": "challenge"},
                ],
                "training_labels": [
                    {"snippet_id": "s1", "value": "challenge",
                     "selection_source": "heuristic"},
                    {"snippet_id": "s2", "value": "threat",
                     "selection_source": "random"},
                ],
                "admin_annotation_events": [
                    {"section_type": "comment", "field_name": "admin_comment",
                     "reason_chip": "tone",
                     "previous_value_hash": "a", "new_value_hash": "b"},
                    {"section_type": "comment", "field_name": "admin_comment",
                     "reason_chip": None,
                     "previous_value_hash": "c", "new_value_hash": "c"},
                ],
                "admin_annotation_export_runs": [
                    {"id": "r1", "status": "success", "exported_count": 2,
                     "started_at": "2026-07-08T00:00:00+00:00"},
                ],
                "runtime_config": [
                    {"key": "stress_baseline_model_path",
                     "value": "storage://stress_models/baseline/all/x.json",
                     "updated_by": "internal:stress-model-train",
                     "updated_at": "2026-07-08T00:00:00+00:00",
                     "metadata": {"quality_gate_ok": True,
                                  "force_promote": False}},
                ],
                "stress_snippets": [
                    {"id": "x1", "coach_label": "stress"},
                    {"id": "x2", "coach_label": "no_stress"},
                    {"id": "x3", "coach_label": None},
                ],
                "charisma_snippets": [
                    {"id": "y1", "coach_label": "charisma"},
                ],
                "snippet_labels": [
                    {"id": "l1", "confidence": "high"},
                    {"id": "l2", "confidence": "low"},
                ],
            },
            "raise_tables": set(),
        }
        self._p = [patch.object(real_db, "client", _FakeClient(self.store))]
        for p in self._p:
            p.start()
        # Bust learning_serve's TTL caches so the fake client is what's read.
        learning_serve._version_cache["row"] = None
        learning_serve._version_cache["at"] = 0.0
        learning_serve._cache["version"] = None
        learning_serve._cache["bundle"] = None

    def tearDown(self):
        for p in self._p:
            p.stop()
        learning_serve._version_cache["row"] = None
        learning_serve._version_cache["at"] = 0.0

    def test_all_sections_present(self):
        payload = learning_trace.build_learning_trace()
        for key in ("lane_shadow", "lane_annotations", "lane_acoustic",
                    "pipeline_docs", "known_gaps", "errors", "generated_at"):
            self.assertIn(key, payload)
        self.assertEqual(payload["errors"], [])

        shadow = payload["lane_shadow"]
        self.assertEqual(len(shadow["model_versions"]), 1)
        self.assertIsNone(shadow["coefficients"])  # no artifact_ref
        self.assertEqual(shadow["shadow_agreement"]["sample_n"], 2)
        self.assertEqual(shadow["training_labels"]["total"], 2)
        self.assertEqual(
            shadow["training_labels"]["by_class"],
            {"challenge": 1, "threat": 1},
        )
        self.assertEqual(shadow["auto_retrain"]["min_total"], 50)
        self.assertEqual(shadow["auto_retrain"]["new_delta"], 25)
        weeks = shadow["agreement_over_time"]
        self.assertTrue(weeks and weeks[0]["n"] == 2)

        ann = payload["lane_annotations"]
        totals = ann["annotation_events"]
        self.assertEqual(totals["total"], 2)
        self.assertEqual(totals["approve_vs_override"]["approved_verbatim"], 1)
        self.assertEqual(totals["approve_vs_override"]["overridden"], 1)
        self.assertEqual(len(ann["export_runs"]), 1)
        self.assertIsNone(ann["copilot_model"])  # key absent in fake store

        ac = payload["lane_acoustic"]
        self.assertEqual(ac["stress_snippets"]["total"], 3)
        self.assertEqual(ac["stress_snippets"]["labeled_stress"], 1)
        self.assertEqual(ac["charisma_snippets"]["labeled_charisma"], 1)
        self.assertEqual(
            ac["stress_baseline_model"]["metadata"]["quality_gate_ok"], True,
        )
        self.assertEqual(ac["snippet_labels"]["labels_total"], 2)

    def test_failing_section_degrades_to_null_plus_error(self):
        self.store["raise_tables"].add("admin_annotation_events")
        payload = learning_trace.build_learning_trace()
        self.assertIsNone(
            payload["lane_annotations"]["annotation_events"],
        )
        sections = [e["section"] for e in payload["errors"]]
        self.assertIn("lane_annotations.annotation_events", sections)
        # Other lanes still render.
        self.assertIsNotNone(payload["lane_acoustic"]["stress_snippets"])
        self.assertIsNotNone(payload["lane_shadow"]["training_labels"])

    def test_known_gaps_surface_charisma_stress_model(self):
        payload = learning_trace.build_learning_trace()
        gap_ids = [g["id"] for g in payload["known_gaps"]]
        self.assertIn("charisma_uses_stress_model", gap_ids)

    def test_trace_route_is_admin_only(self):
        """BLIND COACH: the trace endpoint must be @require_admin, NOT the
        @require_admin_or_coach the sibling learning endpoints use — the
        payload shows machine guesses vs coach labels."""
        import inspect
        from routes import v2_routes
        src = inspect.getsource(v2_routes.v2_admin_learning_trace)
        self.assertNotIn("require_admin_or_coach", src.split("def ")[0])
        self.assertIn("@require_admin", src)


if __name__ == "__main__":
    unittest.main()
