"""
STORY    As the founder, I want every candidate's pick chance logged in the
         dark frame but never in what is served, so that we can study picks
         without showing numbers.
OUTCOME
  O1  NEVER-1: the service frame carries the Take's blocks and candidates and
      no pick log or pick chance.
  O2  The dark frame logs every candidate once, with its chance (1.0 for the
      block's pick, 0.0 for the rest), the Take's seed and the policy version.
PROVES   O1 -> test_the_serving_frame_carries_no_pick_chance
         O2 -> test_the_dark_frame_logs_every_pick_with_seed_and_policy
WHY      V4 Phase 1, B1.1 (build plan D-ML-6); AC-9.
"""
from __future__ import annotations

import json

from services.take_feedback_policy_v3 import (
    PICK_SEED_VERSION,
    POLICY_VERSION,
    build_service_candidate_frame,
    build_shadow_frame,
    pick_seed,
)

TAKE = "take-2"
# (index, slide, words, delivery score): two slides, two 75-word blocks.
_PIECES = [(0, 0, 25, -0.4), (1, 0, 25, 0.2), (2, 0, 25, 0.7),
           (3, 1, 35, -0.5), (4, 1, 35, -0.2)]


def _inputs() -> dict:
    pieces, snippets = [], []
    for index, slide, words, score in _PIECES:
        text = " ".join(f"word{index}x{n}" for n in range(words))
        pieces.append({
            "snippet_id": f"snippet-{index}", "take_session_id": TAKE,
            "slide_index": slide, "start": index * 1000,
            "end": index * 1000 + len(text), "text": text,
            "recording_id": "recording-1", "start_offset_ms": index * 5000,
            "duration_ms": 5000, "score": score,
        })
        snippets.append({
            "id": f"snippet-{index}", "session_id": TAKE, "recording_id": "recording-1",
            "start_offset_ms": index * 5000, "duration_ms": 5000,
            "metrics": {"voice_confidence": {
                "version": "voice-confidence-universal-v3", "score": score}},
        })
    return {"take_document": {"take_session_id": TAKE, "text": "x" * 5000,
                              "pieces": pieces},
            "snippets": snippets, "suggestions": {}, "feedback_candidates": [],
            "take_index": 2, "expected_recording_id": "recording-1",
            "served_text": "x" * 5000}


def _candidate_ids(frame: dict) -> list[str]:
    return [c["candidate_id"] for block in frame["blocks"]
            for c in block["confidence_candidates"]]


def test_the_serving_frame_carries_no_pick_chance():
    service = build_service_candidate_frame(**_inputs())
    assert service is not None
    assert len(service["blocks"]) == 2 and len(_candidate_ids(service)) == len(_PIECES)
    assert "pick_log" not in service
    assert "pick_probability" not in json.dumps(service)


def test_the_dark_frame_logs_every_pick_with_seed_and_policy():
    dark = build_shadow_frame(**_inputs())
    log = dark["pick_log"]
    assert log["seed"] == pick_seed(TAKE) and log["seed"].isdigit()
    assert log["seed_version"] == PICK_SEED_VERSION
    assert log["policy_version"] == POLICY_VERSION
    logged = [entry["candidate_id"] for entry in log["candidates"]]
    assert sorted(logged) == sorted(_candidate_ids(dark))
    chances = {entry["candidate_id"]: entry["pick_probability"] for entry in log["candidates"]}
    for block in dark["blocks"]:
        ids = [c["candidate_id"] for c in block["confidence_candidates"]]
        picked = [i for i in ids if chances[i] == 1.0]
        assert len(picked) == 1, block["block_id"]
        assert all(chances[i] == 0.0 for i in ids if i not in picked)
