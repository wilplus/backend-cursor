"""
STORY    As a speaker, I want no exercise assigned on evidence the machine did
         not really have, and none after I withdraw permission, so that practice
         is never invented or done without my permission.
OUTCOME
  O1  Unclear or unreliable audio, or missing or out-of-range measurements,
      give "no match" with the named reason, and that "no match" cannot be
      turned into a request for a new exercise.
  O2  After my permission is withdrawn, no new assignment or observation can
      be made.
PROVES   O1 -> test_no_invented_evidence (one case per reason)
         O2 -> test_revocation_blocks_creation_and_replay
WHY      Rehearsal database only (migrations 0313, 0314); no provider calls.
"""
from __future__ import annotations

import itertools
import os
from time import monotonic, sleep
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extras import Json, RealDictCursor

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
    # pg_stat_activity is read once per transaction and then cached, and `db`
    # is usually inside one. Without clearing that snapshot, a first poll
    # that lands a moment before the worker starts waiting sees the same stale
    # picture on every later poll, times out, and — inside a caller's
    # ThreadPoolExecutor — turns into a hang rather than a failure.
    while True:
        query(db, "SELECT pg_stat_clear_snapshot()")
        if query(db, "SELECT 1 FROM pg_stat_activity WHERE application_name=%s AND wait_event=%s",
                 (application, event)):
            return
        if monotonic() >= deadline:
            raise AssertionError(f"worker never reached {event} wait")
        sleep(0.01)


@pytest.mark.parametrize("quality,features,reason", [("audio_unclear", {"pace": 4}, "audio_unclear"), ("unreliable", {"pace": 4}, "audio_unreliable"), ("usable", {}, "missing_need_features"), ("usable", {"pace": 20}, "need_outside_contract")])
def test_no_invented_evidence(db, ctx, quality, features, reason):
    ctx["observation"] = observe(db, ctx, quality=quality, features=features)["id"]
    a = assign(db, ctx)
    assert a["outcome"] == "dark_no_match"
    rows = query(db, "SELECT exclusion_reasons FROM exercise_candidates WHERE candidate_set_id=%s", (a["id"],))
    assert rows and all(reason in r["exclusion_reasons"] for r in rows)
    with pytest.raises(psycopg2.Error, match="EXERCISE_REQUEST_SOURCE_NOT_ACTIONABLE"):
        rpc(db, "register_exercise_no_match_request_v1", a["id"], str(uuid4()), ctx["reviewer"], ctx["auth"], str(uuid4()))


def test_revocation_blocks_creation_and_replay(db, ctx):
    assign(db, ctx)
    query(db, "INSERT INTO processing_service_blocks(acquisition_principal_id,effective_at) VALUES (%s,clock_timestamp())", (ctx["owner"],))
    with pytest.raises(psycopg2.Error, match="CURRENT_AUTHORIZATION_REVOKED"):
        assign(db, ctx)
    with pytest.raises(psycopg2.Error, match="CURRENT_AUTHORIZATION_REVOKED"):
        observe(db, ctx)


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
