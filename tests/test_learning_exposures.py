"""
STORY    As the founder, I want each record of what a speaker was shown to keep
         the machine's, the speaker's and the coach's answers apart and to show
         no numbers, so that the three judgements stay independent.
OUTCOME
  O1  What the speaker sees carries no score, rank or prediction, and no copy
      of any other person's answer; the machine's own score stays only in the
      machine's column.
  O2  A shown item that carries a score or someone's answer is refused before
      anything is saved.
PROVES   O1 -> test_v3_packets_carry_no_score_rank_prediction_or_other_actors_answer
         O2 -> test_a_visible_payload_with_a_score_or_an_answer_is_refused_at_the_seam
WHY      Never-rules 1 and 2 (AC-9, L3).
"""
from __future__ import annotations

import uuid
from unittest.mock import Mock

import pytest

from services.learning_exposures import (
    LearningExposureError,
    prepare_presentation,
)

OWNER = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
TAKE = "33333333-3333-4333-8333-333333333333"
ACTOR = "44444444-4444-4444-8444-444444444444"


def _candidate(key: str, family: str, evidence_id: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "candidate_key": key,
        "feedback_family": family,
        "candidate_score": 0.7,
        "rank_evidence": {"rank_key": [1]},
        "generated_output": {"quote": f"Visible {key}"},
        "training_eligible": True,
        "evidence": {
            "id": evidence_id,
            "evidence_hash": "a" * 64,
            "exact_text": f"Evidence {key}",
            "audio_ref": "recordings/take.webm",
            "start_ms": 0,
            "end_ms": 1000,
        },
    }


def _bundle() -> dict:
    candidates = [
        _candidate("voice", "confident_voice",
                   "55555555-5555-4555-8555-555555555555"),
        _candidate("rewrite", "rewrite_clarity",
                   "66666666-6666-4666-8666-666666666666"),
        _candidate("praise", "great_formulation",
                   "77777777-7777-4777-8777-777777777777"),
    ]
    return {
        "owner_principal_id": OWNER,
        "project_id": PROJECT,
        "take_id": TAKE,
        "candidate_set_id": "88888888-8888-4888-8888-888888888888",
        "candidates": candidates,
        "selected_keys": [
            {"id": row["candidate_key"],
             "feedback_family": row["feedback_family"]}
            for row in candidates
        ],
        "versions": {"taxonomy_version": "v1", "selector_version": "v1"},
        "generation_runs": [],
    }


def _presentation_database() -> Mock:
    database = Mock()
    database.create_learning_surface_presentation.side_effect = lambda row: {
        "presentation_id": str(uuid.uuid4()),
        "acknowledgement_token": str(uuid.uuid4()),
        "learning_surface": row["learning_surface"],
        "evaluation_only": row["delivery_mode"] == "shadow",
    }
    return database


# ── V3 PACKETS (founder 2026-09-29; the 29 Sep report's "V3 packets") ─────
#
# V3 has served every Take since 2026-09-18. Its rows share no identity with
# V2's three, and the V2 writer above insists on exactly three cards, so no
# served V3 card ever carried a packet. The V3 writer freezes one packet per
# surface for every visible row, from the bundle V3 itself served from.

from services.learning_exposures import (  # noqa: E402
    FORBIDDEN_VISIBLE_KEYS,
    prepare_v3_feedback_presentations,
)


def _v3_rows(bundle: dict, *keys: str) -> list[dict]:
    """Served V3 rows, in the shape the service emits: id = candidate key."""
    by_key = {row["candidate_key"]: row for row in bundle["candidates"]}
    rows = []
    for key in keys:
        row = {"id": key, "feedback_family": by_key[key]["feedback_family"],
               "snippet_id": "snip-" + key}
        if by_key[key]["feedback_family"] == "confident_voice":
            row.update({"bookmark_tier": "exercise", "block_id": "block-1",
                        "practice_prompt": True})
        rows.append(row)
    return rows


def test_v3_packets_carry_no_score_rank_prediction_or_other_actors_answer():
    """The three columns stay apart (L3) and nothing shown is a number (AC-9).

    The machine's own score and rank evidence live in the frozen candidate
    snapshots -- the machine column -- and nowhere else in the packet.
    """
    database = _presentation_database()
    bundle = _bundle()
    for row in bundle["candidates"]:
        row["user_self_report"] = "yes"
        row["coach_judgment"] = "yes"
        row["machine_prediction"] = {"lean": "confident"}

    prepare_v3_feedback_presentations(
        database=database, bundle=bundle,
        visible_rows=_v3_rows(bundle, "voice", "rewrite", "praise"),
        actor_id=ACTOR)

    for call in database.create_learning_surface_presentation.call_args_list:
        payload = call.args[0]
        assert not FORBIDDEN_VISIBLE_KEYS.intersection(payload["visible_payload"])
        assert not FORBIDDEN_VISIBLE_KEYS.intersection(payload["versions"])
        for snapshot in [payload["selected_candidate"],
                         *payload["complete_candidate_set"]]:
            assert "user_self_report" not in snapshot
            assert "coach_judgment" not in snapshot
            assert "peer_judgment" not in snapshot
            assert "machine_prediction" not in snapshot
            # The machine column keeps the machine's own evidence.
            assert snapshot["candidate_score"] == 0.7
            assert snapshot["rank_evidence"] == {"rank_key": [1]}
        assert payload["actor_role"] == "owner"


def test_a_visible_payload_with_a_score_or_an_answer_is_refused_at_the_seam():
    database = _presentation_database()
    for key in ("candidate_score", "user_self_report", "coach_judgment"):
        with pytest.raises(LearningExposureError, match="another actor"):
            prepare_presentation(
                database=database,
                owner_principal_id=OWNER,
                project_id=PROJECT,
                take_id=TAKE,
                evidence_span_id="55555555-5555-4555-8555-555555555555",
                learning_surface="confidence_classification",
                actor_role="owner",
                actor_id=ACTOR,
                complete_candidate_set=[{"candidate_key": "voice"}],
                selected_candidate={"candidate_key": "voice"},
                visible_payload={"quote": "shown", key: 0.9},
                versions={"taxonomy_version": "v1"},
            )
    database.create_learning_surface_presentation.assert_not_called()
