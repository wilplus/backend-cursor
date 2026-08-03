"""Backlog item 11 + the stress-lane deletion (founder 2026-08-03).

1) StressLaneIsGoneTests — the deletion, asserted rather than assumed. No
   trainer in a request handler, no promote path, no model loader in clip
   selection, no admin corpus endpoints. This is the regression gate on
   "someone quietly brings the second lane back".
2) LearningTraceServiceTests — GET /v2/admin/learning/trace aggregation:
   the two surviving lanes present, lane_acoustic gone, per-section failures
   degrade to null + errors[], and the peer_review provenance bucket shows up
   with its retrain-trigger decision attached.

The trainer feature-parity tests that used to live here went with the
trainer: the 16-vs-17 feature vector skew they guarded cannot recur, because
neither the trainer nor the serving twin exists any more.

Flask/Supabase-dependent → skips locally without deps, runs in CI
(same gotcha as test_credits_admin).

Run: python3 -m unittest test_learning_trace
"""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from services.db import db as real_db
    from services import learning_serve
    from services import learning_trace
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    real_db = None
    learning_serve = None
    learning_trace = None
    _IMPORT_ERROR = e


def _code_without_prose(path: str) -> str:
    """A module's source with comments and docstrings stripped out.

    The deletion notes live in those comments and docstrings ON PURPOSE — a
    reader who finds the gap deserves to know why it is a gap, and the next
    person tempted to re-add a trainer should hit the reason first. A naive
    substring search would match the note explaining the deletion and report
    the very thing it documents as still present, so strip the prose and
    assert against executable code only."""
    import ast
    import io
    import tokenize
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)
    def _is_docstring(tok) -> bool:
        if tok.type != tokenize.STRING:
            return False
        try:
            return ast.literal_eval(tok.string) in docstrings
        except (ValueError, SyntaxError):
            return False  # f-string / anything not a plain literal

    out = [tok.string
           for tok in tokenize.generate_tokens(io.StringIO(src).readline)
           if tok.type != tokenize.COMMENT and not _is_docstring(tok)]
    return "\n".join(out)


# ── 1) the stress lane is gone and must stay gone ──────────────────────────

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class StressLaneIsGoneTests(unittest.TestCase):
    """Founder 2026-08-03: stress recognition is dead.

    Each assertion here is one thing the founder named. They are file/route
    level rather than behavioural on purpose — you cannot behaviourally test
    the absence of a code path, and the failure mode worth catching is
    somebody re-adding one."""

    def test_no_trainer_scripts(self):
        for path in ("scripts/train_stress_classifier_baseline.py",
                     "scripts/export_stress_snippets_dataset.py"):
            self.assertFalse(os.path.exists(path),
                             f"{path} is back — there is no replacement trainer")

    def test_no_subprocess_trainer_in_a_request_handler(self):
        with open("routes/internal_webhooks.py", encoding="utf-8") as fh:
            src = fh.read()
        # The route, the 30-minute timeout, and the module's ability to shell
        # out at all — a train pipeline has no business in a web request.
        self.assertNotIn("/v2/internal/stress-model/train", src)
        self.assertNotIn("import subprocess", src)
        self.assertNotIn("timeout=1800", src)

    def test_nothing_promotes_a_model_artifact(self):
        """No surviving code path may promote a model without a quality gate
        AND a human decision. The stress lane's writer was the only
        auto-promoting one; assert the key it wrote is unreachable.

        Checked against CODE, not prose — the module docstrings deliberately
        still name what was deleted so the next reader knows why it went."""
        for path in ("routes/internal_webhooks.py",
                     "services/stress_snippet_service.py",
                     "services/charisma_snippet_service.py"):
            code = _code_without_prose(path)
            self.assertNotIn("upsert_runtime_config(", code, path)
            self.assertNotIn("stress_baseline_model_path", code, path)
            self.assertNotIn("auto_promote", code, path)

    def test_clip_selection_has_no_model_loader(self):
        """The promoted model fed clip SELECTION only, and the no-model state
        already ran heuristic suspicion scoring. Deleting the loader makes
        that heuristic permanent — it must not have grown a hard dependency
        on the model on the way out."""
        for path in ("services/stress_snippet_service.py",
                     "services/charisma_snippet_service.py"):
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            for gone in ("_load_baseline_model", "_predict_with_baseline_model",
                         "_feature_vector_for_model"):
                self.assertNotIn(f"def {gone}", src, f"{gone} in {path}")
            # The heuristic the selector now runs on, permanently.
            self.assertIn("suspicion = 0.45 * c.filler_density", src, path)

    def test_local_file_path_model_fallback_is_gone(self):
        """A model ref pointing at a local path on Railway dies at the next
        deploy. The fallback is deleted, not just its call site."""
        import config as config_module
        self.assertFalse(
            hasattr(config_module.Config, "STRESS_BASELINE_MODEL_PATH"))
        self.assertFalse(
            hasattr(config_module.Config, "STRESS_MODEL_TRAIN_SECRET"))
        self.assertFalse(hasattr(config_module.Config, "STRESS_MODEL_BUCKET"))

    def test_lane_corpus_endpoints_are_unregistered(self):
        for path in ("routes/snippet_labels_routes.py",
                     "services/snippet_labels.py"):
            self.assertFalse(os.path.exists(path), f"{path} is back")
        with open("app.py", encoding="utf-8") as fh:
            app_src = fh.read()
        self.assertNotIn("snippet_labels_bp", app_src)
        with open("routes/v2_routes.py", encoding="utf-8") as fh:
            v2_src = fh.read()
        self.assertNotIn('"/user/snippets/<snippet_id>/label"', v2_src)

    def test_the_replacement_capture_exists(self):
        """The lane is not merely deleted — it is pivoted. The peer-review
        capture is the thing it became."""
        with open("routes/v2_routes.py", encoding="utf-8") as fh:
            v2_src = fh.read()
        self.assertIn('"/user/snippets/<snippet_id>/confidence-review"', v2_src)


# ── 2) learning trace aggregation ──────────────────────────────────────────

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
                "runtime_config": [],
                "snippet_confidence_reviews": [
                    {"id": "p1", "snippet_id": "s1", "reviewer_user_id": "u1",
                     "ai_correct": True, "model_version": "direction-v1-a",
                     "created_at": "2026-08-01T00:00:00+00:00"},
                    {"id": "p2", "snippet_id": "s2", "reviewer_user_id": "u1",
                     "ai_correct": False, "model_version": "direction-v1-a",
                     "created_at": "2026-08-02T00:00:00+00:00"},
                    {"id": "p3", "snippet_id": "s1", "reviewer_user_id": "u2",
                     "ai_correct": True, "model_version": None,
                     "created_at": "2026-08-02T00:00:00+00:00"},
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
        for key in ("lane_shadow", "lane_annotations",
                    "pipeline_docs", "known_gaps", "errors", "generated_at"):
            self.assertIn(key, payload)
        # The retired third lane is GONE from the payload (the FE renders two
        # lanes; a trace that still served a third would keep it alive).
        self.assertNotIn("lane_acoustic", payload)
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

    def test_peer_review_corpus_is_reported_with_its_own_provenance(self):
        """Separate provenance, always: peer flags are NON-BLIND and must be
        countable apart from the blind coach corpus."""
        shadow = learning_trace.build_learning_trace()["lane_shadow"]
        peer = shadow["peer_review"]
        self.assertEqual(peer["total"], 3)
        self.assertEqual(peer["ai_correct_true"], 2)
        self.assertEqual(peer["ai_correct_false"], 1)
        self.assertEqual(peer["reviewers"], 2)
        self.assertEqual(peer["selection_source"], "peer_review")
        self.assertFalse(peer["blind"])
        self.assertEqual(peer["by_model_version"],
                         {"direction-v1-a": 2, "(unattributed)": 1})

    def test_peer_review_shows_in_the_selection_source_mix(self):
        """The trace breaks the corpus down by_selection_source so the MIX of
        blind coach truth vs non-blind peer flags stays visible."""
        labels = learning_trace.build_learning_trace(
        )["lane_shadow"]["training_labels"]
        self.assertEqual(labels["by_selection_source"],
                         {"heuristic": 1, "random": 1, "peer_review": 3})
        # `total` still means BLIND coach labels only — the peer rows live in
        # their own table and must never inflate the coach-truth count.
        self.assertEqual(labels["total"], 2)

    def test_retrain_trigger_excludes_peer_review_by_decision(self):
        """Whether peer_review counts toward the >=50 / >=25-new trigger is a
        DECISION, not a default — and the trace has to say which way."""
        shadow = learning_trace.build_learning_trace()["lane_shadow"]
        self.assertFalse(shadow["auto_retrain"]["counts_peer_review"])
        self.assertFalse(shadow["peer_review"]["counts_toward_retrain_trigger"])
        self.assertIn("do NOT count", shadow["peer_review"]["decision"])

    def test_missing_peer_table_does_not_break_the_coach_counts(self):
        """Pre-migration, the peer bucket is simply absent — a new table may
        never take down counts that rendered fine before it existed."""
        self.store["raise_tables"].add("snippet_confidence_reviews")
        labels = learning_trace.build_learning_trace(
        )["lane_shadow"]["training_labels"]
        self.assertEqual(labels["total"], 2)
        self.assertNotIn("peer_review", labels["by_selection_source"])

    def test_failing_section_degrades_to_null_plus_error(self):
        self.store["raise_tables"].add("admin_annotation_events")
        payload = learning_trace.build_learning_trace()
        self.assertIsNone(
            payload["lane_annotations"]["annotation_events"],
        )
        sections = [e["section"] for e in payload["errors"]]
        self.assertIn("lane_annotations.annotation_events", sections)
        # The other lane still renders.
        self.assertIsNotNone(payload["lane_shadow"]["training_labels"])

    def test_retired_lane_is_documented_not_just_absent(self):
        """A lane that vanishes without a trace reads as a bug. The pipeline
        docs carry WHY it went and what replaced it."""
        docs = learning_trace.build_learning_trace()["pipeline_docs"]
        self.assertEqual([lane["id"] for lane in docs["lanes"]],
                         ["shadow_direction", "annotation_writer"])
        retired = {lane["id"]: lane for lane in docs["retired_lanes"]}
        self.assertIn("acoustic_baseline", retired)
        self.assertEqual(retired["acoustic_baseline"]["retired_at"],
                         "2026-08-03")

    def test_known_gaps_surface_the_peer_weighting_question(self):
        """The charisma-uses-stress-model gap is closed by deletion; the open
        question is now how a non-blind peer label should weigh."""
        payload = learning_trace.build_learning_trace()
        gap_ids = [g["id"] for g in payload["known_gaps"]]
        self.assertIn("peer_review_weighting_undecided", gap_ids)
        self.assertNotIn("charisma_uses_stress_model", gap_ids)

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
