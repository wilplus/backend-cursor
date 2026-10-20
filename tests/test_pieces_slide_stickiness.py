"""
STORY    As a speaker, I want slide-fit scores, overall scores and ranks never
         to appear in my readout, while my coach can see them, so that I see
         words, not numbers (Never rule 1).
OUTCOME
  O1  The speaker readout JSON contains none of slide_stickiness,
      overall_score or rank.
  O2  The coach packet carries all three.
  O3  With the LLM down, a take still persists every piece, each with a
      lexical (degraded) slide-fit score, so the coach still gets one.
PROVES   O1 -> test_speaker_readout_carries_no_slide_scores
         O2 -> test_coach_packet_carries_all_three
         O3 -> test_llm_outage_still_persists_every_piece_with_lexical_slide_fit
WHY      AC-9 fence (founder fix-pack BE-5, 2026-07-16).
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

    def _build(self, rows, **kwargs):
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
            return mod.build_readout_from_session("sess1", **kwargs)

    def test_speaker_readout_carries_no_slide_scores(self):
        # Called exactly as the speaker routes call it (user_sessions,
        # guest readout, completed-recording response).
        out = self._build([self._piece_row("a", 0), self._piece_row("b", 1)],
                          include_upgrade_cards=False)
        self.assertEqual([s["id"] for s in out["snippets"]], ["a", "b"])
        wire = json.dumps(out)
        for key in ("slide_stickiness", "overall_score", '"rank"'):
            self.assertNotIn(key, wire)

    def test_coach_packet_carries_all_three(self):
        rows = [self._piece_row("a", 0)]
        out = self._build(rows, include_insights=False,
                          include_slide_scores=True)
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
    """process_lab_recording with the LLM down: only audio decoding, Whisper
    and the LLM itself are faked; slide alignment, scoring and persistence
    run for real against the stubbed database."""

    def test_llm_outage_still_persists_every_piece_with_lexical_slide_fit(self):
        from services import slide_alignment as sa
        from services.db import db
        sa._claims_cache.clear()
        db.reset_mock()
        persisted = {}

        def _bulk(rows):
            persisted["rows"] = rows
            return [f"sn{i}" for i in range(len(rows))]

        db.create_charisma_snippets_bulk.side_effect = _bulk

        words, advances = _words_and_advances(
            [ON_SLIDE_TEXT, "customers leave us in week one because "
                            "setup is painful today"])
        whisper = MagicMock(client=True)
        whisper.transcribe_audio.return_value = {"segments": [],
                                                 "words": words}
        # services.openai_service imports the openai package — stub the
        # MODULE for this test only (patch.dict restores it).
        ois_mod = types.ModuleType("services.openai_service")
        ois_mod.OpenAIService = MagicMock(return_value=whisper)

        with patch.dict(sys.modules,
                        {"services.openai_service": ois_mod}), \
             patch.dict(os.environ, {"WILLAB_PIECE_LLM_BUDGET": "1"}), \
             patch("services.audio_metrics.decode_audio_to_pcm",
                   return_value=[0.0] * 16000), \
             patch("services.audio_metrics.analyze_pcm_window",
                   return_value={"f0_mean": 150.0, "speech_rate": 130.0,
                                 "loudness_range": 10.0,
                                 "voiced_ratio": 0.7}), \
             patch("services.llm.chat_complete", return_value=None):
            # chat_complete's contract: None on any provider failure.
            from services.lab_recording import process_lab_recording
            process_lab_recording(
                session_id="sess1", user_id="u1", recording_id="rec1",
                audio_bytes=b"x" * 64, filename="lab.webm",
                session_context={"slides": SLIDES[:2],
                                 "slide_advances": advances},
                parent_audio_url="https://x/parent.webm",
            )

        rows = persisted.get("rows") or []
        self.assertEqual(len(rows), 2)          # live loop intact
        for r in rows:
            ss = r["metrics"]["slide_stickiness"]
            self.assertIsNotNone(ss["composite"])
            self.assertTrue(ss["degraded"])


if __name__ == "__main__":
    unittest.main()
