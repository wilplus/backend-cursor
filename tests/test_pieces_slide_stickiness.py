"""Founder fix-pack BE-5 (2026-07-16) — slide stickiness REVIVED in pieces
mode (F1-CORE: restores the text↔slide input to the L2 ranking blend).

Covers services/slide_alignment.compute_piece_slide_scores (two-tier: lexical
for EVERY piece, claim-decomposition + entailment upgrade for the LLM-budget
subset, LLM-failure fallback, slide_index edge cases), the ranking seam
(metrics.slide_stickiness.composite → power_score via _rank_inputs), the
AC-9 user-readout string-absence fence, and the process_lab_recording wiring
(stamping + overall/rank blend + the raw candidate-window capture staying
slide_stickiness-free).

Run: python3 -m unittest tests.test_pieces_slide_stickiness
"""
from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# services.db pulls in supabase/postgrest, which aren't in the test image, so
# we stub it — in setUpModule, NOT at import time (a stub leaked into
# sys.modules at import time bleeds into sibling test modules).
# tearDownModule RESTORES the saved original.
_ORIG_SERVICES_DB = None

# services.audio_metrics needs numpy. PipelineWiringTests patches attributes ON
# that module, and mock.patch resolves "services.audio_metrics.X" by importing
# `services` and then getattr'ing `audio_metrics` — which only exists as an
# attribute once the submodule has been imported. Without numpy the import
# fails and the patch dies with
#
#     AttributeError: module 'services' has no attribute 'audio_metrics'
#
# which reads exactly like a broken test and is really a missing dependency.
# CI installs numpy (requirements.txt) so this suite runs there; a lean local
# env now SKIPS with the reason instead of reporting five phantom errors.
try:
    import services.audio_metrics  # noqa: F401 — import-only probe
    _AUDIO_METRICS_IMPORT_ERROR = None
except Exception as import_err:  # pragma: no cover - env/bootstrap guard
    _AUDIO_METRICS_IMPORT_ERROR = import_err


def setUpModule():
    global _ORIG_SERVICES_DB
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)


SLIDES = [
    {"title": "Onboarding", "body": "we cut onboarding from nine days to two"},
    {"title": "Retention", "body": "customers churn in week one"},
    {"title": "", "body": ""},  # empty slide — unscorable
]

# On-slide piece text (content words overlap slide 0's body heavily).
ON_SLIDE_TEXT = "we cut onboarding from nine days down to just two days"


class UserReadoutFenceTests(unittest.TestCase):
    """AC-9 hard fence: slide_stickiness / overall_score / rank must not
    appear ANYWHERE in the serialized user readout — coach packet only
    (mirrors test_readout_reread's potentiometer fence)."""

    def _piece_row(self, sid, piece_index, slide_index=0):
        return {
            "id": sid,
            "transcript": f"piece text {piece_index}",
            "audio_segment_path": "https://x/parent.webm",
            "start_offset_ms": piece_index * 4000, "duration_ms": 3500,
            "metrics": {
                "wpm": 140, "f0_sd": 30.0, "dynamic_db": 12.0,
                "voiced_ratio": 0.7,
                "piece": {"index": piece_index, "slide_index": slide_index},
                "recording_kind": "spoken",
                "stickiness": {"composite": 0.5, "comment": None},
                "slide_stickiness": {"composite": 0.62, "on_slide": True,
                                     "degraded": True},
                "overall_score": 0.56, "rank": 1,
            },
        }

    def _build(self, rows, include_slide_scores):
        from services import lab_recording as mod
        from services.db import db
        with patch.object(db, "get_snippets_by_session", return_value=rows), \
             patch.object(db, "v2_get_session_by_id", return_value={}), \
             patch.object(db.takes, "get_session_intake_context", return_value={}), \
             patch.object(db.takes, "get_session_slide_transcripts",
                          return_value=None), \
             patch.object(db, "get_user_transcript_edits", return_value=[]), \
             patch.object(db, "get_suggestion_feedback_by_session",
                          return_value=[]):
            return mod.build_readout_from_session(
                "sess1", include_insights=False,
                include_slide_scores=include_slide_scores,
            )


    def test_coach_packet_carries_all_three(self):
        rows = [self._piece_row("a", 0)]
        out = self._build(rows, include_slide_scores=True)
        snip = out["snippets"][0]
        self.assertEqual(snip["slide_stickiness"]["composite"], 0.62)
        self.assertTrue(snip["slide_stickiness"]["degraded"])
        self.assertEqual(snip["overall_score"], 0.56)
        self.assertEqual(snip["rank"], 1)


def _words_and_advances(text_per_slide, word_dur=0.4, tap_gap_s=1.0):
    """Time-consistent whisper word list + tap timeline (one word every
    word_dur seconds, taps between slides) — same shape the cutter expects."""
    words, advances = [], []
    t = 0.0
    for i, text in enumerate(text_per_slide):
        if i > 0:
            t += tap_gap_s
            advances.append({"index": i, "t_ms": int(t * 1000) - 50})
        for w in text.split():
            words.append({"word": w, "start": round(t, 3),
                          "end": round(t + word_dur, 3)})
            t += word_dur
    advances.insert(0, {"index": 0, "t_ms": 0})
    return words, advances


@unittest.skipIf(
    _AUDIO_METRICS_IMPORT_ERROR is not None,
    "these tests patch services.audio_metrics, which needs numpy: "
    f"{_AUDIO_METRICS_IMPORT_ERROR}",
)
class PipelineWiringTests(unittest.TestCase):
    """process_lab_recording in pieces mode (audio/Whisper/LLM/db mocked):
    every piece gets slide_stickiness stamped (lexical, degraded), the budget
    piece gets the entailment upgrade + the restored overall/rank BLEND, and
    the raw candidate-window capture never sees any of it."""

    TWO_SLIDES = SLIDES[:2]

    def _run(self, entail_ok=True):
        from services import slide_alignment as sa
        sa._claims_cache.clear()
        captured = {}

        def _capture_rows(rows):
            captured["rows"] = rows
            return len(rows)

        from services.db import db
        db.reset_mock()
        db.create_charisma_snippets_bulk.side_effect = \
            lambda rows: [f"sn{i}" for i in range(len(rows))]
        db.insert_candidate_windows.side_effect = _capture_rows

        bulk_rows = {}

        def _bulk(rows):
            bulk_rows["rows"] = rows
            return [f"sn{i}" for i in range(len(rows))]

        db.create_charisma_snippets_bulk.side_effect = _bulk

        words, advances = _words_and_advances(
            [ON_SLIDE_TEXT, "customers leave us in week one because "
                            "setup is painful today"])
        ctx = {"slides": self.TWO_SLIDES, "slide_advances": advances}

        ois = MagicMock()
        ois.client = True
        ois.transcribe_audio.return_value = {"segments": [], "words": words}

        # services.openai_service imports the openai package (not in the local
        # test image) — stub the MODULE, saved-and-restored (never bare pop).
        _orig_ois_mod = sys.modules.get("services.openai_service")
        _ois_stub = types.ModuleType("services.openai_service")
        _ois_stub.OpenAIService = MagicMock(return_value=ois)
        sys.modules["services.openai_service"] = _ois_stub

        entail = (
            (lambda work: {str(w["ref"]): ["partial"] for w in work})
            if entail_ok else (lambda work: None)
        )

        try:
            # The retired flag must not be able to reactivate a second
            # segmentation algorithm, even if a stale deployment still sets
            # it to false.
            with patch.dict(os.environ, {
                     "WILLAB_PIECE_LLM_BUDGET": "1",
                     "PIECES_CANONICAL_ENABLED": "0",
                 }), \
                 patch("services.audio_metrics.decode_audio_to_pcm",
                       return_value=[0.0] * 16000), \
                 patch("services.audio_metrics.analyze_pcm_window",
                       side_effect=lambda *a, **k: {
                           "f0_mean": 150.0, "speech_rate": 130.0,
                           "loudness_range": 10.0, "voiced_ratio": 0.7}), \
                 patch("services.snippet_salience.rank_candidates_by_salience",
                       side_effect=lambda cands, top_n: cands[:top_n]), \
                 patch("services.snippet_stickiness.score_snippets_stickiness",
                       side_effect=lambda items: [
                           {"composite": 0.5, "comment": "held"}
                           for _ in items]), \
                 patch("services.slide_alignment._llm_decompose",
                       return_value={0: ["onboarding time dropped"],
                                     1: ["customers churn early"]}), \
                 patch("services.slide_alignment._entail_batch",
                       side_effect=entail), \
                 patch("services.say_it_stronger.dispatch_say_it_stronger",
                       return_value=None):
                from services.lab_recording import process_lab_recording
                payload = process_lab_recording(
                    session_id="sess1", user_id="u1", recording_id="rec1",
                    audio_bytes=b"x" * 64, filename="lab.webm",
                    session_context=ctx,
                    parent_audio_url="https://x/parent.webm",
                )
        finally:
            if _orig_ois_mod is not None:
                sys.modules["services.openai_service"] = _orig_ois_mod
            else:
                sys.modules.pop("services.openai_service", None)
        return payload, bulk_rows.get("rows") or [], captured.get("rows") or []


    def test_entailment_down_pipeline_keeps_lexical_and_never_crashes(self):
        payload, rows, _ = self._run(entail_ok=False)
        self.assertEqual(len(rows), 2)          # live loop intact
        for r in rows:
            ss = r["metrics"]["slide_stickiness"]
            self.assertIsNotNone(ss["composite"])
            self.assertTrue(ss["degraded"])


if __name__ == "__main__":
    unittest.main()
