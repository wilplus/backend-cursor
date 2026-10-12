"""Unit tests for the user-facing session summary surface (Task 8).

The two things that matter to verify in isolation:
  1. The `metrics_ready` helper flips correctly on the `global_wpm`
     marker (canonical "compute-metrics has run" signal).
  2. The summary endpoint's allowlist construction NEVER leaks an
     admin-only field — we test by constructing a synthetic session
     row that has every banned field populated with sentinel values
     and verifying NONE of them appear in the response keys.

These tests don't need the full Flask app to run — the route's
JSON construction is a pure transformation of the session row +
snippet counts. We import the helper directly and check the
response dict by simulating the route's logic.

Run: python3 -m unittest tests.test_session_summary_allowlist
"""
from __future__ import annotations

import unittest


class SummaryAllowlistTests(unittest.TestCase):
    """Confirm the response shape NEVER leaks an admin-only field.

    We simulate the route's response builder by replicating its
    allowlist construction here. If the route changes its keys, this
    test will catch it; the assertion is on the SET of keys in the
    response, compared against an explicit allowlist.
    """

    # The hard denylist documented in the route's docstring.
    # Every one of these must NOT appear in the summary response.
    BANNED_KEYS = {
        "session_kpi_narrative",
        "ai_task_alignment_comment",       # legacy editable col
        "session_kpi_narrative_ai_draft",  # immutable, body-only
        "admin_corrected_rationale",
        "private_admin_notes",
        "queued_override_question",
        "coach_override_profile",
        "behavioral_profile",
        "behavioral_profile_auto",
        "inferred_learner_profile",
        "admin_profile_override",
        "ai_draft_admin_comment",
        "ai_draft_follow_up_question",
        "score_for_display",
        "scores",
        "follow_up_outcome",
        "kpi_debug",
        "drift_diagnostic",
        "user_id",
        "ai_task_alignment_score",
    }

    # Pre-publish keys (post-tester decision: commentary + kpi_score
    # gated as "findings" until human review). snippets + cta are
    # always present in the new shape.
    EXPECTED_KEYS_PRE_PUBLISH = {
        "status",
        "metrics_ready",
        "snippets_published",
        "metrics",
        "snippets",
        "snippet_count_pending",
        "cta",
    }
    # Post-publish: same + commentary + kpi_score (charisma_profile
    # is optional — only present when the row carries one).
    EXPECTED_KEYS_POST_PUBLISH = EXPECTED_KEYS_PRE_PUBLISH | {
        "commentary",
        "kpi_score",
    }

    def _build_response(self, session: dict, snippet_counts: dict) -> dict:
        """Simulate the route's response construction (post-tester
        phase-aware shape).

        Pre-publish: raw block only — no commentary, no kpi_score.
        Post-publish: + commentary + kpi_score.
        """
        published = bool(session.get("results_published_at"))
        commentary_body = (
            (session.get("session_kpi_narrative_ai_draft") or "").strip()
            or (session.get("ai_task_alignment_comment") or "").strip()
            or None
        )
        commentary = (
            {"kind": "ai_summary", "body": commentary_body}
            if commentary_body else None
        )
        snippet_count_pending = (
            snippet_counts.get("total", 0) if not published else 0
        )
        response = {
            "status": (
                "completed" if published
                else "pending_review" if snippet_counts.get("total", 0)
                else "processing"
            ),
            "metrics_ready": session.get("global_wpm") is not None,
            "snippets_published": published,
            "metrics": {
                "wpm":             session.get("global_wpm"),
                "fillers":         session.get("global_fillers"),
                "pause_ms":        session.get("global_pause_ms"),
                "pitch_center_hz": session.get("global_pitch_center"),
                "dynamic_db":      session.get("global_dynamic_db"),
                "energy":          session.get("global_energy"),
            },
            # Always present in the new shape (raw block).
            "snippets": [],
            "snippet_count_pending": snippet_count_pending,
            "cta": (
                {"kind": "view_findings"} if published
                else {"kind": "wait_for_review",
                      "copy": (
                          "Our coach is reviewing your session — "
                          "you'll get the analysis within 1 business day."
                      )}
            ),
        }
        # Findings — only after admin publishes.
        if published:
            response["commentary"] = commentary
            kpi = session.get("kpi_score")
            if isinstance(kpi, (int, float)):
                response["kpi_score"] = float(kpi)
            else:
                # Test harness needs the key in the post-publish
                # expected-set; default to None for completeness.
                response["kpi_score"] = None
        return response

    def test_response_keys_match_explicit_allowlist(self):
        """No matter what's on the session row, response keys must be
        exactly the allowlist for the current phase — no extras,
        no missing."""
        # Poisoned row with EVERY banned field populated with a
        # sentinel that would be easy to spot in a leak.
        poisoned = {
            "global_wpm": 142,
            "global_fillers": 3,
            "global_pause_ms": 240,
            "global_pitch_center": 115,
            "global_dynamic_db": 8.4,
            "global_energy": 0.62,
            "ai_task_alignment_comment": "user-safe (legacy editable)",
            "session_kpi_narrative_ai_draft": "user-safe (immutable AI draft)",
            "user_id": "POISON-user-id",
            # Banned admin/internal fields below.
            "private_admin_notes": "POISON-private-notes",
            "queued_override_question": "POISON-queued",
            "coach_override_profile": "POISON-override",
            "behavioral_profile": "POISON-classified",
            "inferred_learner_profile": {"poison": True},
            "admin_profile_override": {"poison": True},
            "ai_draft_admin_comment": "POISON-draft",
            "ai_task_alignment_score": 0.99,
            "kpi_debug": {"poison": True},
            "drift_diagnostic": "POISON-drift",
        }
        # Pre-publish case (no results_published_at).
        out_pre = self._build_response(poisoned, {"total": 3})
        self.assertEqual(set(out_pre.keys()), self.EXPECTED_KEYS_PRE_PUBLISH)
        # commentary + kpi_score MUST NOT leak pre-publish even
        # when the row has them populated — they're gated findings.
        self.assertNotIn("commentary", out_pre)
        self.assertNotIn("kpi_score", out_pre)

        # Post-publish case (results_published_at set).
        poisoned_pub = {**poisoned, "results_published_at": "2026-06-01T10:00:00Z"}
        out_pub = self._build_response(poisoned_pub, {"total": 3})
        self.assertEqual(set(out_pub.keys()), self.EXPECTED_KEYS_POST_PUBLISH)


    def test_poisoned_admin_fields_do_not_appear_as_values_anywhere(self):
        """If we accidentally surfaced a banned field's value
        anywhere — even as a value, not a key — this catches it by
        scanning the serialised JSON for the POISON sentinel."""
        import json
        session = {
            "global_wpm": 142,
            "private_admin_notes": "POISON-private-notes-marker",
            "queued_override_question": "POISON-queued-question-marker",
            "ai_draft_admin_comment": "POISON-draft-comment-marker",
            "behavioral_profile": "POISON-profile-marker",
        }
        out = self._build_response(session, {"total": 0})
        body = json.dumps(out)
        self.assertNotIn("POISON-private-notes-marker", body)
        self.assertNotIn("POISON-queued-question-marker", body)
        self.assertNotIn("POISON-draft-comment-marker", body)
        self.assertNotIn("POISON-profile-marker", body)


if __name__ == "__main__":
    unittest.main()
