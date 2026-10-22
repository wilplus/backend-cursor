"""
STORY    As the founder, I want every candidate's pick chance logged in the
         dark frame but never in what is served, so that we can study picks
         without showing numbers.
OUTCOME
  O1  NEVER-1: the service frame carries the Take's blocks and candidates and
      no pick log or pick chance.
  O2  The dark frame logs every candidate once, with its chance (1.0 for the
      block's pick, 0.0 for the rest), the Take's seed and the policy version.
  O3  The database writer on main accepts the labels the code builds, and
      V4's frame rule names every policy a stored frame carries.
PROVES   O1 -> test_the_serving_frame_carries_no_pick_chance
         O2 -> test_the_dark_frame_logs_every_pick_with_seed_and_policy
         O3 -> test_the_database_accepts_the_labels_the_code_builds
WHY      V4 Phase 1, B1.1 (build plan D-ML-6); AC-9. O3: #1207 moved both
         labels with no migration, and for two days no Take kept its frame;
         the rehearsal tier, which would have caught it, runs only when a
         migration changes (0489).
"""
from __future__ import annotations

import json
import pathlib

from services.take_feedback_policy_v3 import (
    DARK_POLICY_VERSIONS,
    FRAME_SCHEMA_VERSION,
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


def _last_definition(function: str) -> str:
    """The text of the last migration in the manifest that defines it."""
    migrations = pathlib.Path(__file__).resolve().parents[1] / "migrations"
    files = [line.split("\t")[1] for line in
             (migrations / "manifest.txt").read_text().splitlines() if "\t" in line]
    texts = [(migrations / f).read_text() for f in files]
    return [t for t in texts if f"FUNCTION public.{function}(" in t][-1]


def test_the_database_accepts_the_labels_the_code_builds():
    writer = _last_definition("record_take_feedback_policy_v3_shadow_v3")
    assert f"'{POLICY_VERSION}'" in writer
    assert f"'{FRAME_SCHEMA_VERSION}'" in writer
    assert DARK_POLICY_VERSIONS[0] == POLICY_VERSION
    rule = _last_definition("v4_frame_policy_v1")
    assert all(f"'{policy}'" in rule for policy in DARK_POLICY_VERSIONS)
