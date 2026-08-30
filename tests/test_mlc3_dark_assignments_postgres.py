"""Executable rejection/reproduction tests; disposable PostgreSQL ONLY.

Load integration/mlc3_assignment_prerequisites.sql, 0313 and 0314 into an
empty willab_m33_* database, then set MLC3_REHEARSAL_DSN. No provider calls,
real audio, user exposure, dataset creation or model evaluation occurs here.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import hashlib
import itertools
import json
import os
import threading
from time import monotonic, sleep
from uuid import uuid4

import psycopg2
from psycopg2.extras import Json, RealDictCursor
import pytest


DSN = os.environ.get("MLC3_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="disposable M3-3 PostgreSQL rehearsal only")
_counter = itertools.count()


def connect():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_m33_"):
        raise RuntimeError("Refusing a non-disposable database")
    if not parsed.get("host", "").startswith(("/tmp/willab-", "/private/tmp/willab-")):
        raise RuntimeError("Refusing a non-local rehearsal host")
    c = psycopg2.connect(DSN)
    c.autocommit = True
    return c


def query(c, sql, params=()):
    with c.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else []


def one(c, sql, params=()):
    return query(c, sql, params)[0]


def rpc(c, name, *args):
    # Names come only from this checked-in test, never external input.
    query(c, "SET ROLE service_role")
    try:
        return one(c, f"SELECT * FROM public.{name}({','.join(['%s'] * len(args))})", args)
    finally:
        if c.get_transaction_status() != psycopg2.extensions.TRANSACTION_STATUS_INERROR:
            query(c, "RESET ROLE")


@pytest.fixture
def db():
    c = connect()
    yield c
    c.close()


def add_prediction(c, ctx, *, features=None, quality="usable", detector="voice-confidence-universal-v3"):
    run, prediction = str(uuid4()), str(uuid4())
    query(c, "INSERT INTO ml_model_runs VALUES (%s,'confidence_classification','succeeded',clock_timestamp()-interval '1 minute','fixture-code-v1')", (run,))
    query(c, "INSERT INTO ml_classification_runs VALUES (%s,%s,'m33-test-features-v1','fixture-extractor-v1')", (run, detector))
    query(c, "INSERT INTO ml_machine_predictions VALUES (%s,%s,%s,'mlc3-acoustic-observation-v1',%s)",
          (prediction, run, ctx["evidence"], Json({"acoustic_features": {"pace": 4} if features is None else features, "audio_quality": quality})))
    return prediction


def observe(c, ctx, **kwargs):
    prediction = add_prediction(c, ctx, **kwargs)
    return rpc(c, "record_exercise_profile_observation_v1", ctx["lineage"], ctx["need"], prediction, ctx["auth"])


def add_exercise(c, ctx, *, state="active", safety="approved", language=None, key=None, version=1, need=None):
    media = rpc(c, "register_exercise_media_object_v1", "synthetic-exercises", str(uuid4()), "c" * 64,
                1024, "video/mp4", "read_after_write_sha256", one(c, "SELECT clock_timestamp() AS t")["t"],
                "synthetic-only", "rehearsal")
    exercise = rpc(c, "register_exercise_version_v1", key or "exercise-" + uuid4().hex, "willab_library", None,
                   language or ctx["language"], version, need or ctx["need"], media["id"], "Synthetic exercise.",
                   safety, state, "rehearsal")
    rpc(c, "record_exercise_media_availability_v1", media["id"], "available", "c" * 64, "d" * 64,
        one(c, "SELECT clock_timestamp() AS t")["t"], str(uuid4()))
    return exercise


def catalogue(c, ctx, scope="context"):
    return rpc(c, "finalize_exercise_catalog_snapshot_v2",
               ctx["language"] if scope == "context" else scope, str(uuid4()), "rehearsal")["id"]


def assign(c, ctx, **changes):
    values = {**ctx, **changes}
    return rpc(c, "finalize_exercise_dark_assignment_v1", values["lineage"], values["need"], values["observation"],
               values["catalog"], values["block"], values["language"], values["auth"], values["key"])


@pytest.fixture
def ctx(db):
    return make_context(db)


def make_context(db, *, speaker=None, create_frame=True):
    index = next(_counter)
    x = {name: str(uuid4()) for name in ("owner", "reviewer", "speaker", "project", "take", "recording", "snippet",
         "policy", "receipt", "snapshot", "object", "ml_object", "evidence")}
    if speaker is not None:
        x["speaker"] = speaker
    x.update(language="q" + chr(ord("a") + index % 26), block="speech-block:" + uuid4().hex, key=str(uuid4()))
    query(db, "INSERT INTO owner_principals(id,user_id) VALUES (%s,%s),(%s,%s)", (x["owner"], str(uuid4()), x["reviewer"], str(uuid4())))
    query(db, "INSERT INTO projects(id,owner_principal_id) VALUES (%s,%s)", (x["project"], x["owner"]))
    query(db, "INSERT INTO v2_sessions(id,owner_principal_id,project_id,recording_1_id) VALUES (%s,%s,%s,%s)", (x["take"], x["owner"], x["project"], x["recording"]))
    query(db, "INSERT INTO recording_attempts VALUES (%s,%s,%s)", (x["take"], x["owner"], x["project"]))
    query(db, "INSERT INTO takes VALUES (%s,%s,%s,%s)", (x["take"], x["take"], x["owner"], x["project"]))
    query(db, "INSERT INTO snippets VALUES (%s,%s,%s,1250,2400)", (x["snippet"], x["take"], x["recording"]))
    query(db, "INSERT INTO processing_policy_versions VALUES (%s,%s,'active',clock_timestamp()-interval '1 hour',NULL)", (x["policy"], str(uuid4())))
    query(db, "INSERT INTO processing_policy_purposes VALUES (%s,'personalized_exercise_recommendation')", (x["policy"],))
    query(db, "INSERT INTO processing_authorization_receipts VALUES (%s,%s,%s)", (x["receipt"], x["owner"], x["policy"]))
    query(db, "INSERT INTO processing_authorization_receipt_purposes VALUES (%s,'personalized_exercise_recommendation')", (x["receipt"],))
    query(db, "INSERT INTO processing_authorization_snapshots VALUES (%s,%s,%s,%s,'personalized_exercise_recommendation')", (x["snapshot"], x["owner"], x["receipt"], x["policy"]))
    query(db, "UPDATE processing_purpose_registry SET operational=true,authorizes_processing=true WHERE id='personalized_exercise_recommendation'")
    query(db, "INSERT INTO processing_recording_attempts VALUES (%s,%s,%s,%s)", (x["take"], x["owner"], x["project"], x["recording"]))
    object_key = str(uuid4())
    query(db, "INSERT INTO processing_audio_objects VALUES (%s,%s,%s,'r2','synthetic-recordings',%s,1024,'audio/wav',%s,'read_after_write_sha256',NULL)", (x["object"], x["owner"], x["take"], object_key, "a" * 64))
    query(db, "INSERT INTO ml_speakers VALUES (%s) ON CONFLICT DO NOTHING", (x["speaker"],))
    query(db, "INSERT INTO ml_speaker_principals VALUES (%s,%s)", (x["speaker"], x["owner"]))
    query(db, "INSERT INTO ml_object_artifacts VALUES (%s,%s,%s,'cloudflare_r2','synthetic-recordings',%s,%s,1024,'audio/wav','audio')", (x["ml_object"], x["owner"], x["speaker"], object_key, "a" * 64))
    query(db, "INSERT INTO ml_evidence_spans VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (x["evidence"], x["owner"], x["speaker"], x["project"], x["take"], x["take"], x["ml_object"], Json({"start_ms": 1250, "end_ms": 3650})))
    for op, field in (("profile_identity", "profile_auth"), ("source_audio_lineage", "audio_auth"), ("catalog_assignment", "auth"), ("blind_review_preparation", "blind_auth")):
        x[field] = rpc(db, "record_exercise_authorization_check_v1", x["owner"], x["snapshot"], op, str(uuid4()))["id"]
    x["profile"] = rpc(db, "ensure_learning_profile_v1", x["speaker"], x["owner"], x["profile_auth"], "exercise-profile-v1", str(uuid4()))["id"]
    x["lineage"] = rpc(db, "register_exercise_audio_lineage_v1", x["owner"], x["speaker"], x["profile"], x["audio_auth"], x["object"], x["project"], x["take"], x["take"], x["recording"], x["snippet"], 1250, 2400, "exercise-audio-lineage-v1", str(uuid4()))["id"]
    x["need"] = rpc(db, "register_exercise_need_contract_v1", "synthetic-" + uuid4().hex, 1, "approved",
                    Json({"assignment_gate": {"schema_version": "exercise-need-gate-v1", "feature_ranges": {"pace": {"min": 2, "max": 8}}}}),
                    ["pace"], ["pace"], ["audio_unclear"], Json([]), "m33-test-features-v1", "SYNTHETIC-NOT-PRODUCT-APPROVAL", "b" * 64, "rehearsal")["id"]
    x["observation"] = observe(db, x)["id"]
    second_snippet, second_evidence = str(uuid4()), str(uuid4())
    x["second_block"] = "speech-block:" + uuid4().hex
    query(db, "INSERT INTO snippets VALUES (%s,%s,%s,5000,2400)", (second_snippet, x["take"], x["recording"]))
    query(db, "INSERT INTO ml_evidence_spans VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (second_evidence, x["owner"], x["speaker"], x["project"], x["take"], x["take"], x["ml_object"], Json({"start_ms": 5000, "end_ms": 7400})))
    x["second_lineage"] = rpc(db, "register_exercise_audio_lineage_v1", x["owner"], x["speaker"], x["profile"], x["audio_auth"], x["object"], x["project"], x["take"], x["take"], x["recording"], second_snippet, 5000, 2400, "exercise-audio-lineage-v1", str(uuid4()))["id"]
    x["second_observation"] = observe(db, {**x, "lineage": x["second_lineage"], "evidence": second_evidence})["id"]
    candidate = {"candidate_id": "candidate-" + x["snippet"], "snippet_id": x["snippet"], "eligibility": "eligible",
                 "clip_identity": {"take_id": x["take"], "recording_id": x["recording"], "snippet_id": x["snippet"], "start_offset_ms": 1250, "duration_ms": 2400}}
    frame = {"blocks": [{"block_id": x["block"], "selected_candidate_id": candidate["candidate_id"], "confidence_candidates": [candidate]}],
             "implementation_versions": {"confidence_detector_version": "voice-confidence-universal-v3", "source_code_sha256": "f" * 64}}
    second_candidate = {**candidate, "candidate_id": "candidate-" + second_snippet, "snippet_id": second_snippet,
                        "clip_identity": {**candidate["clip_identity"], "snippet_id": second_snippet, "start_offset_ms": 5000}}
    frame["blocks"].append({"block_id": x["second_block"], "selected_candidate_id": second_candidate["candidate_id"], "confidence_candidates": [second_candidate]})
    x["source_frame"] = frame
    if create_frame:
        insert_source_frame(db, x)
    x["versions"] = [add_exercise(db, x) for _ in range(3)]
    x["catalog"] = catalogue(db, x)
    return x


def insert_source_frame(db, ctx):
    query(db, "INSERT INTO take_feedback_policy_v3_shadow_frames(take_session_id,recording_id,policy_version,acquisition_principal_id,frame,frame_hash) VALUES (%s,%s,'take-feedback-policy-v3-universal-dark-v3',%s,%s,%s)",
          (ctx["take"], ctx["recording"], ctx["owner"], Json(ctx["source_frame"]), "e" * 64))


def wait_for_lock(db, application, event):
    deadline = monotonic() + 5
    while not query(db, "SELECT 1 FROM pg_stat_activity WHERE application_name=%s AND wait_event=%s", (application, event)):
        if monotonic() >= deadline:
            raise AssertionError(f"worker never reached {event} wait")
        sleep(0.01)


def assignment_during_wait(db, ctx, mutation, **changes):
    """Change live state only after the assignment has captured its snapshot."""
    holder = connect()
    holder.autocommit = False
    query(holder, "SELECT pg_advisory_xact_lock(hashtextextended('exercise-profile:' || %s || ':' || %s,0))",
          (ctx["speaker"], ctx["need"]))
    application = "m33_assignment_" + uuid4().hex

    def work():
        c = connect()
        try:
            query(c, "SET application_name=%s", (application,))
            return assign(c, ctx, **changes)
        finally:
            c.close()

    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(work)
            try:
                wait_for_lock(db, application, "advisory")
                mutation()
            finally:
                holder.commit()
            return future.result(timeout=5)
    finally:
        holder.rollback()
        holder.close()


def test_complete_pool_probability_rng_hash_and_zero_exposure(db, ctx):
    a = assign(db, ctx)
    frame = one(db, "SELECT * FROM exercise_candidate_sets WHERE id=%s", (a["id"],))
    candidates = query(db, "SELECT * FROM exercise_candidates WHERE candidate_set_id=%s", (a["id"],))
    assert len(candidates) == frame["candidate_count"]
    eligible = [c for c in candidates if c["eligibility"] == "eligible"]
    assert len(eligible) == 3
    assert sum(c["probability"] for c in eligible) == Decimal(1)
    assert sorted(c["probability"] for c in eligible) == [Decimal("0.1"), Decimal("0.1"), Decimal("0.8")]
    rng = one(db, "SELECT * FROM exercise_randomization_assignments WHERE assignment_id=%s", (a["id"],))
    digest = hashlib.sha256(bytes(rng["protected_seed"]) + rng["randomization_unit_sha256"].encode()).hexdigest()
    draw = Decimal(int(digest[:13], 16)) / Decimal(2**52)
    assert abs(draw - rng["draw"]) < Decimal("1e-19")
    assert hashlib.sha256(bytes(rng["protected_seed"])).hexdigest() == rng["seed_commitment_sha256"]
    expected_rank = 1 if draw < Decimal("0.8") else 2 + int((draw - Decimal("0.8")) * 10)
    assert rng["selected_rank"] == expected_rank
    assert a["selected_exercise_version_id"] == next(c["exercise_version_id"] for c in eligible if c["deterministic_rank"] == expected_rank)
    assert one(db, "SELECT pool_sha256 = exercise_json_sha256_v1(inventory) AS ok FROM exercise_candidate_sets WHERE id=%s", (a["id"],))["ok"]
    assert frame["rendered_exposure_id"] is None
    assert not a["serves_user"] and not a["dataset_eligible"]
    assert rng["causal_evaluation_exclusion"] == "dark_non_exposure"


def test_inventory_retains_inactive_rejected_and_wrong_need(db, ctx):
    draft = add_exercise(db, ctx, state="draft", safety="pending_review")
    retired = add_exercise(db, ctx, state="retired")
    ctx["catalog"] = catalogue(db, ctx)
    a = assign(db, ctx)
    rows = query(db, "SELECT exercise_version_id,eligibility,exclusion_reasons FROM exercise_candidates WHERE candidate_set_id=%s", (a["id"],))
    assert any(r["exercise_version_id"] == draft["id"] and "safety_not_approved" in r["exclusion_reasons"] for r in rows)
    assert any(r["exercise_version_id"] == retired["id"] and "inactive_version" in r["exclusion_reasons"] for r in rows)


@pytest.mark.parametrize("quality,features,reason", [("audio_unclear", {"pace": 4}, "audio_unclear"), ("unreliable", {"pace": 4}, "audio_unreliable"), ("usable", {}, "missing_need_features"), ("usable", {"pace": 20}, "need_outside_contract")])
def test_no_invented_evidence(db, ctx, quality, features, reason):
    ctx["observation"] = observe(db, ctx, quality=quality, features=features)["id"]
    a = assign(db, ctx)
    assert a["outcome"] == "dark_no_match"
    rows = query(db, "SELECT exclusion_reasons FROM exercise_candidates WHERE candidate_set_id=%s", (a["id"],))
    assert rows and all(reason in r["exclusion_reasons"] for r in rows)
    with pytest.raises(psycopg2.Error, match="EXERCISE_REQUEST_SOURCE_NOT_ACTIONABLE"):
        rpc(db, "register_exercise_no_match_request_v1", a["id"], str(uuid4()), ctx["reviewer"], ctx["auth"], str(uuid4()))


def test_observation_wrong_detector_and_unapproved_feature_fail(db, ctx):
    with pytest.raises(psycopg2.Error, match="OBSERVATION_PROVENANCE_INVALID"):
        observe(db, ctx, detector="voice-confidence-v2")
    with pytest.raises(psycopg2.Error, match="FEATURE_CONTRACT_INVALID"):
        observe(db, ctx, features={"pace": 4, "emotion": 1})


def test_source_interval_mismatch_and_deleted_audio_fail(db, ctx):
    query(db, "UPDATE snippets SET duration_ms=2401 WHERE id=%s", (ctx["snippet"],))
    with pytest.raises(psycopg2.Error, match="SOURCE_MISMATCH"):
        assign(db, ctx)
    query(db, "UPDATE snippets SET duration_ms=2400 WHERE id=%s", (ctx["snippet"],))
    a = assign(db, ctx)
    query(db, "UPDATE processing_audio_objects SET deleted_at=clock_timestamp() WHERE id=%s", (ctx["object"],))
    with pytest.raises(psycopg2.Error, match="SOURCE_MISMATCH"):
        assign(db, ctx)
    assert a["serves_user"] is False


def test_replay_is_same_frame_and_changed_input_conflicts(db, ctx):
    a = assign(db, ctx)
    rng = one(db, "SELECT * FROM exercise_randomization_assignments WHERE assignment_id=%s", (a["id"],))
    assert assign(db, ctx)["id"] == a["id"]
    assert assign(db, ctx, key=str(uuid4()))["id"] == a["id"]
    assert one(db, "SELECT * FROM exercise_randomization_assignments WHERE assignment_id=%s", (a["id"],)) == rng
    with pytest.raises(psycopg2.Error, match="REPLAY_CONFLICT"):
        assign(db, ctx, language="zz")


def test_revocation_blocks_creation_and_replay(db, ctx):
    assign(db, ctx)
    query(db, "INSERT INTO processing_service_blocks(acquisition_principal_id,effective_at) VALUES (%s,clock_timestamp())", (ctx["owner"],))
    with pytest.raises(psycopg2.Error, match="CURRENT_AUTHORIZATION_REVOKED"):
        assign(db, ctx)
    with pytest.raises(psycopg2.Error, match="CURRENT_AUTHORIZATION_REVOKED"):
        observe(db, ctx)


@pytest.mark.parametrize("mutation", ["policy", "receipt", "operation"])
def test_live_policy_purpose_receipt_and_operation(db, ctx, mutation):
    if mutation == "policy":
        query(db, "DELETE FROM processing_policy_purposes WHERE policy_id=%s", (ctx["policy"],))
    elif mutation == "receipt":
        query(db, "DELETE FROM processing_authorization_receipt_purposes WHERE receipt_id=%s", (ctx["receipt"],))
    else:
        ctx["auth"] = ctx["blind_auth"]
    with pytest.raises(psycopg2.Error, match="CURRENT_AUTHORIZATION"):
        assign(db, ctx)


def test_feature_snapshot_never_backfills_later_observations(db, ctx):
    a = assign(db, ctx)
    before = one(db, "SELECT * FROM exercise_selection_feature_snapshots WHERE id=%s", (a["id"],))
    newer = observe(db, ctx, features={"pace": 7})
    assert newer["id"] not in str(before["snapshot"])
    assert assign(db, ctx)["id"] == a["id"]
    assert one(db, "SELECT * FROM exercise_selection_feature_snapshots WHERE id=%s", (a["id"],)) == before
    assert before["snapshot"]["baseline_version"] == "not_used-dark-v1"


def test_same_transaction_observation_not_misrepresented_as_prior_commit(db, ctx):
    prediction = add_prediction(db, ctx)
    db.autocommit = False
    try:
        observed = rpc(db, "record_exercise_profile_observation_v1", ctx["lineage"], ctx["need"], prediction, ctx["auth"])
        with pytest.raises(psycopg2.Error, match="SOURCE_NOT_COMMITTED_ASOF"):
            assign(db, ctx, observation=observed["id"])
    finally:
        db.rollback()
        db.autocommit = True
    assert not query(db, "SELECT * FROM exercise_assignments WHERE idempotency_key=%s", (ctx["key"],))


def test_concurrent_first_creation_effectively_once(db, ctx):
    barrier = threading.Barrier(2)

    def run():
        c = connect()
        try:
            barrier.wait(timeout=10)
            return assign(c, ctx)["id"]
        finally:
            c.close()

    with ThreadPoolExecutor(max_workers=2) as workers:
        ids = list(workers.map(lambda _: run(), range(2)))
    assert ids[0] == ids[1]
    assert one(db, "SELECT count(*) AS n FROM exercise_assignments WHERE idempotency_key=%s", (ctx["key"],))["n"] == 1


def test_unavailable_media_is_excluded_not_discarded(db, ctx):
    v = ctx["versions"][0]
    rpc(db, "record_exercise_media_availability_v1", v["media_object_id"], "checksum_mismatch", "f" * 64, "d" * 64,
        one(db, "SELECT clock_timestamp() AS t")["t"], str(uuid4()))
    a = assign(db, ctx)
    row = one(db, "SELECT * FROM exercise_candidates WHERE candidate_set_id=%s AND exercise_version_id=%s", (a["id"], v["id"]))
    assert row["eligibility"] == "excluded" and "media_unavailable" in row["exclusion_reasons"]


def test_catalog_stale_rejected(db, ctx):
    add_exercise(db, ctx, state="retired")
    with pytest.raises(psycopg2.Error, match="CATALOG_STALE"):
        assign(db, ctx)


def test_schema_permissions_and_dark_checks(db, ctx):
    a = assign(db, ctx)
    for table in ("learning_profile_observations", "exercise_selection_feature_snapshots", "exercise_candidate_sets",
                  "exercise_candidates", "exercise_assignments", "exercise_randomization_assignments", "exercise_requests"):
        assert one(db, "SELECT relrowsecurity AS enabled FROM pg_class WHERE oid=%s::regclass", (table,))["enabled"]
        assert not one(db, "SELECT has_table_privilege('service_role',%s,'INSERT') AS allowed", (table,))["allowed"]
        assert not one(db, "SELECT has_table_privilege('authenticated',%s,'SELECT') AS allowed", (table,))["allowed"]
    with pytest.raises(psycopg2.Error, match="append-only"):
        query(db, "UPDATE exercise_assignments SET serves_user=true WHERE id=%s", (a["id"],))
    with pytest.raises(psycopg2.Error, match="append-only"):
        query(db, "DELETE FROM exercise_assignments WHERE id=%s", (a["id"],))
    query(db, "SET ROLE service_role")
    try:
        with pytest.raises(psycopg2.Error, match="permission denied"):
            query(db, "SELECT exercise_rng_draw_v1(%s,%s)", (b"x" * 32, "a" * 64))
    finally:
        query(db, "RESET ROLE")


def test_missing_and_unknown_gate_remain_exclusions(db, ctx):
    need = one(db, "SELECT * FROM exercise_need_contracts WHERE id=%s", (ctx["need"],))
    # Pure helper testing uses a composite value, not mutation of the contract.
    for gate in ({}, {"assignment_gate": {"schema_version": "unknown", "feature_ranges": {}}},
                 {"assignment_gate": {"schema_version": "exercise-need-gate-v1", "feature_ranges": {"pace": {"min": "wrong"}}}}):
        need["operational_definition"] = gate
        result = one(db, "SELECT exercise_need_gate_reasons_v1(jsonb_populate_record(NULL::exercise_need_contracts,%s),%s,'usable') AS reasons",
                     (Json(need, dumps=lambda obj: json.dumps(obj, default=str)), Json({"pace": 4})))
        assert "unreproducible_gate" in result["reasons"]


def make_packet(c, ctx):
    assignment, packet, reference = (str(uuid4()) for _ in range(3))
    digest = one(c, "SELECT exercise_json_sha256_v1(build_exercise_blind_visible_payload_v1(%s,%s,'confidence-exercise-blind-packet-v1','confidence-five-state-v1',%s,2400,%s,NULL)) AS h",
                 (packet, assignment, reference, ctx["language"]))["h"]
    query(c, "INSERT INTO ml_review_assignments VALUES (%s,'confidence_classification',%s,%s,%s,'confidence-five-state-v1')",
          (assignment, ctx["evidence"], ctx["reviewer"], digest))
    return rpc(c, "register_exercise_blind_packet_v1", packet, assignment, ctx["lineage"], ctx["blind_auth"], ctx["reviewer"],
               "confidence-exercise-blind-packet-v1", "confidence-five-state-v1", reference,
               one(c, "SELECT clock_timestamp()+interval '10 minutes' AS t")["t"], 2400, ctx["language"], None,
               "blind-policy-v1", str(uuid4()))


def reveal_packet(c, ctx, packet):
    judgment = str(uuid4())
    query(c, "INSERT INTO ml_judgments(id,review_assignment_id,learning_surface_id,evidence_span_id,actor_provenance,actor_principal_id,decision) VALUES (%s,%s,'confidence_classification',%s,'blind_coach',%s,'rating_not_sure')",
          (judgment, packet["review_assignment_id"], ctx["evidence"], ctx["reviewer"]))
    for event in ("blind_packet_accessed", "blind_judgment_submitted", "post_judgment_reveal_granted", "post_judgment_reveal_accessed"):
        query(c, "INSERT INTO exercise_blind_packet_events(blind_packet_id,review_assignment_id,event_kind,actor_principal_id,judgment_id,blindness_policy_version,idempotency_key,occurred_at) VALUES (%s,%s,%s,%s,%s,'blind-policy-v1',%s,clock_timestamp())",
              (packet["id"], packet["review_assignment_id"], event, ctx["reviewer"], judgment if event == "blind_judgment_submitted" else None, str(uuid4())))
    return judgment


def test_no_match_request_requires_exact_post_blind_reveal(db, ctx):
    # Empty catalogue is honest absence, not a fabricated recommendation.
    ctx["language"] = "zz"
    ctx["catalog"] = catalogue(db, ctx)
    a = assign(db, ctx)
    assert a["outcome"] == "dark_no_match"
    packet = make_packet(db, ctx)
    key = str(uuid4())
    with pytest.raises(psycopg2.Error, match="REQUIRES_EXACT_POST_BLIND_REVEAL"):
        rpc(db, "register_exercise_no_match_request_v1", a["id"], packet["id"], ctx["reviewer"], ctx["auth"], key)
    judgment = reveal_packet(db, ctx, packet)
    r = rpc(db, "register_exercise_no_match_request_v1", a["id"], packet["id"], ctx["reviewer"], ctx["auth"], key)
    assert r["state"] == "dark_pending" and r["judgment_id"] == judgment
    assert not r["serves_user"] and not r["dataset_eligible"]
    assert rpc(db, "register_exercise_no_match_request_v1", a["id"], packet["id"], ctx["reviewer"], ctx["auth"], key)["id"] == r["id"]
    with pytest.raises(psycopg2.Error, match="REQUIRES_EXACT_POST_BLIND_REVEAL"):
        rpc(db, "register_exercise_no_match_request_v1", a["id"], packet["id"], ctx["owner"], ctx["auth"], str(uuid4()))
    query(db, "INSERT INTO processing_service_blocks(acquisition_principal_id,effective_at) VALUES (%s,clock_timestamp())", (ctx["owner"],))
    with pytest.raises(psycopg2.Error, match="CURRENT_AUTHORIZATION_REVOKED"):
        rpc(db, "register_exercise_no_match_request_v1", a["id"], packet["id"], ctx["reviewer"], ctx["auth"], key)


def test_selected_frame_cannot_create_no_match_request(db, ctx):
    a = assign(db, ctx)
    with pytest.raises(psycopg2.Error, match="REQUIRES_NO_MATCH"):
        rpc(db, "register_exercise_no_match_request_v1", a["id"], str(uuid4()), ctx["reviewer"], ctx["auth"], str(uuid4()))


def test_singleton_probability_and_low_probability_inventory(db, ctx):
    for version in ctx["versions"][:2]:
        rpc(db, "record_exercise_media_availability_v1", version["media_object_id"], "missing", None, "d" * 64,
            one(db, "SELECT clock_timestamp() AS t")["t"], str(uuid4()))
    a = assign(db, ctx)
    rng = one(db, "SELECT * FROM exercise_randomization_assignments WHERE assignment_id=%s", (a["id"],))
    assert rng["selection_mode"] == "deterministic_singleton"
    c = one(db, "SELECT probability FROM exercise_candidates WHERE candidate_set_id=%s AND eligibility='eligible'", (a["id"],))
    assert c["probability"] == 1


def test_small_exploration_probabilities_are_typed_excluded_from_causal_evaluation(db, ctx):
    for _ in range(20):
        add_exercise(db, ctx)
    ctx["catalog"] = catalogue(db, ctx)
    a = assign(db, ctx)
    candidates = query(db, "SELECT * FROM exercise_candidates WHERE candidate_set_id=%s AND eligibility='eligible' ORDER BY deterministic_rank", (a["id"],))
    assert candidates[0]["probability"] == Decimal("0.8")
    assert all(c["probability_floor_reason"] == "insufficient_assignment_probability" for c in candidates[1:])
    assert abs(sum(c["probability"] for c in candidates) - 1) < Decimal("1e-15")
    assert all(c["probability_numerator"] == 1 and c["probability_denominator"] == 110 for c in candidates[1:])


def test_cross_principal_prediction_cannot_enter_source_profile(db, ctx):
    foreign = str(uuid4())
    query(db, "INSERT INTO owner_principals(id) VALUES (%s)", (foreign,))
    query(db, "UPDATE ml_evidence_spans SET acquisition_principal_id=%s WHERE id=%s", (foreign, ctx["evidence"]))
    with pytest.raises(psycopg2.Error, match="OBSERVATION_PROVENANCE_INVALID"):
        observe(db, ctx)


def test_late_committed_observation_excluded_from_frozen_asof_snapshot(db, ctx):
    # Hold the exact profile lock so the finalizer captures its snapshot,
    # then commit an observation that was unavailable at that instant.
    holder, writer = connect(), connect()
    holder.autocommit = False
    writer.autocommit = False
    query(holder, "SELECT pg_advisory_xact_lock(hashtextextended('exercise-profile:' || %s || ':' || %s,0))", (ctx["speaker"], ctx["need"]))
    prediction = add_prediction(db, ctx)
    observed = rpc(writer, "record_exercise_profile_observation_v1", ctx["lineage"], ctx["need"], prediction, ctx["auth"])
    started = threading.Event()

    def work():
        c = connect()
        try:
            query(c, "SET application_name='m33_asof_waiter'")
            started.set()
            return assign(c, ctx)
        finally:
            c.close()

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(work)
            assert started.wait(5)
            # Read-only bounded polling; wait for the actual advisory-lock wait,
            # not a timing guess. The test fails instead of hanging indefinitely.
            from time import monotonic, sleep
            try:
                deadline = monotonic() + 5
                while not query(db, "SELECT 1 FROM pg_stat_activity WHERE application_name='m33_asof_waiter' AND wait_event='advisory'"):
                    if monotonic() >= deadline:
                        raise AssertionError("finalizer never reached keyed lock")
                    sleep(0.01)
                writer.commit()
            finally:
                holder.commit()
            a = future.result(timeout=5)
        snapshot = one(db, "SELECT snapshot FROM exercise_selection_feature_snapshots WHERE id=%s", (a["id"],))["snapshot"]
        assert observed["id"] not in [v["id"] for v in snapshot["profile_observations"]]
        assert {"id": observed["id"], "reason": "not_available_asof"} in snapshot["excluded_observations"]
    finally:
        holder.rollback()
        writer.rollback()
        holder.close()
        writer.close()


def test_repeat_inventory_excludes_previous_dark_selection(db, ctx):
    first = assign(db, ctx)
    second = assign(db, ctx, lineage=ctx["second_lineage"], observation=ctx["second_observation"], block=ctx["second_block"], key=str(uuid4()))
    rng = one(db, "SELECT * FROM exercise_randomization_assignments WHERE assignment_id=%s", (second["id"],))
    assert rng["repetition_state"] == "repeated_dark_assignment"
    assert one(db, "SELECT to_jsonb(prior_assignment_ids) AS ids FROM exercise_randomization_assignments WHERE assignment_id=%s", (second["id"],))["ids"] == [first["id"]]
    previous = one(db, "SELECT * FROM exercise_candidates WHERE candidate_set_id=%s AND exercise_version_id=%s", (second["id"], first["selected_exercise_version_id"]))
    assert previous["eligibility"] == "excluded"
    assert previous["exclusion_reasons"] == ["already_assigned_version"]
    assert second["selected_exercise_version_id"] != first["selected_exercise_version_id"]
    with pytest.raises(psycopg2.Error, match="REPLAY_CONFLICT"):
        assign(db, ctx, lineage=ctx["second_lineage"], observation=ctx["second_observation"], block=ctx["second_block"])


def test_source_observation_cannot_be_attached_to_another_clip_or_block(db, ctx):
    with pytest.raises(psycopg2.Error, match="SOURCE_MISMATCH"):
        assign(db, ctx, observation=ctx["second_observation"])
    with pytest.raises(psycopg2.Error, match="CANDIDATE_LINEAGE_INVALID"):
        assign(db, ctx, block=ctx["second_block"])


def test_dark_checks_reject_true_even_for_table_owner(db, ctx):
    a = assign(db, ctx)
    for column in ("serves_user", "dataset_eligible"):
        with pytest.raises(psycopg2.errors.CheckViolation):
            query(db, f"INSERT INTO exercise_assignments SELECT (jsonb_populate_record(NULL::exercise_assignments,to_jsonb(a) || jsonb_build_object('{column}',true))).* FROM exercise_assignments a WHERE id=%s", (a["id"],))


def test_incomplete_frame_transaction_rolls_back(db, ctx):
    a = assign(db, ctx)
    new_id = str(uuid4())
    db.autocommit = False
    try:
        query(db, "INSERT INTO exercise_selection_feature_snapshots SELECT (jsonb_populate_record(NULL::exercise_selection_feature_snapshots,to_jsonb(s)||jsonb_build_object('id',%s::text))).* FROM exercise_selection_feature_snapshots s WHERE id=%s", (new_id, a["id"]))
        query(db, "INSERT INTO exercise_candidate_sets SELECT (jsonb_populate_record(NULL::exercise_candidate_sets,to_jsonb(f)||jsonb_build_object('id',%s::text,'feature_snapshot_id',%s::text))).* FROM exercise_candidate_sets f WHERE id=%s", (new_id, new_id, a["id"]))
        with pytest.raises(psycopg2.Error, match="FINALIZATION_INCOMPLETE_OR_INVALID"):
            db.commit()
    finally:
        db.rollback()
        db.autocommit = True
    assert not query(db, "SELECT id FROM exercise_candidate_sets WHERE id=%s", (new_id,))
    assert not query(db, "SELECT id FROM exercise_selection_feature_snapshots WHERE id=%s", (new_id,))


def test_old_transaction_snapshot_cannot_reuse_authority(db, ctx):
    db.autocommit = False
    try:
        query(db, "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        with pytest.raises(psycopg2.Error, match="REQUIRES_READ_COMMITTED"):
            assign(db, ctx)
    finally:
        db.rollback()
        db.autocommit = True


def test_authority_revoked_while_waiting_for_assignment_lock_fails(db, ctx):
    from time import monotonic, sleep

    holder = connect()
    holder.autocommit = False
    query(holder, "SELECT pg_advisory_xact_lock(hashtextextended('exercise-profile:' || %s || ':' || %s,0))", (ctx["speaker"], ctx["need"]))

    def work():
        c = connect()
        try:
            query(c, "SET application_name='m33_revocation_waiter'")
            return assign(c, ctx)
        finally:
            c.close()

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(work)
            try:
                deadline = monotonic() + 5
                while not query(db, "SELECT 1 FROM pg_stat_activity WHERE application_name='m33_revocation_waiter' AND wait_event='advisory'"):
                    if monotonic() >= deadline:
                        raise AssertionError("finalizer never waited")
                    sleep(0.01)
                query(db, "INSERT INTO processing_service_blocks(acquisition_principal_id,effective_at) VALUES (%s,clock_timestamp())", (ctx["owner"],))
            finally:
                holder.commit()
            with pytest.raises(psycopg2.Error, match="CURRENT_AUTHORIZATION_REVOKED"):
                future.result(timeout=5)
    finally:
        holder.rollback()
        holder.close()
    assert not query(db, "SELECT * FROM exercise_assignments WHERE idempotency_key=%s", (ctx["key"],))


def test_no_match_packet_for_another_clip_is_rejected(db, ctx):
    ctx["language"] = "zz"
    ctx["catalog"] = catalogue(db, ctx)
    a = assign(db, ctx, lineage=ctx["second_lineage"], observation=ctx["second_observation"], block=ctx["second_block"])
    packet = make_packet(db, ctx)
    reveal_packet(db, ctx, packet)
    with pytest.raises(psycopg2.Error, match="REQUIRES_EXACT_POST_BLIND_REVEAL"):
        rpc(db, "register_exercise_no_match_request_v1", a["id"], packet["id"], ctx["reviewer"], ctx["auth"], str(uuid4()))


def test_superseded_version_retained_but_cannot_win(db, ctx):
    key = "version-test-" + uuid4().hex
    old = add_exercise(db, ctx, key=key)
    new = add_exercise(db, ctx, key=key, version=2, state="retired")
    ctx["catalog"] = catalogue(db, ctx)
    a = assign(db, ctx)
    rows = {r["exercise_version_id"]: r for r in query(db, "SELECT * FROM exercise_candidates WHERE candidate_set_id=%s", (a["id"],))}
    assert "superseded_version" in rows[old["id"]]["exclusion_reasons"]
    assert "inactive_version" in rows[new["id"]]["exclusion_reasons"]


def test_cross_principal_authorization_rejected(db, ctx):
    with pytest.raises(psycopg2.Error, match="CURRENT_AUTHORIZATION"):
        # Correct purpose, wrong acquisition principal.
        query(db, "SELECT require_exercise_assignment_authority_v1(%s,%s)", (ctx["auth"], ctx["reviewer"]))


def test_media_receipt_cannot_claim_available_with_wrong_hash(db, ctx):
    with pytest.raises(psycopg2.Error, match="MEDIA_VERIFICATION_INVALID"):
        rpc(db, "record_exercise_media_availability_v1", ctx["versions"][0]["media_object_id"], "available", "f" * 64,
            "d" * 64, one(db, "SELECT clock_timestamp() AS t")["t"], str(uuid4()))


def test_aggregate_health_is_zero_invariant_and_has_no_identity(db):
    result = rpc(db, "get_mlc3_dark_assignment_health_v1")["get_mlc3_dark_assignment_health_v1"]
    assert result["incomplete_frames"] == 0 and result["invalid_selections"] == 0
    assert not result["serves_user"] and not result["dataset_eligible"]
    assert set(result) == {"serves_user", "dataset_eligible", "assignments", "no_match", "post_blind_requests", "incomplete_frames", "invalid_selections"}


@pytest.mark.parametrize("revoked", [False, True])
def test_same_speaker_foreign_acquisition_never_contributes_history(db, ctx, revoked):
    first = assign(db, ctx)
    other = make_context(db, speaker=ctx["speaker"])
    other.update(need=ctx["need"], language=ctx["language"], catalog=ctx["catalog"])
    other["observation"] = observe(db, other)["id"]
    if revoked:
        query(db, "INSERT INTO processing_service_blocks(acquisition_principal_id,effective_at) VALUES (%s,clock_timestamp())", (ctx["owner"],))
    second = assign(db, other)
    s = one(db, "SELECT snapshot FROM exercise_selection_feature_snapshots WHERE id=%s", (second["id"],))["snapshot"]
    # Even an exclusion ID or count would introduce a foreign purge dependency.
    assert first["id"] not in json.dumps(s)
    assert ctx["observation"] not in json.dumps(s)
    assert s["acquisition_scope"] == "same_principal_only"
    assert s["cross_principal_exclusion_reason"] == "cross_principal_not_authorized"
    assert "cross_principal_exclusion_count" not in s
    assert s["prior_assignment_ids"] == []
    previous = one(db, "SELECT eligibility,exclusion_reasons FROM exercise_candidates WHERE candidate_set_id=%s AND exercise_version_id=%s",
                   (second["id"], first["selected_exercise_version_id"]))
    assert previous == {"eligibility": "eligible", "exclusion_reasons": []}
    rng = one(db, "SELECT * FROM exercise_randomization_assignments WHERE assignment_id=%s", (second["id"],))
    assert one(db, "SELECT to_jsonb(prior_assignment_ids) AS ids FROM exercise_randomization_assignments WHERE assignment_id=%s", (second["id"],))["ids"] == []
    assert rng["repetition_state"] == "first_dark_assignment"


def invalidate_source(db, ctx, kind):
    if kind == "deleted_audio":
        query(db, "UPDATE processing_audio_objects SET deleted_at=clock_timestamp() WHERE id=%s", (ctx["object"],))
    else:
        query(db, "UPDATE snippets SET duration_ms=duration_ms+1 WHERE id=%s", (ctx["snippet"],))


@pytest.mark.parametrize("replay", [False, True])
@pytest.mark.parametrize("kind", ["deleted_audio", "changed_interval"])
def test_source_invalidated_during_assignment_wait_rejects_create_and_replay(db, ctx, replay, kind):
    existing = assign(db, ctx) if replay else None
    before = one(db, "SELECT count(*) AS n FROM exercise_candidate_sets")["n"]
    with pytest.raises(psycopg2.Error, match="SOURCE_MISMATCH"):
        assignment_during_wait(db, ctx, lambda: invalidate_source(db, ctx, kind))
    assert one(db, "SELECT count(*) AS n FROM exercise_candidate_sets")["n"] == before
    rows = query(db, "SELECT id FROM exercise_assignments WHERE idempotency_key=%s", (ctx["key"],))
    assert rows == ([{"id": existing["id"]}] if existing else [])


@pytest.mark.parametrize("kind", ["catalogue", "version_and_catalogue", "source_frame"])
def test_late_committed_catalogue_version_or_source_frame_retries(db, kind):
    x = make_context(db, create_frame=kind != "source_frame")
    writer = connect()
    writer.autocommit = False
    try:
        if kind == "source_frame":
            insert_source_frame(writer, x)
            expected = "FRAME_NOT_COMMITTED_ASOF"
        else:
            if kind == "version_and_catalogue":
                add_exercise(writer, x)
            x["catalog"] = catalogue(writer, x)
            expected = "CATALOG_NOT_COMMITTED_ASOF"
        before = one(db, "SELECT count(*) AS n FROM exercise_candidate_sets")["n"]
        with pytest.raises(psycopg2.Error, match=expected) as error:
            assignment_during_wait(db, x, writer.commit)
        assert error.value.pgcode == "40001"
        assert one(db, "SELECT count(*) AS n FROM exercise_candidate_sets")["n"] == before
        # New invocation has a new visibility boundary; only then may it create.
        assignment = assign(db, x)
        frozen = one(db, "SELECT * FROM exercise_candidate_sets WHERE id=%s", (assignment["id"],))
        rng = one(db, "SELECT * FROM exercise_randomization_assignments WHERE assignment_id=%s", (assignment["id"],))
        assert assign(db, x)["id"] == assignment["id"]
        assert one(db, "SELECT * FROM exercise_candidate_sets WHERE id=%s", (assignment["id"],)) == frozen
        assert one(db, "SELECT * FROM exercise_randomization_assignments WHERE assignment_id=%s", (assignment["id"],)) == rng
    finally:
        writer.rollback()
        writer.close()


@pytest.mark.parametrize("kind", ["revocation", "deleted_audio", "changed_interval", "policy_expiry"])
def test_observation_uniqueness_wait_revalidates_current_authority_and_source(db, ctx, kind):
    prediction = add_prediction(db, ctx)
    holder = connect()
    holder.autocommit = False
    first = rpc(holder, "record_exercise_profile_observation_v1", ctx["lineage"], ctx["need"], prediction, ctx["auth"])
    application = "m33_observation_" + uuid4().hex

    def work():
        c = connect()
        try:
            query(c, "SET application_name=%s", (application,))
            return rpc(c, "record_exercise_profile_observation_v1", ctx["lineage"], ctx["need"], prediction, ctx["auth"])
        finally:
            c.close()

    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(work)
            try:
                wait_for_lock(db, application, "transactionid")
                if kind == "revocation":
                    query(db, "INSERT INTO processing_service_blocks(acquisition_principal_id,effective_at) VALUES (%s,clock_timestamp())", (ctx["owner"],))
                elif kind == "policy_expiry":
                    query(db, "UPDATE processing_policy_versions SET retired_at=clock_timestamp() WHERE id=%s", (ctx["policy"],))
                else:
                    invalidate_source(db, ctx, kind)
            finally:
                holder.commit()
            expected = "CURRENT_AUTHORIZATION_REVOKED" if kind in ("revocation", "policy_expiry") else "OBSERVATION_PROVENANCE_INVALID"
            with pytest.raises(psycopg2.Error, match=expected):
                future.result(timeout=5)
        # No deletion/retroactive alteration: the first, originally valid row remains.
        assert query(db, "SELECT id FROM learning_profile_observations WHERE prediction_id=%s", (prediction,)) == [{"id": first["id"]}]
    finally:
        holder.rollback()
        holder.close()


@pytest.mark.parametrize("replay", [False, True])
def test_policy_retirement_effective_during_lock_wait_rejects(db, ctx, replay):
    if replay:
        assign(db, ctx)
    with pytest.raises(psycopg2.Error, match="CURRENT_AUTHORIZATION_REVOKED"):
        assignment_during_wait(db, ctx, lambda: query(db,
            "UPDATE processing_policy_versions SET retired_at=clock_timestamp() WHERE id=%s", (ctx["policy"],)))


@pytest.mark.parametrize("operation", ["assignment_create", "assignment_replay", "observation_create", "observation_replay"])
def test_long_running_transaction_does_not_freeze_policy_authority(db, ctx, operation):
    prediction = add_prediction(db, ctx)
    if operation == "assignment_replay":
        assign(db, ctx)
    elif operation == "observation_replay":
        rpc(db, "record_exercise_profile_observation_v1", ctx["lineage"], ctx["need"], prediction, ctx["auth"])
    worker = connect()
    worker.autocommit = False
    try:
        query(worker, "SELECT now()")  # pin the old transaction time
        query(db, "UPDATE processing_policy_versions SET retired_at=clock_timestamp() WHERE id=%s", (ctx["policy"],))
        with pytest.raises(psycopg2.Error, match="CURRENT_AUTHORIZATION_REVOKED"):
            if operation.startswith("assignment"):
                assign(worker, ctx)
            else:
                rpc(worker, "record_exercise_profile_observation_v1", ctx["lineage"], ctx["need"], prediction, ctx["auth"])
    finally:
        worker.rollback()
        worker.close()


def test_principal_purge_inventory_covers_all_permitted_dark_dependencies(db, ctx, monkeypatch):
    from services.data_purge import DataPurgeOrchestrator, SubjectGraph
    from services.data_purge_registry import DEPENDENCIES

    first = assign(db, ctx)
    second = assign(db, ctx, lineage=ctx["second_lineage"], observation=ctx["second_observation"], block=ctx["second_block"], key=str(uuid4()))
    foreign = make_context(db, speaker=ctx["speaker"])
    assign(db, foreign)
    personal = {"learning_profile_observations", "exercise_selection_feature_snapshots", "exercise_candidate_sets",
                "exercise_candidates", "exercise_assignments", "exercise_randomization_assignments", "exercise_requests"}
    deps = [d for d in DEPENDENCIES if d.relation in personal or d.relation == "learning_profiles"]
    orchestrator = DataPurgeOrchestrator(type("Database", (), {"client": object()})())

    def rows(relation, columns, *, selector, values, existing_relations):
        assert relation in {d.relation for d in deps}
        assert selector in ("speaker_id", "acquisition_principal_id") and columns == selector
        return query(db, f"SELECT {columns} FROM {relation} WHERE {selector}::text=ANY(%s)", (list(values),))

    monkeypatch.setattr(orchestrator, "_rows", rows)
    graph = SubjectGraph(principal_ids=(ctx["owner"],), speaker_ids=(ctx["speaker"],))
    targets = {d.relation: orchestrator._dependency_target(d, graph, frozenset(personal | {"learning_profiles"})) for d in deps}
    for table in personal - {"exercise_requests"}:
        target = targets[table]
        assert target.target_kind == "unknown"
        assert target.metadata["reason_code"] == "EXPLICIT_RESOLVER_REQUIRED"
        assert target.initial_match_count == one(db, f"SELECT count(*) AS n FROM {table} WHERE acquisition_principal_id=%s", (ctx["owner"],))["n"]
    # Shared identity is a separate already-inventoried, fail-closed dependency.
    assert targets["learning_profiles"].target_kind == "unknown"
    assert targets["learning_profiles"].initial_match_count == 1
    snapshot = one(db, "SELECT snapshot FROM exercise_selection_feature_snapshots WHERE id=%s", (second["id"],))["snapshot"]
    assert snapshot["prior_assignment_ids"] == [first["id"]]
    for ref in snapshot["profile_observations"] + snapshot["excluded_observations"]:
        assert one(db, "SELECT acquisition_principal_id FROM learning_profile_observations WHERE id=%s", (ref["id"],))["acquisition_principal_id"] == ctx["owner"]
