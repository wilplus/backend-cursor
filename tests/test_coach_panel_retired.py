"""The coach panel's removals (founder 2026-09-30, B1 to B8; contract 63 to
66; docs/FOUNDER-LOCK-coach-panel-2026-10.md).

Pins:
  * no route named star verdict remains, and the V2 lane's tables stay;
  * the coach's Ideal Text edit, verify and approve answer 410 and write
    nothing;
  * the compare, audit-data and confidence-comparison routes are gone;
  * the CMS exercise lane's routes are gone and the posts routes stay;
  * the annotation emitter that approve fed is gone, its diff helpers stay;
  * the arc-level delivery (P2-19, removed 2026-10-01 on the founder's "do
    P2-19 now"): the per-snippet save, the re-cut, the per-take Save, the
    wrap-up read, the slide-mapping correction, the publish and the internal
    publish door answer 410; the delivery job, the publish email and the
    publish service are gone; the tables stay; the album's coach leg is
    released by the judgement write.
"""
from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class RetiredRoutesTests(unittest.TestCase):
    def setUp(self):
        try:
            from app import app
        except Exception as e:  # pragma: no cover
            self.skipTest(f"app import failed: {e}")
        app.config["TESTING"] = True
        self.app = app
        self.client = app.test_client()
        self.rules = {r.rule for r in app.url_map.iter_rules()}

    def test_no_star_verdict_route_remains(self):
        for rule in self.rules:
            self.assertNotIn("star", rule.split("/coach/")[-1] if "/coach/" in rule else "", rule)
        self.assertNotIn("/v2/coach/arc/<arc_id>/stars", self.rules)
        self.assertNotIn("/v2/coach/snippets/<snippet_id>/star-verdict", self.rules)
        self.assertNotIn("/v2/coach/snippets/<snippet_id>/star-text", self.rules)
        # The tables stay as history: the purge registry still names the rows.
        registry = (ROOT / "services/data_purge_registry.py").read_text()
        self.assertIn('"star_verdicts"', registry)

    def test_the_coach_ideal_text_routes_answer_410(self):
        for method, path in (("GET", "/v2/coach/arc/a1/ideal-text"),
                             ("PUT", "/v2/coach/arc/a1/ideal-text"),
                             ("POST", "/v2/coach/arc/a1/verify"),
                             ("POST", "/v2/coach/arc/a1/ideal-text/approve")):
            with self.subTest(path=path):
                response = self.client.open(path, method=method, json={})
                # Unauthenticated callers meet the coach gate first; a coach
                # meets the tombstone. Either way nothing is written.
                self.assertIn(response.status_code, (401, 403, 410))
        source = (ROOT / "routes/v2/coach.py").read_text()
        self.assertIn('"code": "GONE"', source)
        self.assertNotIn("def v2_coach_approve_ideal_text(", source)
        self.assertNotIn("emit_ideal_text_annotations", source)

    def test_the_dead_coach_routes_are_gone(self):
        for path in ("/v2/coach/arcs/<arc_id>/ab-pairs",
                     "/v2/coach/arcs/<arc_id>/ab-verdict",
                     "/v2/coach/students/<user_id>/audit-data",
                     "/v2/coach/sessions/<session_id>/confidence-comparison"):
            self.assertNotIn(path, self.rules, path)
        for gone in ("services/ab_slide_pairs.py", "services/feeling_performance.py",
                     "services/founder_confidence_comparison.py"):
            self.assertFalse((ROOT / gone).exists(), gone)

    def test_the_cms_exercise_lane_routes_are_gone_and_posts_stay(self):
        for path in ("/v2/internal/journal/diagnostic-exercises/list",
                     "/v2/internal/journal/diagnostic-exercises/save",
                     "/v2/internal/journal/exercise-gaps",
                     "/v2/internal/journal/exercise-learning-readiness",
                     "/v2/internal/journal/exercise-learning-evaluation",
                     "/v2/internal/journal/speaking-errors/list",
                     "/v2/internal/journal/speaking-errors/save"):
            self.assertNotIn(path, self.rules, path)
        for path in ("/v2/internal/journal/posts/list", "/v2/internal/journal/posts/create",
                     "/v2/coach/speaking-errors"):
            self.assertIn(path, self.rules, path)

    def test_the_arc_level_delivery_routes_answer_410(self):
        for method, path in (
                ("POST", "/v2/coach/sessions/s1/snippets/n1"),
                ("POST", "/v2/coach/sessions/s1/recut"),
                ("POST", "/v2/coach/sessions/s1/save-feedback"),
                ("GET", "/v2/coach/arc/a1/review-state"),
                ("PUT", "/v2/coach/snippets/n1/slide"),
                ("POST", "/v2/coach/arc/a1/publish-analysis"),
                ("POST", "/v2/internal/publish-session-results")):
            with self.subTest(path=path):
                response = self.client.open(path, method=method, json={})
                self.assertIn(response.status_code, (401, 403, 410))
        source = (ROOT / "routes/v2/coach.py").read_text()
        for gone in ("def v2_coach_publish_analysis(", "def v2_coach_save_feedback(",
                     "def v2_coach_session_recut(", "def v2_coach_arc_review_state(",
                     "def v2_coach_put_snippet_slide(", "def v2_coach_save_snippet(",
                     "_save_coach_snippet_lanes", "_arc_has_a_surfaced_note"):
            self.assertNotIn(gone, source, gone)
        # The judgement write stays: one instrument on the walk (35g-5).
        self.assertIn("/v2/coach/snippets/<snippet_id>/confidence-label", self.rules)
        # The tables stay as history: the purge registry still names them.
        registry = (ROOT / "services/data_purge_registry.py").read_text()
        for table in ("coach_review_delivery_outbox", "coach_review_revisions",
                      "coach_snippet_drafts", "snippet_slide_corrections"):
            self.assertIn(table, registry, table)

    def test_the_gap_view_moved_to_the_founder_ledger(self):
        source = (ROOT / "routes/v2/learning_admin.py").read_text()
        self.assertIn("gap_view(db, days=30)", source)
        self.assertIn('"gaps": gaps', source)


class RetiredCodeTests(unittest.TestCase):
    def test_the_star_service_keeps_only_the_speaker_side_reads(self):
        from services import star_verdicts
        self.assertTrue(hasattr(star_verdicts, "filter_user_suggestions"))
        self.assertTrue(hasattr(star_verdicts, "released_user_verdicts"))
        for gone in ("validate_verdict", "stars_with_verdicts", "corpus_summary",
                     "annotation_pair_for_star", "validate_star_text"):
            self.assertFalse(hasattr(star_verdicts, gone), gone)

    def test_the_delivery_job_and_the_publish_email_are_gone(self):
        for gone in ("services/coach_publish.py", "services/coach_publish_delivery.py",
                     "services/post_session_results_email.py"):
            self.assertFalse((ROOT / gone).exists(), gone)
        jobs = (ROOT / "services/pipeline_jobs.py").read_text()
        self.assertNotIn("sweep_pending_deliveries", jobs)
        for boot in ("worker.py", "app.py"):
            self.assertNotIn("email_config_summary", (ROOT / boot).read_text(), boot)
        from services import db as db_mod
        for name in ("publish_coach_review_revisions", "get_coach_review_delivery",
                     "list_pending_coach_review_deliveries",
                     "record_snippet_slide_correction"):
            self.assertFalse(hasattr(db_mod.DatabaseService, name), name)
        # The speaker's "Your coach" still reads a historical revision.
        self.assertTrue(hasattr(db_mod.DatabaseService, "get_coach_review_revision"))
        self.assertTrue(hasattr(db_mod.DatabaseService, "get_snippet_slide_corrections"))

    def test_the_albums_coach_leg_is_released_by_the_judgement_write(self):
        from services import voice_album
        import inspect
        src = inspect.getsource(voice_album._coach_yes_sessions)
        self.assertNotIn("results_published_at", src)
        from routes.v2 import coach
        self.assertIn("reconcile_voice_album_clip",
                      inspect.getsource(coach._reconcile_album_after_judgement))

    def test_the_annotation_emitter_is_gone_and_its_diff_helpers_stay(self):
        from services import ideal_text_annotations
        self.assertFalse(hasattr(ideal_text_annotations, "emit_ideal_text_annotations"))
        self.assertTrue(hasattr(ideal_text_annotations, "strip_for_diff"))


if __name__ == "__main__":
    unittest.main()
