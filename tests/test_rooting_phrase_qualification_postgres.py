"""Disposable PostgreSQL tests for restored V3/P1/P2/RPQ contracts."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep
from uuid import uuid4

import psycopg2
from psycopg2.extras import Json
import pytest

from tests.test_mlc3_dark_assignments_postgres import (
    assign,
    connect,
    make_context,
    make_packet,
    one,
    query,
    reveal_packet,
    rpc,
)
from tests.test_mlc3_n1_source_pattern_postgres import profile, source_pattern


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


def _direct_qualification(db, ctx, v3):
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
    return owner_user, content, qualification


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


def test_content_rejects_a_different_phrase_from_the_same_paragraph(db):
    ctx = make_context(db)
    v3 = _v3_context(
        db,
        ctx,
        paragraph_override="This is my clear anchor. This is another phrase.",
    )
    phrase_b = "This is another phrase."
    start_b = v3["paragraph"].index(phrase_b)
    with pytest.raises(psycopg2.Error, match="ROOT_CONTENT_VERSION_INVALID"):
        rpc(
            db,
            "register_synthetic_root_content_version_v1",
            v3["membership"]["id"],
            v3["confidence"],
            v3["part"],
            ctx["auth"],
            phrase_b,
            start_b,
            start_b + len(phrase_b),
            "unchanged_manager",
            str(uuid4()),
        )
    assert one(
        db,
        "SELECT count(*) AS n FROM root_phrase_content_versions "
        "WHERE feedback_membership_id=%s",
        (v3["membership"]["id"],),
    )["n"] == 0


@pytest.mark.parametrize("family", ["confidence", "rewrite"])
def test_manager_wording_must_equal_its_exact_evidence_wording(db, family):
    ctx = make_context(db)
    if family == "confidence":
        v3 = _v3_context(
            db,
            ctx,
            paragraph_override="This is my clear anchor. Evidence says otherwise.",
            evidence_exact_override="Evidence says otherwise.",
        )
        candidate = v3["confidence"]
        origin = "unchanged_manager"
    else:
        v3 = _v3_context(
            db,
            ctx,
            include_rewrite=True,
            evidence_replacement_override="A different proposed rewrite.",
        )
        candidate = v3["rewrite"]
        origin = "accepted_rewrite"
    with pytest.raises(psycopg2.Error, match="ROOT_MANAGER_EVIDENCE_MISMATCH"):
        rpc(
            db,
            "register_synthetic_root_content_version_v1",
            v3["membership"]["id"],
            candidate,
            v3["part"],
            ctx["auth"],
            v3["phrase"],
            0,
            len(v3["phrase"]),
            origin,
            str(uuid4()),
        )
    assert one(
        db,
        "SELECT count(*) AS n FROM root_phrase_content_versions "
        "WHERE feedback_membership_id=%s",
        (v3["membership"]["id"],),
    )["n"] == 0


def test_accepting_candidate_a_does_not_authorize_regenerated_candidate_b(db):
    ctx = make_context(db)
    v3 = _v3_context(db, ctx, include_rewrite=True)
    owner_user = one(
        db, "SELECT user_id FROM owner_principals WHERE id=%s", (ctx["owner"],)
    )["user_id"]
    candidate_a = one(
        db,
        "SELECT candidate_set_id,evidence_span_id,generated_output FROM "
        "feedback_candidates WHERE id=%s",
        (v3["rewrite"],),
    )
    decision_a = one(
        db,
        "SELECT id,candidate_id,candidate_output_sha256 FROM correction_decisions "
        "WHERE rater_id=%s AND value='accept_proposed'",
        (owner_user,),
    )
    candidate_b_id = str(uuid4())
    candidate_b_set_id = str(uuid4())
    candidate_b_exposure_id = str(uuid4())
    candidate_b_snapshot_id = str(uuid4())
    candidate_b_key = v3["rewrite_key"]
    snapshot_a = one(
        db, "SELECT * FROM ideal_text_document_snapshots WHERE id=%s",
        (v3["snapshot"],),
    )
    query(
        db,
        "UPDATE ideal_text_document_generations SET generation=2 WHERE arc_id=%s",
        (str(ctx["project"]),),
    )
    query(
        db,
        "INSERT INTO ideal_text_document_snapshots(id,arc_id,actor_id,"
        "acquisition_principal_id,project_id,source_take_session_id,version,"
        "source_generation,source_fingerprint_sha256,payload_sha256,payload) "
        "VALUES (%s,%s,%s,%s,%s,%s,2,2,%s,%s,%s)",
        (
            candidate_b_snapshot_id, snapshot_a["arc_id"], snapshot_a["actor_id"],
            ctx["owner"], ctx["project"], ctx["take"], "c" * 64, "d" * 64,
            Json(snapshot_a["payload"]),
        ),
    )
    query(
        db,
        "UPDATE ideal_text_document_heads SET snapshot_id=%s "
        "WHERE arc_id=%s AND actor_id=%s",
        (candidate_b_snapshot_id, snapshot_a["arc_id"], snapshot_a["actor_id"]),
    )
    query(
        db,
        "INSERT INTO candidate_sets(id,owner_principal_id,project_id,take_id,"
        "taxonomy_version,selector_version,manager_rules_version,threshold_version,"
        "input_hash,idempotency_key,code_commit) VALUES "
        "(%s,%s,%s,%s,'feedback-v3','selector-v1',"
        "'take-feedback-policy-v3-serving-v1','threshold-v1',%s,%s,'fixture')",
        (
            candidate_b_set_id, ctx["owner"], ctx["project"], ctx["take"],
            "e" * 64, str(uuid4()),
        ),
    )
    query(
        db,
        "INSERT INTO feedback_candidates(id,candidate_set_id,evidence_span_id,"
        "feedback_family,lane,candidate_key,generated_output) VALUES "
        "(%s,%s,%s,'rewrite_clarity','wording',%s,%s)",
        (
            candidate_b_id,
            candidate_b_set_id,
            candidate_a["evidence_span_id"],
            candidate_b_key,
            Json(candidate_a["generated_output"]),
        ),
    )
    query(
        db,
        "INSERT INTO feedback_exposures(id,candidate_set_id,candidate_id,"
        "feedback_family,lane,is_selected,position_shown,shown_at,selector_version,"
        "manager_rules_version,threshold_version,input_hash) VALUES "
        "(%s,%s,%s,'rewrite_clarity','wording',true,1,clock_timestamp(),"
        "'selector-v1','take-feedback-policy-v3-serving-v1','threshold-v1',%s)",
        (candidate_b_exposure_id, candidate_b_set_id, candidate_b_id, "f" * 64),
    )
    items_b = [{
        "candidate_id": candidate_b_id,
        "candidate_key": candidate_b_key,
        "feedback_family": "rewrite_clarity",
        "slide_index": 0,
        "block_key": 0,
        "source_ideal_part_id": v3["part"],
        "eligibility": "eligible",
        "exclusion_reason": None,
        "selected": True,
        "position_shown": 1,
    }]
    membership_b_hash = one(
        db,
        "SELECT exercise_json_sha256_v1(jsonb_build_object("
        "'acquisition_principal_id',%s::uuid,'project_id',%s::uuid,"
        "'take_id',%s::uuid,'candidate_set_id',%s::uuid,"
        "'document_snapshot_id',%s::uuid,'document_snapshot_sha256',%s,"
        "'content_identity_sha256',feedback_v3_content_identity_v1(%s::jsonb),"
        "'policy_version','take-feedback-policy-v3-serving-v1',"
        "'block_partition_version','slide-75-words-v1','items',%s::jsonb)) AS hash",
        (
            ctx["owner"], ctx["project"], ctx["take"], candidate_b_set_id,
            candidate_b_snapshot_id, "d" * 64, Json(snapshot_a["payload"]),
            Json(items_b),
        ),
    )["hash"]
    membership_b = rpc(
        db,
        "freeze_synthetic_feedback_v3_membership_v1",
        ctx["owner"], ctx["project"], ctx["take"], candidate_b_set_id,
        candidate_b_snapshot_id, "slide-75-words-v1", Json(items_b),
        membership_b_hash, str(uuid4()),
    )
    candidate_b_hash = one(
        db,
        "SELECT feedback_candidate_output_sha256_v1(%s) AS hash",
        (candidate_b_id,),
    )["hash"]
    assert decision_a["candidate_id"] == v3["rewrite"]
    assert decision_a["candidate_id"] != candidate_b_id
    assert decision_a["candidate_output_sha256"] != candidate_b_hash
    assert not one(
        db,
        "SELECT EXISTS(SELECT 1 FROM correction_decisions decision "
        "WHERE decision.id=%s AND decision.candidate_id=%s "
        "AND decision.candidate_output_sha256="
        "feedback_candidate_output_sha256_v1(%s)) AS authorized",
        (decision_a["id"], candidate_b_id, candidate_b_id),
    )["authorized"]
    with pytest.raises(psycopg2.Error, match="FEEDBACK_V3"):
        rpc(
            db,
            "record_feedback_human_decision_v1",
            ctx["project"], ctx["take"], owner_user,
            v3["membership"]["id"], v3["rewrite"], v3["rewrite_exposure"],
            "rewrite_clarity", "accept_proposed", "feedback-taxonomy-v1",
            str(uuid4()),
        )
    assert one(
        db,
        "SELECT count(*) AS n FROM correction_decisions WHERE candidate_id=%s",
        (candidate_b_id,),
    )["n"] == 0
    decision_b_key = str(uuid4())
    explicit_b = one(
        db,
        "SELECT public.record_feedback_human_decision_v1(" + ",".join(["%s"] * 10)
        + ") AS result",
        (
            ctx["project"], ctx["take"], owner_user, membership_b["id"],
            candidate_b_id, candidate_b_exposure_id,
            "rewrite_clarity", "accept_proposed", "feedback-taxonomy-v1",
            decision_b_key,
        ),
    )["result"]
    assert explicit_b["candidate_id"] == candidate_b_id
    assert explicit_b["candidate_output_sha256"] == candidate_b_hash
    assert one(
        db, "SELECT supersedes_id FROM correction_decisions WHERE id=%s",
        (explicit_b["decision_id"],),
    )["supersedes_id"] == decision_a["id"]
    replay_b = one(
        db,
        "SELECT public.record_feedback_human_decision_v1(" + ",".join(["%s"] * 10)
        + ") AS result",
        (
            ctx["project"], ctx["take"], owner_user, membership_b["id"],
            candidate_b_id, candidate_b_exposure_id,
            "rewrite_clarity", "accept_proposed", "feedback-taxonomy-v1",
            decision_b_key,
        ),
    )["result"]
    assert replay_b == explicit_b
    with pytest.raises(
        psycopg2.Error,
        match="FEEDBACK_EXACT_IDENTITY_REQUIRED|permission denied",
    ):
        rpc(
            db,
            "record_feedback_human_decision_v1",
            ctx["project"], ctx["take"], owner_user, candidate_b_key,
            "rewrite_clarity", "accept_proposed", "feedback-taxonomy-v1",
            str(uuid4()),
        )


def test_rewrite_and_manual_origins_must_be_proven(db):
    ctx = make_context(db)
    v3 = _v3_context(db, ctx, include_rewrite=True, prove_rewrite=False)
    with pytest.raises(psycopg2.Error, match="ROOT_CONTENT_VERSION_INVALID"):
        rpc(
            db,
            "register_synthetic_root_content_version_v1",
            v3["membership"]["id"],
            v3["rewrite"],
            v3["part"],
            ctx["auth"],
            v3["phrase"],
            0,
            len(v3["phrase"]),
            "accepted_rewrite",
            str(uuid4()),
        )
    with pytest.raises(psycopg2.Error, match="ROOT_CONTENT_VERSION_INVALID"):
        rpc(
            db,
            "register_synthetic_root_content_version_v1",
            v3["membership"]["id"],
            v3["rewrite"],
            v3["part"],
            ctx["auth"],
            v3["paragraph"],
            0,
            len(v3["paragraph"]),
            "manual_edit",
            str(uuid4()),
        )


def test_accepted_rewrite_requires_user_edit_from_the_exact_take(db):
    ctx = make_context(db)
    v3 = _v3_context(db, ctx, include_rewrite=True)
    query(
        db,
        "UPDATE ideal_text_part_revision SET take_session_id=%s "
        "WHERE part_id=%s AND action='user_edit'",
        (str(uuid4()), v3["part"]),
    )
    with pytest.raises(psycopg2.Error, match="ROOT_CONTENT_VERSION_INVALID"):
        rpc(
            db,
            "register_synthetic_root_content_version_v1",
            v3["membership"]["id"],
            v3["rewrite"],
            v3["part"],
            ctx["auth"],
            v3["phrase"],
            0,
            len(v3["phrase"]),
            "accepted_rewrite",
            str(uuid4()),
        )


def test_later_keep_original_supersedes_accepted_rewrite(db):
    ctx = make_context(db)
    v3 = _v3_context(db, ctx, include_rewrite=True)
    owner_user = one(
        db, "SELECT user_id FROM owner_principals WHERE id=%s", (ctx["owner"],)
    )["user_id"]
    accepted = one(db, "SELECT id,candidate_id,candidate_output_sha256 FROM "
                   "correction_decisions WHERE rater_id=%s AND value='accept_proposed'",
                   (owner_user,))
    assert accepted["candidate_id"] == v3["rewrite"]
    assert len(accepted["candidate_output_sha256"]) == 64
    kept = one(
        db,
        "SELECT public.record_feedback_human_decision_v1(" + ",".join(["%s"] * 10)
        + ") AS result",
        (
            ctx["project"], ctx["take"], owner_user,
            v3["membership"]["id"], v3["rewrite"], v3["rewrite_exposure"],
            "rewrite_clarity", "keep_original", "feedback-taxonomy-v1",
            str(uuid4()),
        ),
    )["result"]
    assert one(db, "SELECT supersedes_id FROM correction_decisions WHERE id=%s",
               (kept["decision_id"],))["supersedes_id"] == accepted["id"]
    with pytest.raises(psycopg2.Error, match="ROOT_CONTENT_VERSION_INVALID"):
        rpc(
            db,
            "register_synthetic_root_content_version_v1",
            v3["membership"]["id"],
            v3["rewrite"],
            v3["part"],
            ctx["auth"],
            v3["phrase"],
            0,
            len(v3["phrase"]),
            "accepted_rewrite",
            str(uuid4()),
        )
    assert one(
        db,
        "SELECT count(*) AS n FROM root_phrase_content_versions "
        "WHERE feedback_membership_id=%s",
        (v3["membership"]["id"],),
    )["n"] == 0


def test_keep_original_committed_during_registration_contention_fails_closed(db):
    ctx = make_context(db)
    v3 = _v3_context(db, ctx, include_rewrite=True)
    owner_user = one(
        db, "SELECT user_id FROM owner_principals WHERE id=%s", (ctx["owner"],)
    )["user_id"]
    evidence_id = one(
        db, "SELECT evidence_span_id FROM feedback_candidates WHERE id=%s",
        (v3["rewrite"],),
    )["evidence_span_id"]
    holder = connect()
    holder.autocommit = False
    query(
        holder,
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        (f"canonical-correction:{evidence_id}:{owner_user}",),
    )

    def register_while_decision_changes():
        worker = connect()
        try:
            query(worker, "SET application_name='rpq-decision-waiter'")
            return rpc(
                worker,
                "register_synthetic_root_content_version_v1",
                v3["membership"]["id"],
                v3["rewrite"],
                v3["part"],
                ctx["auth"],
                v3["phrase"],
                0,
                len(v3["phrase"]),
                "accepted_rewrite",
                str(uuid4()),
            )
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(register_while_decision_changes)
        deadline = monotonic() + 5
        while not query(
            db,
            "SELECT 1 FROM pg_stat_activity WHERE application_name=%s "
            "AND wait_event='advisory'",
            ("rpq-decision-waiter",),
        ):
            if monotonic() >= deadline:
                raise AssertionError("registration never waited on correction lock")
            sleep(0.01)
        rpc(
            holder,
            "record_feedback_human_decision_v1",
            ctx["project"],
            ctx["take"],
            owner_user,
            v3["membership"]["id"],
            v3["rewrite"],
            v3["rewrite_exposure"],
            "rewrite_clarity",
            "keep_original",
            "feedback-taxonomy-v1",
            str(uuid4()),
        )
        holder.commit()
        with pytest.raises(psycopg2.Error, match="ROOT_CONTENT_VERSION_INVALID"):
            future.result(timeout=5)
    holder.close()
    assert one(
        db,
        "SELECT count(*) AS n FROM root_phrase_content_versions "
        "WHERE feedback_membership_id=%s",
        (v3["membership"]["id"],),
    )["n"] == 0


def test_semantic_inputs_are_server_derived_and_frozen(db):
    ctx = make_context(db)
    v3 = _v3_context(db, ctx)
    _, content, _ = _direct_qualification(db, ctx, v3)
    semantic_input = one(
        db,
        "SELECT input.* FROM root_phrase_semantic_input_snapshots input "
        "JOIN root_phrase_semantic_results result "
        "ON result.semantic_input_snapshot_id=input.id "
        "WHERE result.content_version_id=%s",
        (content["id"],),
    )
    assert semantic_input["project_goal_snapshot"]["project_setup"]["goal"] == (
        "Explain the product clearly."
    )
    assert semantic_input["slide_context_snapshot"]["paragraphs"] == [
        {"id": v3["part"], "text": v3["paragraph"]}
    ]
    frozen_hash = semantic_input["input_snapshot_sha256"]
    query(db, "UPDATE projects SET setup=%s WHERE id=%s", (Json({"goal": "Changed"}), ctx["project"]))
    assert one(
        db,
        "SELECT input_snapshot_sha256 AS hash FROM root_phrase_semantic_input_snapshots "
        "WHERE id=%s",
        (semantic_input["id"],),
    )["hash"] == frozen_hash


def test_semantic_input_cannot_cross_content_or_project_lineage(db):
    first_ctx = make_context(db)
    first_v3 = _v3_context(db, first_ctx)
    first_content = rpc(
        db,
        "register_synthetic_root_content_version_v1",
        first_v3["membership"]["id"],
        first_v3["confidence"],
        first_v3["part"],
        first_ctx["auth"],
        first_v3["phrase"],
        0,
        len(first_v3["phrase"]),
        "unchanged_manager",
        str(uuid4()),
    )
    first_input = rpc(
        db,
        "freeze_synthetic_root_semantic_input_v1",
        first_content["id"],
        str(uuid4()),
    )

    second_ctx = make_context(db)
    second_v3 = _v3_context(db, second_ctx)
    second_content = rpc(
        db,
        "register_synthetic_root_content_version_v1",
        second_v3["membership"]["id"],
        second_v3["confidence"],
        second_v3["part"],
        second_ctx["auth"],
        second_v3["phrase"],
        0,
        len(second_v3["phrase"]),
        "unchanged_manager",
        str(uuid4()),
    )
    with pytest.raises(psycopg2.Error):
        rpc(
            db,
            "record_synthetic_root_semantic_result_v1",
            second_content["id"],
            first_input["id"],
            "aligned",
            "foreign_input_must_fail",
            "prompt-v1",
            "model-v1",
            "code-v1",
            str(uuid4()),
        )
    assert one(
        db,
        "SELECT count(*) AS n FROM root_phrase_semantic_results "
        "WHERE content_version_id=%s",
        (second_content["id"],),
    )["n"] == 0


def test_combined_action_rolls_back_authoritative_lock_if_root_write_fails(db):
    ctx = make_context(db)
    v3 = _v3_context(db, ctx)
    owner_user, _, qualification = _direct_qualification(db, ctx, v3)
    query(
        db,
        "CREATE FUNCTION reject_test_root_insert() RETURNS trigger LANGUAGE plpgsql "
        "AS $$BEGIN IF NEW.action='root_activate' THEN RAISE EXCEPTION "
        "'synthetic root failure'; END IF; RETURN NEW; END$$",
    )
    query(
        db,
        "CREATE TRIGGER reject_test_root_insert BEFORE INSERT ON root_phrase_product_actions "
        "FOR EACH ROW EXECUTE FUNCTION reject_test_root_insert()",
    )
    with pytest.raises(psycopg2.Error, match="synthetic root failure"):
        rpc(
            db,
            "activate_synthetic_root_phrase_v1",
            qualification["id"],
            owner_user,
            True,
            False,
            str(uuid4()),
        )
    query(db, "DROP TRIGGER reject_test_root_insert ON root_phrase_product_actions")
    query(db, "DROP FUNCTION reject_test_root_insert()")
    assert one(
        db, "SELECT locked_at FROM ideal_text_part WHERE id=%s", (v3["part"],)
    )["locked_at"] is None
    assert one(
        db,
        "SELECT count(*) AS n FROM ideal_text_part_revision WHERE part_id=%s "
        "AND action='lock'",
        (v3["part"],),
    )["n"] == 0
    assert one(
        db,
        "SELECT count(*) AS n FROM root_phrase_product_actions "
        "WHERE project_id=%s",
        (ctx["project"],),
    )["n"] == 0


@pytest.mark.parametrize("revocation", ["policy_expiry", "withdrawal", "deletion"])
def test_direct_activation_revalidates_live_authority_and_source(db, revocation):
    ctx = make_context(db)
    v3 = _v3_context(db, ctx)
    owner_user, _, qualification = _direct_qualification(db, ctx, v3)
    if revocation == "policy_expiry":
        query(db, "UPDATE processing_policy_versions SET retired_at=clock_timestamp() WHERE id=%s", (ctx["policy"],))
    elif revocation == "withdrawal":
        query(
            db,
            "INSERT INTO processing_service_blocks(acquisition_principal_id,effective_at) "
            "VALUES (%s,clock_timestamp())",
            (ctx["owner"],),
        )
    else:
        query(db, "UPDATE processing_audio_objects SET deleted_at=clock_timestamp() WHERE id=%s", (ctx["object"],))
    with pytest.raises(psycopg2.Error):
        rpc(
            db,
            "activate_synthetic_root_phrase_v1",
            qualification["id"],
            owner_user,
            True,
            False,
            str(uuid4()),
        )
    assert one(db, "SELECT locked_at FROM ideal_text_part WHERE id=%s", (v3["part"],))["locked_at"] is None


def test_direct_activation_revalidates_after_block_lock_contention(db):
    ctx = make_context(db)
    v3 = _v3_context(db, ctx)
    owner_user, _, qualification = _direct_qualification(db, ctx, v3)
    activation_key = str(uuid4())
    holder = connect()
    holder.autocommit = False
    query(
        holder,
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        (f"root-block:{ctx['project']}:0:0",),
    )

    def activate_while_waiting():
        worker = connect()
        try:
            query(worker, "SET application_name='rpq-activation-waiter'")
            return rpc(
                worker,
                "activate_synthetic_root_phrase_v1",
                qualification["id"],
                owner_user,
                True,
                False,
                activation_key,
            )
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(activate_while_waiting)
        deadline = monotonic() + 5
        while not query(
            db,
            "SELECT 1 FROM pg_stat_activity WHERE application_name=%s "
            "AND wait_event='advisory'",
            ("rpq-activation-waiter",),
        ):
            if monotonic() >= deadline:
                raise AssertionError("activation never waited on the block lock")
            sleep(0.01)
        query(
            holder,
            "INSERT INTO processing_service_blocks(acquisition_principal_id,effective_at) "
            "VALUES (%s,clock_timestamp())",
            (ctx["owner"],),
        )
        holder.commit()
        with pytest.raises(psycopg2.Error, match="AUTHORIZATION"):
            future.result(timeout=5)
    holder.close()
    assert one(db, "SELECT locked_at FROM ideal_text_part WHERE id=%s", (v3["part"],))["locked_at"] is None


@pytest.mark.parametrize(
    "answer",
    [
        "confident_in_between",
        "confident_no",
        "confident_not_sure",
        "confident_audio_unclear",
    ],
)
def test_direct_path_rejects_every_non_yes_confidence_state(db, answer):
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
        answer,
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
    semantic = _semantic(db, content)
    result = rpc(
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
    assert result["routing_state"] == "blocked_confidence_response"


def test_stale_text_fails_closed_without_rewriting_frozen_history(db):
    ctx = make_context(db)
    v3 = _v3_context(db, ctx)
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
    query(db, "DELETE FROM ideal_text_document_heads WHERE snapshot_id=%s", (v3["snapshot"],))
    with pytest.raises(psycopg2.Error, match="ROOT_CONTENT_SOURCE_NOT_LIVE"):
        _semantic(db, content)
        rpc(
            db,
            "evaluate_synthetic_root_qualification_v1",
            content["id"],
            str(uuid4()),
            None,
            None,
            None,
            "unchanged_confident_voice",
            str(uuid4()),
        )
    assert one(
        db, "SELECT count(*) AS n FROM root_phrase_content_versions WHERE id=%s", (content["id"],)
    )["n"] == 1


def test_rewrite_requires_exact_fresh_offer_practice_and_first_valid_attempt(db):
    ctx = make_context(db)
    v3 = _v3_context(db, ctx, include_rewrite=True)
    source = source_pattern(db, ctx, "confident")
    for version in ctx["versions"]:
        profile(db, version["id"], ["confident"])
    assignment = assign(db, ctx)
    n1 = rpc(
        db,
        "freeze_exercise_n1_pattern_snapshot_v1",
        assignment["id"],
        source["id"],
        str(uuid4()),
    )
    offer = rpc(
        db,
        "freeze_synthetic_exercise_service_offer_v1",
        v3["membership"]["id"],
        v3["confidence"],
        n1["candidate_set_id"],
        ctx["auth"],
        str(uuid4()),
    )
    practice_auth = rpc(
        db,
        "record_exercise_authorization_check_v1",
        ctx["owner"],
        ctx["snapshot"],
        "practice_processing",
        str(uuid4()),
    )
    now = one(db, "SELECT clock_timestamp() AS t")["t"]
    session = rpc(
        db,
        "create_synthetic_exercise_practice_session_v1",
        offer["id"],
        practice_auth["id"],
        v3["phrase"],
        "root-practice-window-v1",
        now,
        one(db, "SELECT clock_timestamp()+interval '10 minutes' AS t")["t"],
        str(uuid4()),
    )
    object_key = "practice/" + uuid4().hex + ".wav"
    recovery = rpc(
        db,
        "reserve_synthetic_practice_upload_v1",
        session["id"],
        ctx["owner"],
        1,
        "local_synthetic",
        "practice",
        object_key,
        "e" * 64,
        str(uuid4()),
    )
    attempt_id, recording_id, object_id = (str(uuid4()) for _ in range(3))
    query(
        db,
        "INSERT INTO processing_recording_attempts(id,acquisition_principal_id,"
        "project_id,recording_id,status) VALUES (%s,%s,%s,%s,'completed')",
        (attempt_id, ctx["owner"], ctx["project"], recording_id),
    )
    query(
        db,
        "INSERT INTO processing_audio_objects(id,acquisition_principal_id,"
        "recording_attempt_id,storage_provider,bucket,object_key,byte_size,"
        "content_type,exact_bytes_sha256,verification_method,deleted_at) VALUES "
        "(%s,%s,%s,'local_synthetic','practice',%s,256,'audio/wav',%s,"
        "'read_after_write_sha256',NULL)",
        (object_id, ctx["owner"], attempt_id, object_key, "e" * 64),
    )
    capture_start = one(db, "SELECT clock_timestamp() AS t")["t"]
    capture_end = one(db, "SELECT clock_timestamp()+interval '2 seconds' AS t")["t"]
    transcript = "  " + v3["phrase"].upper() + "  "
    transcript_hash = one(
        db,
        "SELECT exercise_json_sha256_v1(to_jsonb(%s::text)) AS hash",
        (transcript,),
    )["hash"]
    conditions = {"source": "synthetic_microphone", "sample_rate_hz": 48000}
    attempt_hash = one(
        db,
        "SELECT exercise_json_sha256_v1(jsonb_build_object("
        "'session_id',%s::uuid,'acquisition_principal_id',%s::uuid,"
        "'processing_recording_attempt_id',%s::uuid,"
        "'processing_audio_object_id',%s::uuid,'upload_recovery_id',%s::uuid,"
        "'attempt_index',1,'exact_passage',%s,'transcript_text',%s,"
        "'transcript_sha256',%s,'exact_audio_sha256',%s,'duration_ms',2000,"
        "'capture_started_at',%s::timestamptz,'capture_completed_at',%s::timestamptz,"
        "'recording_conditions',%s::jsonb)) AS hash",
        (
            session["id"],
            ctx["owner"],
            attempt_id,
            object_id,
            recovery["id"],
            v3["phrase"],
            transcript,
            transcript_hash,
            "e" * 64,
            capture_start,
            capture_end,
            Json(conditions),
        ),
    )["hash"]
    attempt = rpc(
        db,
        "attach_synthetic_practice_attempt_v1",
        recovery["id"],
        attempt_id,
        object_id,
        v3["phrase"],
        transcript,
        transcript_hash,
        2000,
        capture_start,
        capture_end,
        Json(conditions),
        attempt_hash,
        str(uuid4()),
    )
    input_hash = one(
        db,
        "SELECT exercise_json_sha256_v1(jsonb_build_object("
        "'attempt_id',%s::uuid,'attempt_sha256',%s,'measurement_revision',1,"
        "'extractor_version','synthetic-extractor-v1',"
        "'feature_schema_version','synthetic-features-v1')) AS hash",
        (attempt["id"], attempt["attempt_sha256"]),
    )["hash"]
    raw, safeguards = {"pace": 4.0}, {"audio_usable": True}
    output_hash = one(
        db,
        "SELECT exercise_json_sha256_v1(jsonb_build_object("
        "'input_sha256',%s,'raw_measurements',%s::jsonb,'safeguards',%s::jsonb)) AS hash",
        (input_hash, Json(raw), Json(safeguards)),
    )["hash"]
    measurement = rpc(
        db,
        "record_synthetic_practice_measurement_v1",
        attempt["id"],
        1,
        "synthetic-extractor-v1",
        "synthetic-features-v1",
        Json(raw),
        Json(safeguards),
        input_hash,
        output_hash,
        str(uuid4()),
    )
    validity_hash = one(
        db,
        "SELECT exercise_json_sha256_v1(jsonb_build_object("
        "'attempt_id',%s::uuid,'attempt_sha256',%s,"
        "'measurement_revision_id',%s::uuid,'measurement_output_sha256',%s,"
        "'baseline_revision',1,'validity','valid','reason_codes','[]'::jsonb,"
        "'validity_contract_version','synthetic-capture-validity-v1')) AS hash",
        (
            attempt["id"],
            attempt["attempt_sha256"],
            measurement["id"],
            measurement["output_sha256"],
        ),
    )["hash"]
    rpc(
        db,
        "record_synthetic_practice_validity_v1",
        attempt["id"],
        measurement["id"],
        1,
        "valid",
        [],
        "synthetic-capture-validity-v1",
        validity_hash,
        str(uuid4()),
    )
    selection = rpc(
        db,
        "freeze_synthetic_practice_selection_v1",
        session["id"],
        ctx["owner"],
        1,
        1,
        str(uuid4()),
    )
    assert selection["selected_attempt_id"] == attempt["id"]
    content = rpc(
        db,
        "register_synthetic_root_content_version_v1",
        v3["membership"]["id"],
        v3["rewrite"],
        v3["part"],
        ctx["auth"],
        v3["phrase"],
        0,
        len(v3["phrase"]),
        "accepted_rewrite",
        str(uuid4()),
    )
    semantic = _semantic(db, content)
    qualification = rpc(
        db,
        "evaluate_synthetic_root_qualification_v1",
        content["id"],
        semantic["id"],
        None,
        None,
        selection["id"],
        "accepted_rewrite",
        str(uuid4()),
    )
    assert qualification["routing_state"] == "eligible_after_rerecord"
    pair = rpc(
        db,
        "freeze_synthetic_exercise_pair_v1",
        session["id"],
        selection["id"],
        1,
        str(uuid4()),
    )
    coach_assignment = rpc(
        db,
        "assign_synthetic_exercise_pair_v1",
        pair["id"],
        ctx["reviewer"],
        "blind_coach",
        str(uuid4()),
    )
    judgment = rpc(
        db,
        "submit_synthetic_exercise_pair_judgment_v1",
        coach_assignment["id"],
        ctx["reviewer"],
        "same",
        str(uuid4()),
    )
    assert judgment["answer"] == "same"
    assert not judgment["serves_user"] and not judgment["dataset_eligible"]
    query(
        db,
        "UPDATE processing_policy_versions SET retired_at=clock_timestamp() "
        "WHERE id=%s",
        (ctx["policy"],),
    )
    owner_user = one(
        db, "SELECT user_id FROM owner_principals WHERE id=%s", (ctx["owner"],)
    )["user_id"]
    with pytest.raises(psycopg2.Error, match="AUTHORIZATION"):
        rpc(
            db,
            "activate_synthetic_root_phrase_v1",
            qualification["id"],
            owner_user,
            True,
            False,
            str(uuid4()),
        )
    query(db, "UPDATE processing_policy_versions SET retired_at=NULL WHERE id=%s", (ctx["policy"],))
    query(
        db,
        "UPDATE processing_audio_objects SET deleted_at=clock_timestamp() WHERE id=%s",
        (object_id,),
    )
    with pytest.raises(psycopg2.Error, match="PRACTICE"):
        rpc(
            db,
            "activate_synthetic_root_phrase_v1",
            qualification["id"],
            owner_user,
            True,
            False,
            str(uuid4()),
        )
    query(db, "UPDATE processing_audio_objects SET deleted_at=NULL WHERE id=%s", (object_id,))

    holder = connect()
    holder.autocommit = False
    query(
        holder,
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        (f"root-block:{ctx['project']}:0:0",),
    )

    def activate_rerecord_while_waiting():
        worker = connect()
        try:
            query(worker, "SET application_name='rpq-rerecord-activation-waiter'")
            return rpc(
                worker,
                "activate_synthetic_root_phrase_v1",
                qualification["id"],
                owner_user,
                True,
                False,
                str(uuid4()),
            )
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(activate_rerecord_while_waiting)
        deadline = monotonic() + 5
        while not query(
            db,
            "SELECT 1 FROM pg_stat_activity WHERE application_name=%s "
            "AND wait_event='advisory'",
            ("rpq-rerecord-activation-waiter",),
        ):
            if monotonic() >= deadline:
                raise AssertionError("re-record activation never waited on the block lock")
            sleep(0.01)
        query(
            holder,
            "INSERT INTO processing_service_blocks(acquisition_principal_id,effective_at) "
            "VALUES (%s,clock_timestamp())",
            (ctx["owner"],),
        )
        holder.commit()
        with pytest.raises(psycopg2.Error):
            future.result(timeout=5)
    holder.close()
    assert one(
        db, "SELECT locked_at FROM ideal_text_part WHERE id=%s", (v3["part"],)
    )["locked_at"] is None


def test_no_match_becomes_post_blind_request_and_draft_only(db):
    ctx = make_context(db)
    v3 = _v3_context(db, ctx)
    source = source_pattern(db, ctx, "confident")
    assignment = assign(db, ctx)
    n1 = rpc(
        db,
        "freeze_exercise_n1_pattern_snapshot_v1",
        assignment["id"],
        source["id"],
        str(uuid4()),
    )
    offer = rpc(
        db,
        "freeze_synthetic_exercise_service_offer_v1",
        v3["membership"]["id"],
        v3["confidence"],
        n1["candidate_set_id"],
        ctx["auth"],
        str(uuid4()),
    )
    assert offer["outcome"] == "synthetic_no_match"
    packet = make_packet(db, ctx)
    request_key = str(uuid4())
    with pytest.raises(
        psycopg2.Error,
        match="EXERCISE_SERVICE_REQUEST_REQUIRES_EXACT_POST_BLIND_REVEAL",
    ):
        rpc(
            db,
            "register_synthetic_service_no_match_request_v1",
            offer["id"],
            packet["id"],
            ctx["reviewer"],
            request_key,
        )
    reveal_packet(db, ctx, packet)
    request = rpc(
        db,
        "register_synthetic_service_no_match_request_v1",
        offer["id"],
        packet["id"],
        ctx["reviewer"],
        request_key,
    )
    draft = rpc(
        db,
        "create_synthetic_exercise_authoring_draft_v1",
        request["id"],
        ctx["reviewer"],
        "Record a concise synthetic exercise for this exact need.",
        str(uuid4()),
    )
    assert request["state"] == "synthetic_post_blind_pending"
    assert draft["state"] == "synthetic_draft"
    assert draft["target_need_contract_id"] == ctx["need"]
    assert not request["serves_user"] and not request["dataset_eligible"]
    assert not draft["serves_user"] and not draft["dataset_eligible"]


def test_schema_is_rpc_only_append_only_and_non_serving(db):
    for table in (
        "feedback_v3_memberships",
        "exercise_practice_sessions",
        "exercise_service_offers",
        "exercise_pair_revisions",
        "root_phrase_content_versions",
        "root_phrase_semantic_input_snapshots",
        "root_phrase_semantic_results",
        "root_phrase_product_actions",
        "root_phrase_block_heads",
    ):
        assert one(
            db,
            "SELECT relrowsecurity AS enabled FROM pg_class WHERE oid=%s::regclass",
            (table,),
        )["enabled"]
        assert not one(
            db,
            "SELECT has_table_privilege('service_role',%s,'INSERT') AS allowed",
            (table,),
        )["allowed"]
    with pytest.raises(psycopg2.Error):
        query(
            db,
            "INSERT INTO root_phrase_block_heads(acquisition_principal_id,project_id,"
            "slide_index,block_key,interaction_state_revision) "
            "VALUES (%s,%s,0,0,1)",
            (str(uuid4()), str(uuid4())),
        )
    assert one(
        db,
        "SELECT to_regprocedure(%s) IS NULL AS closed",
        (
            "public.register_synthetic_root_content_version_v1("
            "uuid,uuid,uuid,text,integer,integer,text,text)",
        ),
    )["closed"]
    assert one(
        db,
        "SELECT to_regprocedure(%s) IS NULL AS closed",
        (
            "public.record_synthetic_root_semantic_result_v1("
            "uuid,text,text,text,text,text,text,text,text)",
        ),
    )["closed"]
