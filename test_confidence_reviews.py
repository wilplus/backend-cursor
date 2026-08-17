"""Confident Voice owner response: Voice Album routing only.

1) ValidateConfidenceReviewTests — the pure validator. The load-bearing rule
   is STRICT BOOLEAN: "true" the string is a 400, not a coercion, because a
   coerced value is a fabricated training label and afterwards it is
   indistinguishable from a real one.
2) ConfidenceReviewRouteTests — the legacy POST remains compatible but writes
   only the owner-scoped Voice Album routing table.
3) ReviewCorpusSummaryTests — historical audit rows remain readable and
   permanently excluded from learning.

Flask/Supabase-dependent → skips locally without deps, runs in CI.

Run: python3 -m unittest test_confidence_reviews
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from flask import Flask
    from services import confidence_reviews
    from services.confidence_reviews import validate_confidence_review
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    confidence_reviews = None
    validate_confidence_review = None
    _IMPORT_ERROR = e


_SNIPPET = "11111111-2222-3333-4444-555555555555"
_REVIEWER = "99999999-8888-7777-6666-555555555555"


# ── 1) the validator ───────────────────────────────────────────────────────

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ValidateConfidenceReviewTests(unittest.TestCase):

    def test_accepts_a_real_boolean(self):
        for value in (True, False):
            row, err = validate_confidence_review({"ai_correct": value})
            self.assertIsNone(err)
            self.assertIs(row["ai_correct"], value)
            self.assertIsNone(row["model_version"])

    def test_string_true_is_rejected_not_coerced(self):
        """THE rule. A corpus that quietly accepted "true" would record a
        human verdict nobody gave, and nothing downstream could tell it from
        a real one."""
        for junk in ("true", "false", "yes", 1, 0, None, [], {}):
            row, err = validate_confidence_review({"ai_correct": junk})
            self.assertIsNone(row, f"coerced {junk!r}")
            self.assertIn("ai_correct", err)

    def test_missing_ai_correct_is_rejected(self):
        row, err = validate_confidence_review({})
        self.assertIsNone(row)
        self.assertIn("ai_correct", err)

    def test_non_object_body_is_rejected(self):
        for junk in (None, "ai_correct=true", [True], 7):
            row, err = validate_confidence_review(junk)
            self.assertIsNone(row)
            self.assertIn("body", err)

    def test_model_version_is_optional_and_typed(self):
        row, err = validate_confidence_review(
            {"ai_correct": True, "model_version": "direction-v1-20260801Z"})
        self.assertIsNone(err)
        self.assertEqual(row["model_version"], "direction-v1-20260801Z")

        row, err = validate_confidence_review(
            {"ai_correct": True, "model_version": 7})
        self.assertIsNone(row)
        self.assertIn("model_version", err)

    def test_blank_model_version_reads_as_absent(self):
        """A blank string is a client that sent nothing, not a version named
        "". Storing "" would create a fake attribution bucket."""
        row, err = validate_confidence_review(
            {"ai_correct": False, "model_version": "   "})
        self.assertIsNone(err)
        self.assertIsNone(row["model_version"])

    def test_provenance_is_its_own_selection_source(self):
        """Separate provenance, always — peer flags are NON-BLIND and must
        never be indistinguishable from the blind coach labels."""
        self.assertEqual(confidence_reviews.SELECTION_SOURCE, "peer_review")
        self.assertNotIn(confidence_reviews.SELECTION_SOURCE,
                         ("heuristic", "random", "coach"))

    def test_retrain_trigger_participation_is_an_explicit_decision(self):
        """Whether these rows count toward the >=50 / >=25-new trigger is a
        decision, not a default. It is currently NO — a non-blind validation
        of the model's own prediction must not set that model's retrain
        schedule."""
        self.assertIs(confidence_reviews.COUNTS_TOWARD_RETRAIN_TRIGGER, False)


# ── 2) the route ───────────────────────────────────────────────────────────

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ConfidenceReviewRouteTests(unittest.TestCase):

    def setUp(self):
        import auth
        from routes import v2_routes
        self.v2 = v2_routes
        self.app = Flask(__name__)
        self.app.register_blueprint(v2_routes.v2_bp, url_prefix="/v2")
        self.client = self.app.test_client()
        self.reviewer = _REVIEWER
        self._orig_verify = auth.verify_supabase_token
        auth.verify_supabase_token = lambda token: {"sub": self.reviewer}
        self._auth = auth
        self.saved: list[dict] = []
        self.snippet_exists = True
        self.owner = _REVIEWER

        def fake_get_snippet(snippet_id, user_id=None):
            if not self.snippet_exists:
                return None
            return {"id": snippet_id, "session_id": "sess",
                    "metrics": {"piece": {"slide_index": 3}}}

        def fake_session(session_id):
            return {"id": session_id, "user_id": self.owner, "arc_id": "arc-1"}

        def fake_upsert(**kwargs):
            key = (kwargs["snippet_id"], kwargs["owner_user_id"])
            self.saved[:] = [r for r in self.saved
                             if (r["snippet_id"], r["owner_user_id"]) != key]
            self.saved.append(dict(kwargs))
            return True

        self._p = [
            patch.object(self.v2.db, "get_snippet_by_id",
                         side_effect=fake_get_snippet),
            patch.object(self.v2.db, "v2_get_session_by_id",
                         side_effect=fake_session),
            patch.object(self.v2.db, "upsert_owner_voice_album_route",
                         side_effect=fake_upsert, create=True),
            patch("services.voice_album.refresh_voice_album", return_value=0),
        ]
        for item in self._p:
            item.start()

    def tearDown(self):
        for item in self._p:
            item.stop()
        self._auth.verify_supabase_token = self._orig_verify

    def _post(self, body, snippet_id=_SNIPPET):
        return self.client.post(
            f"/v2/user/snippets/{snippet_id}/confidence-review",
            json=body,
            headers={"Authorization": "Bearer test"},
        )

    def test_saves_owner_scoped_voice_album_routing(self):
        response = self._post({"ai_correct": True, "model_version": "v9"})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(self.saved, [{
            "snippet_id": _SNIPPET,
            "owner_user_id": _REVIEWER,
            "arc_id": "arc-1",
            "response": "yes",
            "slide_index": 3,
            "model_version": "v9",
        }])

    def test_changing_answer_replaces_the_routing_state(self):
        self._post({"ai_correct": True})
        self._post({"ai_correct": False})
        self.assertEqual(len(self.saved), 1)
        self.assertEqual(self.saved[0]["response"], "no")

    def test_string_true_is_a_400_at_the_route(self):
        response = self._post({"ai_correct": "true"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.saved, [])

    def test_bad_uuid_is_a_400(self):
        self.assertEqual(self._post({"ai_correct": True}, "bad").status_code, 400)

    def test_unknown_snippet_is_a_404(self):
        self.snippet_exists = False
        self.assertEqual(self._post({"ai_correct": True}).status_code, 404)
        self.assertEqual(self.saved, [])

    def test_foreign_owner_is_a_404(self):
        self.owner = "12121212-3434-5656-7878-909090909090"
        self.assertEqual(self._post({"ai_correct": True}).status_code, 404)
        self.assertEqual(self.saved, [])

    def test_missing_table_names_the_routing_migration(self):
        with patch.object(self.v2.db, "upsert_owner_voice_album_route",
                          return_value=False, create=True):
            response = self._post({"ai_correct": True})
        self.assertEqual(response.status_code, 500)
        self.assertIn("add_owner_voice_album_routing.sql",
                      response.get_json()["error"])

    def test_response_carries_no_machine_score_or_training_label(self):
        data = self._post({"ai_correct": True}).get_json()
        self.assertEqual(set(data), {"saved", "snippet_id", "ai_correct"})
        self.assertNotIn("value", data)


# ── 3) corpus summary ──────────────────────────────────────────────────────

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ReviewCorpusSummaryTests(unittest.TestCase):

    def test_balance_and_reviewer_count(self):
        rows = [
            {"ai_correct": True, "reviewer_user_id": "a", "model_version": "v1"},
            {"ai_correct": True, "reviewer_user_id": "a", "model_version": "v1"},
            {"ai_correct": False, "reviewer_user_id": "b", "model_version": None},
        ]
        s = confidence_reviews.review_corpus_summary(rows)
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["ai_correct_true"], 2)
        self.assertEqual(s["ai_correct_false"], 1)
        self.assertEqual(s["agreement_rate"], round(2 / 3, 3))
        self.assertEqual(s["reviewers"], 2)
        self.assertEqual(s["by_model_version"],
                         {"v1": 2, "(unattributed)": 1})

    def test_empty_corpus_reports_no_rate(self):
        s = confidence_reviews.review_corpus_summary([])
        self.assertEqual(s["total"], 0)
        self.assertIsNone(s["agreement_rate"])

    def test_summary_declares_itself_non_blind(self):
        s = confidence_reviews.review_corpus_summary([])
        self.assertIs(s["blind"], False)
        self.assertEqual(s["selection_source"], "peer_review")


if __name__ == "__main__":
    unittest.main()
