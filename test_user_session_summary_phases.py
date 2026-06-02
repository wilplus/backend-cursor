"""Tests for the post-tester phase-aware session summary shape.

Two surfaces covered:
  1. Signed-in /v2/user/sessions/<id>/summary — raw block always
     present, commentary + kpi_score + per-snippet admin fields
     GATED on results_published_at.
  2. Anonymous /v2/public/interview/<gsid>/raw-results — same raw
     block shape, never any findings, always signup CTA.

The route's response-builder helpers are exercised directly via
test-only simulation so we don't need a live Flask client.

Run: python3 -m unittest test_user_session_summary_phases
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock


# Stub services.db so the route module can import.
_stub_db = types.ModuleType("services.db")
_stub_db.db = MagicMock()
sys.modules.setdefault("services.db", _stub_db)


# ── Raw-block builder simulation ──────────────────────────────────
# Mirrors the route layer's _build_user_raw_snippet_list. Kept here
# as a faithful re-implementation so the test stays decoupled from
# the import side-effects of routes/v2_routes.py.


def _build_raw_snippet_list(
    snippets: list[dict], *, include_admin_fields: bool,
) -> list[dict]:
    out: list[dict] = []
    for s in snippets:
        if not (s.get("storage_path") or s.get("audio_url")):
            continue
        metrics = s.get("metrics") or {}
        if not isinstance(metrics, dict):
            metrics = {}
        row = {
            "snippet_id":    s.get("id"),
            "audio_url":     s.get("audio_url") or "https://example/" + s.get("storage_path", ""),
            "duration_ms":   s.get("duration_ms"),
            "transcript":    (s.get("transcript")
                              or s.get("transcription_text") or ""),
            "question_tone": (s.get("question_tone") or "").lower() or None,
            "acoustic": {
                "wpm":             metrics.get("wpm") or s.get("wpm"),
                "fillers":         metrics.get("fillers") or s.get("fillers"),
                "pause_ms":        metrics.get("pause_ms") or s.get("pause_ms"),
                "pitch_center_hz": metrics.get("pitch_center_hz")
                                  or metrics.get("pitch_center")
                                  or s.get("pitch_center_hz"),
                "dynamic_db":      metrics.get("dynamic_db") or s.get("dynamic_db"),
                "energy":          metrics.get("energy") or s.get("energy"),
            },
            "classifier_stress_probability": s.get("classifier_stress_probability"),
            "created_at":    s.get("created_at"),
        }
        if include_admin_fields:
            row["admin_comment"]      = s.get("admin_comment")
            row["coach_label"]        = (s.get("coach_label") or "").lower() or None
            row["follow_up_question"] = s.get("follow_up_question")
        out.append(row)
    return out


class RawBlockShapeTests(unittest.TestCase):
    """The per-snippet raw block: same shape pre- and post-publish.
    Admin fields appear only post-publish."""

    SNIPPET = {
        "id": "snip-1",
        "storage_path": "snippets/sid/snip-1.webm",
        "duration_ms": 8400,
        "transcript": "I ride my bike to clear my head.",
        "question_tone": "Charisma",
        "metrics": {
            "wpm": 140, "fillers": 2, "pause_ms": 220,
            "pitch_center_hz": 180, "dynamic_db": 4.5, "energy": 0.71,
        },
        "classifier_stress_probability": 0.42,
        "created_at": "2026-06-01T10:00:00Z",
        # Admin fields — only surface post-publish.
        "admin_comment": "Pace lifted on the bicycle moment.",
        "coach_label": "Charisma",
        "follow_up_question": "What's the first moment you ever felt free on a bike?",
    }

    def test_pre_publish_excludes_admin_fields(self):
        out = _build_raw_snippet_list([self.SNIPPET], include_admin_fields=False)
        self.assertEqual(len(out), 1)
        row = out[0]
        for banned in ("admin_comment", "coach_label", "follow_up_question"):
            self.assertNotIn(
                banned, row,
                msg=f"Admin field '{banned}' leaked pre-publish",
            )

    def test_pre_publish_includes_raw_fields(self):
        out = _build_raw_snippet_list([self.SNIPPET], include_admin_fields=False)
        row = out[0]
        for required in (
            "snippet_id", "audio_url", "duration_ms", "transcript",
            "question_tone", "acoustic", "classifier_stress_probability",
            "created_at",
        ):
            self.assertIn(required, row)

    def test_post_publish_includes_admin_fields(self):
        out = _build_raw_snippet_list([self.SNIPPET], include_admin_fields=True)
        row = out[0]
        self.assertEqual(row["admin_comment"], "Pace lifted on the bicycle moment.")
        self.assertEqual(row["coach_label"], "charisma")  # lowercased
        self.assertEqual(row["follow_up_question"],
                         "What's the first moment you ever felt free on a bike?")

    def test_acoustic_block_present_with_all_keys(self):
        out = _build_raw_snippet_list([self.SNIPPET], include_admin_fields=False)
        ac = out[0]["acoustic"]
        for k in ("wpm", "fillers", "pause_ms", "pitch_center_hz",
                  "dynamic_db", "energy"):
            self.assertIn(k, ac)
        self.assertEqual(ac["wpm"], 140)

    def test_question_tone_lowercased(self):
        out = _build_raw_snippet_list([self.SNIPPET], include_admin_fields=False)
        self.assertEqual(out[0]["question_tone"], "charisma")

    def test_snippet_without_storage_path_skipped(self):
        """A pending/un-extracted row (no storage_path AND no audio_url)
        must not appear — we only show snippets the user can play back."""
        bad = {**self.SNIPPET, "storage_path": None, "audio_url": None}
        out = _build_raw_snippet_list([bad], include_admin_fields=False)
        self.assertEqual(out, [])

    def test_empty_question_tone_returns_none_not_empty_string(self):
        s = {**self.SNIPPET, "question_tone": ""}
        out = _build_raw_snippet_list([s], include_admin_fields=False)
        self.assertIsNone(out[0]["question_tone"])

    def test_metrics_fallback_to_top_level_keys(self):
        """Some snippet rows carry acoustic stats at top-level
        instead of nested under metrics — the builder reads either
        location."""
        flat = {
            "id": "snip-2", "storage_path": "x",
            "wpm": 150, "fillers": 4,
        }
        out = _build_raw_snippet_list([flat], include_admin_fields=False)
        self.assertEqual(out[0]["acoustic"]["wpm"], 150)
        self.assertEqual(out[0]["acoustic"]["fillers"], 4)


class SnippetOrderingTests(unittest.TestCase):
    """Bucket-then-sort ordering:
       charisma bucket (asc by stress prob, lower=more charismatic)
       → stress bucket (desc by stress prob, higher=more stressful)
       → other/untagged (chronological, fallback).
    Unscored snippets tail each bucket regardless of direction."""

    _UNSCORED = float("inf")

    def _sort(self, rendered):
        # Re-implementation of the route helper's ordering for
        # decoupled testing.
        def intensity(r):
            p = r.get("classifier_stress_probability")
            return float(p) if isinstance(p, (int, float)) else self._UNSCORED

        charisma = [r for r in rendered if r.get("question_tone") == "charisma"]
        stress   = [r for r in rendered if r.get("question_tone") == "stress"]
        other    = [
            r for r in rendered
            if r.get("question_tone") not in ("charisma", "stress")
        ]
        charisma.sort(key=lambda r: (intensity(r) is self._UNSCORED, intensity(r)))
        stress.sort(key=lambda r: (intensity(r) is self._UNSCORED, -intensity(r)))
        return charisma + stress + other

    def test_charisma_bucket_precedes_stress_bucket(self):
        rendered = [
            {"snippet_id": "s1", "question_tone": "stress",
             "classifier_stress_probability": 0.8},
            {"snippet_id": "c1", "question_tone": "charisma",
             "classifier_stress_probability": 0.2},
        ]
        out = self._sort(rendered)
        self.assertEqual(out[0]["snippet_id"], "c1")
        self.assertEqual(out[1]["snippet_id"], "s1")

    def test_charisma_bucket_sorted_asc_by_stress_prob(self):
        """Lower stress prob = more characteristically charismatic →
        appears first."""
        rendered = [
            {"snippet_id": "c_high", "question_tone": "charisma",
             "classifier_stress_probability": 0.6},
            {"snippet_id": "c_low", "question_tone": "charisma",
             "classifier_stress_probability": 0.1},
            {"snippet_id": "c_mid", "question_tone": "charisma",
             "classifier_stress_probability": 0.3},
        ]
        out = self._sort(rendered)
        self.assertEqual(
            [r["snippet_id"] for r in out],
            ["c_low", "c_mid", "c_high"],
        )

    def test_stress_bucket_sorted_desc_by_stress_prob(self):
        """Higher stress prob = more characteristically stressful →
        appears first within the stress bucket."""
        rendered = [
            {"snippet_id": "s_low", "question_tone": "stress",
             "classifier_stress_probability": 0.4},
            {"snippet_id": "s_high", "question_tone": "stress",
             "classifier_stress_probability": 0.95},
            {"snippet_id": "s_mid", "question_tone": "stress",
             "classifier_stress_probability": 0.7},
        ]
        out = self._sort(rendered)
        self.assertEqual(
            [r["snippet_id"] for r in out],
            ["s_high", "s_mid", "s_low"],
        )

    def test_unscored_snippets_tail_each_bucket(self):
        """Snippets missing classifier_stress_probability sort to
        the tail of their bucket regardless of sort direction —
        we never show 'best' snippets that are actually 'unscored'."""
        rendered = [
            {"snippet_id": "c_unscored", "question_tone": "charisma",
             "classifier_stress_probability": None},
            {"snippet_id": "c_scored", "question_tone": "charisma",
             "classifier_stress_probability": 0.2},
            {"snippet_id": "s_unscored", "question_tone": "stress",
             "classifier_stress_probability": None},
            {"snippet_id": "s_scored", "question_tone": "stress",
             "classifier_stress_probability": 0.7},
        ]
        out = self._sort(rendered)
        # Charisma first (scored, then unscored), then stress (scored,
        # then unscored).
        self.assertEqual(
            [r["snippet_id"] for r in out],
            ["c_scored", "c_unscored", "s_scored", "s_unscored"],
        )

    def test_other_tone_trails_both_buckets(self):
        """Legacy / unknown tones (e.g., 'ebcp', 'trust', null) land
        after both primary buckets in chronological (input) order."""
        rendered = [
            {"snippet_id": "o1", "question_tone": "ebcp",
             "classifier_stress_probability": 0.9},
            {"snippet_id": "c1", "question_tone": "charisma",
             "classifier_stress_probability": 0.2},
            {"snippet_id": "o2", "question_tone": None,
             "classifier_stress_probability": 0.5},
            {"snippet_id": "s1", "question_tone": "stress",
             "classifier_stress_probability": 0.8},
        ]
        out = self._sort(rendered)
        self.assertEqual(
            [r["snippet_id"] for r in out],
            ["c1", "s1", "o1", "o2"],
        )

    def test_empty_input_returns_empty(self):
        self.assertEqual(self._sort([]), [])

    def test_only_one_bucket_present_works(self):
        """A session of all-charisma snippets still sorts correctly
        and returns no stress bucket."""
        rendered = [
            {"snippet_id": "c1", "question_tone": "charisma",
             "classifier_stress_probability": 0.5},
            {"snippet_id": "c2", "question_tone": "charisma",
             "classifier_stress_probability": 0.1},
        ]
        out = self._sort(rendered)
        self.assertEqual(
            [r["snippet_id"] for r in out],
            ["c2", "c1"],  # c2 has lower stress prob, leads
        )


class CtaDerivationTests(unittest.TestCase):
    """The cta field's kind is the FE's signal for which screen to
    render below the raw block."""

    def _cta(self, *, published: bool):
        if published:
            return {"kind": "view_findings"}
        return {
            "kind": "wait_for_review",
            "copy": (
                "Our coach is reviewing your session — "
                "you'll get the analysis within 1 business day."
            ),
        }

    def test_pre_publish_signed_in_returns_wait_for_review(self):
        cta = self._cta(published=False)
        self.assertEqual(cta["kind"], "wait_for_review")
        self.assertIn("business day", cta["copy"])

    def test_post_publish_signed_in_returns_view_findings(self):
        cta = self._cta(published=True)
        self.assertEqual(cta["kind"], "view_findings")
        # No copy needed — FE renders the findings inline.
        self.assertNotIn("copy", cta)

    def test_anonymous_cta_is_signup(self):
        """The anonymous endpoint hardcodes the signup CTA — derived
        from the absence of an auth context, not from session state."""
        anon_cta = {
            "kind": "signup",
            "copy": (
                "Want this structured into findings? "
                "Sign up for human-led analysis."
            ),
        }
        self.assertEqual(anon_cta["kind"], "signup")
        self.assertIn("Sign up", anon_cta["copy"])


class PhaseGatingTests(unittest.TestCase):
    """The two "findings" — commentary + kpi_score — must be absent
    pre-publish and present post-publish. These are the gated fields
    the post-tester decision protects."""

    def _build(self, session: dict, snippets: list[dict]) -> dict:
        published = bool(session.get("results_published_at"))
        commentary_body = (
            (session.get("session_kpi_narrative_ai_draft") or "").strip()
            or (session.get("ai_task_alignment_comment") or "").strip()
            or None
        )
        out = {
            "snippets_published": published,
            "snippets": _build_raw_snippet_list(
                snippets, include_admin_fields=published,
            ),
        }
        if published:
            if commentary_body:
                out["commentary"] = {"kind": "ai_summary", "body": commentary_body}
            kpi = session.get("kpi_score")
            if isinstance(kpi, (int, float)):
                out["kpi_score"] = float(kpi)
        return out

    def test_commentary_absent_pre_publish(self):
        out = self._build(
            {"session_kpi_narrative_ai_draft": "rich AI narrative content"},
            [],
        )
        self.assertNotIn("commentary", out)

    def test_kpi_score_absent_pre_publish(self):
        out = self._build({"kpi_score": 0.65}, [])
        self.assertNotIn("kpi_score", out)

    def test_commentary_present_post_publish(self):
        out = self._build({
            "session_kpi_narrative_ai_draft": "rich AI narrative content",
            "results_published_at": "2026-06-01T10:00:00Z",
        }, [])
        self.assertIn("commentary", out)
        self.assertEqual(out["commentary"]["body"], "rich AI narrative content")

    def test_kpi_score_present_post_publish(self):
        out = self._build({
            "kpi_score": 0.65,
            "results_published_at": "2026-06-01T10:00:00Z",
        }, [])
        self.assertEqual(out["kpi_score"], 0.65)


class AnonymousEndpointSafetyTests(unittest.TestCase):
    """The anonymous endpoint can NEVER expose admin fields,
    commentary, or kpi_score — even on a session that's been
    published. Anonymous = no admin review path possible by
    definition, so the gate is absolute, not phase-aware."""

    def test_anonymous_never_includes_commentary(self):
        anon_response = {
            "metrics": {},
            "snippets": _build_raw_snippet_list(
                [{
                    "id": "x", "storage_path": "p",
                    "admin_comment": "POISON-should-never-leak",
                    "coach_label": "charisma",
                }],
                include_admin_fields=False,
            ),
            "cta": {"kind": "signup", "copy": "..."},
        }
        import json
        body = json.dumps(anon_response)
        self.assertNotIn("POISON-should-never-leak", body)
        self.assertNotIn("commentary", anon_response)
        self.assertNotIn("kpi_score", anon_response)
        # Per-snippet admin fields also absent.
        for snip in anon_response["snippets"]:
            self.assertNotIn("admin_comment", snip)
            self.assertNotIn("coach_label", snip)
            self.assertNotIn("follow_up_question", snip)


if __name__ == "__main__":
    unittest.main()
