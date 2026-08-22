"""Founder fix-pack BE-5 (2026-07-16) — slide stickiness REVIVED in pieces
mode (F1-CORE: restores the text↔slide input to the L2 ranking blend).

Covers services/slide_alignment.compute_piece_slide_scores (two-tier: lexical
for EVERY piece, claim-decomposition + entailment upgrade for the LLM-budget
subset, LLM-failure fallback, slide_index edge cases), the ranking seam
(metrics.slide_stickiness.composite → power_score via _rank_inputs), the
AC-9 user-readout string-absence fence, and the process_lab_recording wiring
(stamping + overall/rank blend + the raw candidate-window capture staying
slide_stickiness-free).

Run: python3 -m unittest test_pieces_slide_stickiness
"""
from __future__ import annotations

import json
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
# Off-slide piece text (no content-word overlap with any slide).
OFF_SLIDE_TEXT = "my grandmother's garden grows tomatoes every single summer"


def _piece(text, slide_index, duration_ms=4000):
    return {"transcript": text, "duration_ms": duration_ms,
            "slide_index": slide_index}


class ComputePieceSlideScoresTests(unittest.TestCase):
    """The pure/mocked-LLM core: services/slide_alignment.py."""

    def setUp(self):
        from services import slide_alignment as sa
        sa._claims_cache.clear()

    def test_lexical_tier_scores_every_piece_degraded(self):
        from services.slide_alignment import compute_piece_slide_scores
        # No budget → nothing may touch the LLM; every valid piece still
        # carries a deterministic lexical composite, marked degraded.
        with patch("services.slide_alignment._llm_decompose") as dec, \
             patch("services.slide_alignment._entail_batch") as ent:
            out = compute_piece_slide_scores(
                [_piece(ON_SLIDE_TEXT, 0), _piece(OFF_SLIDE_TEXT, 1)],
                SLIDES, llm_budget_idx=set())
        dec.assert_not_called()
        ent.assert_not_called()
        self.assertEqual(out[0]["composite"], 1.0)   # covered lexically
        self.assertTrue(out[0]["on_slide"])
        self.assertTrue(out[0]["degraded"])
        self.assertEqual(out[1]["composite"], 0.0)   # nothing overlaps
        self.assertFalse(out[1]["on_slide"])
        self.assertTrue(out[1]["degraded"])

    def test_budget_subset_upgraded_via_entailment(self):
        from services.slide_alignment import compute_piece_slide_scores
        # Budget piece 0: entailment says partial → 0.5, degraded=False —
        # a DIFFERENT value than its lexical 1.0, proving the upgrade
        # actually replaced the lexical verdict. Piece 1 stays lexical.
        with patch("services.slide_alignment._llm_decompose",
                   return_value={0: ["onboarding time dropped"]}), \
             patch("services.slide_alignment._entail_batch",
                   side_effect=lambda work: {
                       str(w["ref"]): ["partial"] for w in work}):
            out = compute_piece_slide_scores(
                [_piece(ON_SLIDE_TEXT, 0), _piece(ON_SLIDE_TEXT, 1)],
                SLIDES, llm_budget_idx={0})
        self.assertEqual(out[0]["composite"], 0.5)
        self.assertFalse(out[0]["degraded"])
        self.assertTrue(out[0]["on_slide"])          # 0.5 >= threshold
        self.assertTrue(out[1]["degraded"])          # non-budget: lexical

    def test_one_decomposition_per_slide_however_many_pieces(self):
        from services.slide_alignment import compute_piece_slide_scores
        calls = []

        def fake_decompose(slides_by_index):
            calls.append(dict(slides_by_index))
            return {i: ["a claim"] for i in slides_by_index}

        with patch("services.slide_alignment._llm_decompose",
                   side_effect=fake_decompose), \
             patch("services.slide_alignment._entail_batch",
                   side_effect=lambda work: {
                       str(w["ref"]): ["covered"] for w in work}):
            compute_piece_slide_scores(
                [_piece(ON_SLIDE_TEXT, 0), _piece(ON_SLIDE_TEXT, 0),
                 _piece(ON_SLIDE_TEXT, 0)],
                SLIDES, llm_budget_idx={0, 1, 2})
        # Three budget pieces, ONE slide → one decompose call, one slide in it.
        self.assertEqual(len(calls), 1)
        self.assertEqual(set(calls[0]), {0})

    def test_entailment_failure_keeps_lexical_tier(self):
        from services.slide_alignment import compute_piece_slide_scores
        with patch("services.slide_alignment._llm_decompose",
                   return_value={0: ["a claim"]}), \
             patch("services.slide_alignment._entail_batch",
                   return_value=None):                 # LLM down
            out = compute_piece_slide_scores(
                [_piece(ON_SLIDE_TEXT, 0)], SLIDES, llm_budget_idx={0})
        self.assertEqual(out[0]["composite"], 1.0)     # lexical stands
        self.assertTrue(out[0]["degraded"])

    def test_decompose_unavailable_keeps_lexical_tier(self):
        from services.slide_alignment import compute_piece_slide_scores
        with patch("services.slide_alignment._llm_decompose",
                   return_value=None), \
             patch("services.slide_alignment._entail_batch") as ent:
            out = compute_piece_slide_scores(
                [_piece(ON_SLIDE_TEXT, 0)], SLIDES, llm_budget_idx={0})
        ent.assert_not_called()                        # no claims → no work
        self.assertEqual(out[0]["composite"], 1.0)
        self.assertTrue(out[0]["degraded"])

    def test_llm_raise_never_crashes(self):
        from services.slide_alignment import compute_piece_slide_scores
        with patch("services.slide_alignment.decompose_slides_to_claims",
                   side_effect=RuntimeError("boom")):
            out = compute_piece_slide_scores(
                [_piece(ON_SLIDE_TEXT, 0)], SLIDES, llm_budget_idx={0})
        self.assertEqual(out[0]["composite"], 1.0)     # lexical tier kept
        self.assertTrue(out[0]["degraded"])

    def test_slide_index_none_out_of_range_or_empty_slide(self):
        from services.slide_alignment import compute_piece_slide_scores
        out = compute_piece_slide_scores(
            [_piece(ON_SLIDE_TEXT, None),   # deckless-style piece
             _piece(ON_SLIDE_TEXT, 9),      # out of range
             _piece(ON_SLIDE_TEXT, -1),     # negative
             _piece(ON_SLIDE_TEXT, 2),      # empty slide text
             _piece(ON_SLIDE_TEXT, True)],  # bool is not an index
            SLIDES, llm_budget_idx=set(range(5)))
        for i in range(5):
            self.assertIsNone(out[i]["composite"], msg=f"piece {i}")
            self.assertFalse(out[i]["on_slide"])

    def test_no_slides_returns_all_null(self):
        from services.slide_alignment import compute_piece_slide_scores
        for slides in ([], None):
            out = compute_piece_slide_scores(
                [_piece(ON_SLIDE_TEXT, 0)], slides, llm_budget_idx={0})
            self.assertIsNone(out[0]["composite"])

    def test_word_floor_abstains_to_null(self):
        from services.slide_alignment import compute_piece_slide_scores
        out = compute_piece_slide_scores(
            [_piece("nine days two", 0)], SLIDES)      # 3 words < floor
        self.assertIsNone(out[0]["composite"])

    def test_aligned_to_input_length(self):
        from services.slide_alignment import compute_piece_slide_scores
        pieces = [_piece(ON_SLIDE_TEXT, 0), _piece(OFF_SLIDE_TEXT, None),
                  _piece(ON_SLIDE_TEXT, 1)]
        out = compute_piece_slide_scores(pieces, SLIDES)
        self.assertEqual(len(out), len(pieces))


class RankingReceivesCompositeTests(unittest.TestCase):
    """The L2 seam: metrics.slide_stickiness.composite must MOVE power_score
    again (w_s = 0.6 — the blend term pieces mode had starved to None)."""

    def _metrics(self, composite):
        m = {"overall_score": 0.4, "rank": 1}
        if composite is not None:
            m["slide_stickiness"] = {"composite": composite,
                                     "on_slide": True, "degraded": True}
        return m

    def test_power_score_moves_with_composite(self):
        from services.cross_take_selection import _rank_inputs
        from services.power_phrase_ranking import power_score
        without = power_score(**_rank_inputs(
            {"metrics": self._metrics(None), "coach_label": None}))
        with_it = power_score(**_rank_inputs(
            {"metrics": self._metrics(0.8), "coach_label": None}))
        self.assertAlmostEqual(with_it - without, 0.6 * 0.8, places=6)

    def test_rank_inputs_unwraps_the_dict_shape(self):
        from services.cross_take_selection import _rank_inputs
        inp = _rank_inputs({"metrics": self._metrics(0.62)})
        self.assertEqual(inp["slide_stickiness"], 0.62)
        self.assertEqual(inp["activation"], 0.4)


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
             patch.object(db, "get_session_intake_context", return_value={}), \
             patch.object(db, "get_session_slide_transcripts",
                          return_value=None), \
             patch.object(db, "get_user_transcript_edits", return_value=[]), \
             patch.object(db, "get_suggestion_feedback_by_session",
                          return_value=[]):
            return mod.build_readout_from_session(
                "sess1", include_insights=False,
                include_slide_scores=include_slide_scores,
            )

    def test_user_readout_never_carries_slide_stickiness_overall_or_rank(self):
        rows = [self._piece_row("a", 0), self._piece_row("b", 1)]
        out = self._build(rows, include_slide_scores=False)
        raw = json.dumps(out)
        self.assertNotIn("slide_stickiness", raw)
        self.assertNotIn("overall_score", raw)
        self.assertNotIn("rank", raw)

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

    def test_pieces_stamped_lexical_all_entailment_budget(self):
        payload, rows, _ = self._run()
        self.assertEqual(len(rows), 2)          # one piece per slide
        m0, m1 = rows[0]["metrics"], rows[1]["metrics"]
        # Budget piece (index 0): entailment 'partial' → 0.5, not degraded.
        self.assertEqual(m0["slide_stickiness"]["composite"], 0.5)
        self.assertFalse(m0["slide_stickiness"]["degraded"])
        # Non-budget piece: lexical tier, degraded, still scored.
        self.assertIsNotNone(m1["slide_stickiness"]["composite"])
        self.assertTrue(m1["slide_stickiness"]["degraded"])

    def test_overall_and_rank_blend_restored_for_budget_pieces(self):
        _, rows, _ = self._run()
        m0, m1 = rows[0]["metrics"], rows[1]["metrics"]
        # overall = 0.5·#1 + 0.5·#2 = 0.5·0.5 + 0.5·0.5 = 0.5 (the blend is
        # LIVE again — before BE-5, #2 was None so overall collapsed to #1).
        self.assertEqual(m0["overall_score"], 0.5)
        self.assertEqual(m0["rank"], 1)
        # Non-budget pieces still omit overall/rank (no #1 delivery signal —
        # they compete on coach direction + slide_stickiness only).
        self.assertNotIn("overall_score", m1)
        self.assertNotIn("rank", m1)

    def test_entailment_down_pipeline_keeps_lexical_and_never_crashes(self):
        payload, rows, _ = self._run(entail_ok=False)
        self.assertEqual(len(rows), 2)          # live loop intact
        for r in rows:
            ss = r["metrics"]["slide_stickiness"]
            self.assertIsNotNone(ss["composite"])
            self.assertTrue(ss["degraded"])

    def test_candidate_capture_never_sees_slide_stickiness(self):
        _, _, cap_rows = self._run()
        self.assertTrue(cap_rows)               # capture did run
        raw = json.dumps(cap_rows, default=str)
        self.assertNotIn("slide_stickiness", raw)
        self.assertNotIn("overall_score", raw)

    def test_immediate_201_payload_is_fence_clean(self):
        payload, _, _ = self._run()
        raw = json.dumps(payload)
        self.assertNotIn("slide_stickiness", raw)
        self.assertNotIn("overall_score", raw)
        self.assertNotIn("rank", raw)


if __name__ == "__main__":
    unittest.main()
