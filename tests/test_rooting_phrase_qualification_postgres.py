"""
STORY    As a speaker, I want a phrase I said confidently to become my helper
         words and lock its Paragraph in one step, and be removable, so that
         my helper words follow my choices.
OUTCOME
  O1  A phrase I said with a confident "yes" qualifies to become helper
      words directly.
  O2  Choosing it locks the Paragraph and sets the helper words in one step;
      doing it twice changes nothing more, and the Ideal Text is not
      rebuilt.
  O3  Removing the helper words clears them and keeps the Paragraph locked.
PROVES   O1 -> test_direct_confident_path_activates_and_removes_separate_actions
         O2 -> test_direct_confident_path_activates_and_removes_separate_actions
         O3 -> test_direct_confident_path_activates_and_removes_separate_actions
WHY      Never-rule 5: helper words stay until the speaker picks new ones.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from psycopg2.extras import Json

from tests.test_mlc3_dark_assignments_postgres import (
    connect,
    make_context,
    one,
    query,
    rpc,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("MLC3_REHEARSAL_DSN"),
    reason="disposable RPQ PostgreSQL rehearsal only",
)


@pytest.fixture
def db():
    connection = connect()
    yield connection
    connection.close()


def _v3_context(
    db, ctx, *, include_rewrite=False, paragraph_override: str | None = None,
    prove_rewrite: bool = True, evidence_exact_override: str | None = None,
    evidence_replacement_override: str | None = None,
):
    part_id = str(uuid4())
    manager_set_id = str(uuid4())
    snapshot_id = str(uuid4())
    confidence_id = str(uuid4())
    rewrite_id = str(uuid4())
    confidence_exposure_id = str(uuid4())
    rewrite_exposure_id = str(uuid4())
    evidence_id = str(uuid4())
    phrase = "This is my clear anchor."
    evidence_exact = evidence_exact_override or phrase
    paragraph = (
        paragraph_override
        if paragraph_override is not None
        else phrase if not include_rewrite else "This is my clearer anchor."
    )
    owner_user = one(
        db, "SELECT user_id FROM owner_principals WHERE id=%s", (ctx["owner"],)
    )["user_id"]
    query(
        db,
        "UPDATE v2_sessions SET user_id=%s WHERE id=%s",
        (owner_user, ctx["take"]),
    )
    query(
        db,
        "UPDATE projects SET setup=%s WHERE id=%s",
        (Json({"goal": "Explain the product clearly."}), ctx["project"]),
    )
    query(
        db,
        "UPDATE v2_sessions SET take_index=%s WHERE id=%s",
        (2 if include_rewrite else 1, ctx["take"]),
    )
    query(
        db,
        "INSERT INTO evidence_spans(id,owner_principal_id,project_id,take_id,"
        "recording_id,legacy_piece_id,evidence_kind,task_type,start_ms,end_ms,"
        "start_char,end_char,exact_text,replacement_text,evidence_hash,input_hash) VALUES "
        "(%s,%s,%s,%s,%s,%s,'audio_and_transcript',"
        "'confidence_classification',1250,3650,0,%s,%s,%s,%s,%s)",
        (
            evidence_id,
            ctx["owner"],
            ctx["project"],
            ctx["take"],
            ctx["recording"],
            ctx["snippet"],
            len(phrase),
            evidence_exact,
            (evidence_replacement_override
             if evidence_replacement_override is not None
             else paragraph if include_rewrite else None),
            str(uuid4()),
            str(uuid4()),
        ),
    )
    query(
        db,
        "INSERT INTO candidate_sets(id,owner_principal_id,project_id,take_id,"
        "taxonomy_version,selector_version,manager_rules_version,threshold_version,"
        "input_hash,idempotency_key,code_commit) VALUES "
        "(%s,%s,%s,%s,'feedback-v3','selector-v1',"
        "'take-feedback-policy-v3-serving-v1','threshold-v1',%s,%s,'fixture')",
        (
            manager_set_id,
            ctx["owner"],
            ctx["project"],
            ctx["take"],
            "f" * 64,
            str(uuid4()),
        ),
    )
    candidate_key = "candidate-" + ctx["snippet"]
    rewrite_key = "rewrite-" + uuid4().hex
    query(
        db,
        "INSERT INTO feedback_candidates(id,candidate_set_id,evidence_span_id,"
        "feedback_family,lane,candidate_key,generated_output) VALUES "
        "(%s,%s,%s,'confident_voice','vocal',%s,%s)",
        (confidence_id, manager_set_id, evidence_id, candidate_key,
         Json({"quote": phrase})),
    )
    if include_rewrite:
        query(
            db,
            "INSERT INTO feedback_candidates(id,candidate_set_id,evidence_span_id,"
            "feedback_family,lane,candidate_key,generated_output) VALUES "
            "(%s,%s,%s,'rewrite_clarity','wording',%s,%s)",
            (rewrite_id, manager_set_id, evidence_id, rewrite_key,
             Json({"quote": phrase, "proposed_text": paragraph})),
        )
    query(
        db,
        "INSERT INTO feedback_exposures(id,candidate_set_id,candidate_id,"
        "feedback_family,lane,is_selected,position_shown,shown_at,selector_version,"
        "manager_rules_version,threshold_version,input_hash) VALUES "
        "(%s,%s,%s,'confident_voice','vocal',true,1,clock_timestamp(),"
        "'selector-v1','take-feedback-policy-v3-serving-v1','threshold-v1',%s)",
        (confidence_exposure_id, manager_set_id, confidence_id, "f" * 64),
    )
    if include_rewrite:
        query(
            db,
            "INSERT INTO feedback_exposures(id,candidate_set_id,candidate_id,"
            "feedback_family,lane,is_selected,position_shown,shown_at,selector_version,"
            "manager_rules_version,threshold_version,input_hash) VALUES "
            "(%s,%s,%s,'rewrite_clarity','wording',true,2,clock_timestamp(),"
            "'selector-v1','take-feedback-policy-v3-serving-v1','threshold-v1',%s)",
            (rewrite_exposure_id, manager_set_id, rewrite_id, "f" * 64),
        )
    payload = {
        "parts": [{"id": part_id, "text": paragraph}],
        "pieces": [{"part_id": part_id, "slide_index": 0}],
    }
    query(
        db,
        "INSERT INTO ideal_text_part(id,arc_id,user_id,ord,text) "
        "VALUES (%s,%s,%s,0,%s)",
        (part_id, str(ctx["project"]), str(owner_user), paragraph),
    )
    if include_rewrite and prove_rewrite:
        query(
            db,
            "INSERT INTO ideal_text_part_revision(arc_id,user_id,part_id,action,"
            "text,take_session_id,review_version) VALUES "
            "(%s,%s,%s,'user_edit',%s,%s,2)",
            (str(ctx["project"]), str(owner_user), part_id, paragraph, ctx["take"]),
        )
    query(
        db,
        "INSERT INTO ideal_text_document_generations(arc_id,generation) "
        "VALUES (%s,1) ON CONFLICT (arc_id) DO UPDATE SET generation=1",
        (str(ctx["project"]),),
    )
    query(
        db,
        "INSERT INTO ideal_text_document_snapshots(id,arc_id,actor_id,"
        "acquisition_principal_id,project_id,source_take_session_id,version,"
        "source_generation,source_fingerprint_sha256,payload_sha256,payload) "
        "VALUES (%s,%s,%s,%s,%s,%s,1,1,%s,%s,%s)",
        (
            snapshot_id,
            str(ctx["project"]),
            one(db, "SELECT user_id FROM owner_principals WHERE id=%s", (ctx["owner"],))[
                "user_id"
            ],
            ctx["owner"],
            ctx["project"],
            ctx["take"],
            "a" * 64,
            "b" * 64,
            Json(payload),
        ),
    )
    query(
        db,
        "INSERT INTO ideal_text_document_heads(arc_id,actor_id,snapshot_id) "
        "SELECT arc_id,actor_id,id FROM ideal_text_document_snapshots WHERE id=%s",
        (snapshot_id,),
    )
    items = [
        {
            "candidate_id": confidence_id,
            "candidate_key": candidate_key,
            "feedback_family": "confident_voice",
            "slide_index": 0,
            "block_key": 0,
            "source_ideal_part_id": part_id,
            "eligibility": "eligible",
            "exclusion_reason": None,
            "selected": True,
            "position_shown": 1,
        }
    ]
    if include_rewrite:
        items.append(
            {
                "candidate_id": rewrite_id,
                "candidate_key": one(
                    db,
                    "SELECT candidate_key FROM feedback_candidates WHERE id=%s",
                    (rewrite_id,),
                )["candidate_key"],
                "feedback_family": "rewrite_clarity",
                "slide_index": 0,
                "block_key": 0,
                "source_ideal_part_id": part_id,
                "eligibility": "eligible",
                "exclusion_reason": None,
                "selected": True,
                "position_shown": 2,
            }
        )
    membership_hash = one(
        db,
        "SELECT exercise_json_sha256_v1(jsonb_build_object("
        "'acquisition_principal_id',%s::uuid,'project_id',%s::uuid,"
        "'take_id',%s::uuid,'candidate_set_id',%s::uuid,"
        "'document_snapshot_id',%s::uuid,'document_snapshot_sha256',%s,"
        "'content_identity_sha256',feedback_v3_content_identity_v1(%s::jsonb),"
        "'policy_version','take-feedback-policy-v3-serving-v1',"
        "'block_partition_version','slide-75-words-v1','items',%s::jsonb)) AS hash",
        (
            ctx["owner"],
            ctx["project"],
            ctx["take"],
            manager_set_id,
            snapshot_id,
            "b" * 64,
            Json(payload),
            Json(items),
        ),
    )["hash"]
    membership = rpc(
        db,
        "freeze_synthetic_feedback_v3_membership_v1",
        ctx["owner"],
        ctx["project"],
        ctx["take"],
        manager_set_id,
        snapshot_id,
        "slide-75-words-v1",
        Json(items),
        membership_hash,
        str(uuid4()),
    )
    if include_rewrite and prove_rewrite:
        rpc(
            db,
            "record_feedback_human_decision_v1",
            ctx["project"],
            ctx["take"],
            owner_user,
            membership["id"],
            rewrite_id,
            rewrite_exposure_id,
            "rewrite_clarity",
            "accept_proposed",
            "feedback-taxonomy-v1",
            str(uuid4()),
        )
    return {
        "membership": membership,
        "snapshot": snapshot_id,
        "part": part_id,
        "phrase": paragraph,
        "paragraph": paragraph,
        "confidence": confidence_id,
        "rewrite": rewrite_id,
        "rewrite_key": rewrite_key,
        "confidence_exposure": confidence_exposure_id,
        "rewrite_exposure": rewrite_exposure_id,
    }


def _semantic(db, content):
    semantic_input = rpc(
        db,
        "freeze_synthetic_root_semantic_input_v1",
        content["id"],
        str(uuid4()),
    )
    return rpc(
        db,
        "record_synthetic_root_semantic_result_v1",
        content["id"],
        semantic_input["id"],
        "aligned",
        "exact_goal_alignment",
        "prompt-v1",
        "model-v1",
        "code-v1",
        str(uuid4()),
    )


def test_direct_confident_path_activates_and_removes_separate_actions(db):
    ctx = make_context(db)
    v3 = _v3_context(db, ctx)
    owner_user = one(
        db, "SELECT user_id FROM owner_principals WHERE id=%s", (ctx["owner"],)
    )["user_id"]
    response = rpc(
        db,
        "record_synthetic_feedback_v3_confidence_response_v1",
        v3["membership"]["id"],
        v3["confidence"],
        owner_user,
        "confident_yes",
        str(uuid4()),
    )
    content = rpc(
        db,
        "register_synthetic_root_content_version_v1",
        v3["membership"]["id"],
        v3["confidence"],
        v3["part"],
        ctx["auth"],
        v3["phrase"],
        0,
        len(v3["phrase"]),
        "unchanged_manager",
        str(uuid4()),
    )
    assert content["source_part_version_kind"] == "canonical_snapshot_baseline_v1"
    semantic = _semantic(db, content)
    qualification = rpc(
        db,
        "evaluate_synthetic_root_qualification_v1",
        content["id"],
        semantic["id"],
        None,
        response["id"],
        None,
        "unchanged_confident_voice",
        str(uuid4()),
    )
    assert qualification["routing_state"] == "eligible_direct"
    generation_before = one(
        db,
        "SELECT generation FROM ideal_text_document_generations WHERE arc_id=%s",
        (str(ctx["project"]),),
    )["generation"]
    activation_key = str(uuid4())
    activated = rpc(
        db,
        "activate_synthetic_root_phrase_v1",
        qualification["id"],
        owner_user,
        True,
        False,
        activation_key,
    )["activate_synthetic_root_phrase_v1"]
    replay = rpc(
        db,
        "activate_synthetic_root_phrase_v1",
        qualification["id"],
        owner_user,
        True,
        False,
        activation_key,
    )["activate_synthetic_root_phrase_v1"]
    assert replay == activated
    assert one(
        db,
        "SELECT count(*) AS n FROM root_phrase_product_actions "
        "WHERE id IN (%s,%s)",
        (activated["lock_action_id"], activated["root_action_id"]),
    )["n"] == 2
    canonical = one(
        db,
        "SELECT locked_at,root_phrase,root_start,root_end FROM ideal_text_part "
        "WHERE id=%s",
        (v3["part"],),
    )
    assert canonical["locked_at"] is not None
    assert canonical["root_phrase"] == v3["phrase"]
    assert canonical["root_start"] == 0
    assert canonical["root_end"] == len(v3["phrase"])
    assert one(
        db,
        "SELECT generation FROM ideal_text_document_generations WHERE arc_id=%s",
        (str(ctx["project"]),),
    )["generation"] == generation_before
    core = rpc(
        db,
        "get_synthetic_root_core_state_v1",
        ctx["project"],
        ctx["owner"],
        v3["snapshot"],
    )["get_synthetic_root_core_state_v1"]
    assert core["paragraphs"][0]["locked"] is True
    assert core["paragraphs"][0]["active_root"]["phrase_text"] == v3["phrase"]
    assert core["slides"][0]["state"] == "slide_minimum_ready"
    assert core["full_density"] is True
    removed = rpc(
        db,
        "remove_synthetic_root_phrase_v1",
        ctx["project"],
        0,
        0,
        activated["root_action_id"],
        owner_user,
        str(uuid4()),
    )["remove_synthetic_root_phrase_v1"]
    assert removed["interaction_state_revision"] == 2
    canonical = one(
        db,
        "SELECT locked_at,root_phrase FROM ideal_text_part WHERE id=%s",
        (v3["part"],),
    )
    assert canonical["locked_at"] is not None
    assert canonical["root_phrase"] is None
