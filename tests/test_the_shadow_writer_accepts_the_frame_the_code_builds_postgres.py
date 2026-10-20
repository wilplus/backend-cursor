"""
STORY    As a developer, I want the database to store the feedback frame the
         code really builds, so that every Take's shadow record is kept
         instead of silently refused.
OUTCOME
  O1  The frame build_shadow_frame makes is stored byte for byte and read
      back; a replay is still "stored".
  O2  The same frame with an older schema label or another detector
      version is refused.
  O3  Re-applying the writer's migrations (twice) leaves it accepting the
      code's frame.
  O4  The writer is SECURITY DEFINER with search_path = public; only
      service_role may execute it.
PROVES   O1 -> test_the_frame_the_code_builds_is_stored_and_read_back
         O2 -> test_an_older_label_or_detector_is_refused
         O3 -> test_re_applying_the_writer_keeps_it_accepting_the_frame
         O4 -> test_only_the_service_key_may_call_the_writer
WHY      0431/0441, ledger N20: after #893 every shadow write was refused and
         only logged. Released lane; every write is rolled back. Other suites
         import _migration_body, _seed_take and _write from here.
"""
from __future__ import annotations

import os
import pathlib
import uuid

import psycopg2
import psycopg2.errors
import psycopg2.extras
import pytest

from services.take_feedback_policy_v3 import (
    FRAME_SCHEMA_VERSION,
    POLICY_VERSION,
    build_shadow_frame,
)

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
# The writer as the code needs it today: 0431, then 0441 (V4 B1.1, the pick
# log), applied in manifest order.
MIGRATIONS = (
    ROOT / "migrations" / "the_shadow_writer_accepts_the_frame_the_code_builds.sql",
    ROOT / "migrations" / "the_shadow_writer_keeps_the_pick_log.sql",
)
CALL = ("SELECT public.record_take_feedback_policy_v3_shadow_v3("
        "%s, %s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s)")


@pytest.fixture
def cur():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c:
            yield c
    finally:
        conn.rollback()
        conn.close()


def _migration_body() -> str:
    """0431 then 0441 without their own BEGIN/COMMIT, to run inside a
    test's transaction."""
    return "\n".join(
        line for path in MIGRATIONS for line in path.read_text().splitlines()
        if line.strip() not in ("BEGIN;", "COMMIT;"))


def _piece(take_id, recording_id, snippet_id, index, slide, words, score):
    text = " ".join(f"word{index}x{n}" for n in range(words))
    return {
        "snippet_id": snippet_id,
        "take_session_id": take_id,
        "slide_index": slide,
        "start": index * 1000,
        "end": index * 1000 + len(text),
        "text": text,
        "recording_id": recording_id,
        "start_offset_ms": index * 5000,
        "duration_ms": 5000,
        "score": score,
    }


def _seed_take(cur):
    """One spoken Take with five snippets on two slides, as production
    stores them; returns what `_v3_shadow` passes to the writer."""
    arc_id = f"n20-arc-{uuid.uuid4()}"
    user_id = str(uuid.uuid4())
    principal = str(uuid.uuid4())
    recording = str(uuid.uuid4())
    take = str(uuid.uuid4())
    cur.execute("INSERT INTO public.owner_principals (id, user_id) "
                "VALUES (%s, %s)", (principal, user_id))
    cur.execute("INSERT INTO public.recordings (id) VALUES (%s)", (recording,))
    cur.execute(
        "INSERT INTO public.v2_sessions (id, user_id, owner_principal_id, "
        "arc_id, take_index, recording_kind, recording_1_id) "
        "VALUES (%s, %s, %s, %s, 2, 'spoken', %s)",
        (take, user_id, principal, arc_id, recording))
    shape = [(0, 0, 25, -0.4), (1, 0, 25, 0.2), (2, 0, 25, 0.7),
             (3, 1, 35, -0.5), (4, 1, 35, -0.2)]
    pieces, snippets = [], []
    for index, slide, words, score in shape:
        snippet_id = str(uuid.uuid4())
        piece = _piece(take, recording, snippet_id, index, slide, words, score)
        metrics = {"voice_confidence": {
            "version": "voice-confidence-universal-v3", "score": score}}
        cur.execute(
            "INSERT INTO public.snippets (id, session_id, recording_id, "
            "start_offset_ms, duration_ms, metrics) VALUES (%s, %s, %s, %s, %s, %s)",
            (snippet_id, take, recording, piece["start_offset_ms"],
             piece["duration_ms"], psycopg2.extras.Json(metrics)))
        pieces.append(piece)
        snippets.append({
            "id": snippet_id, "session_id": take, "recording_id": recording,
            "start_offset_ms": piece["start_offset_ms"],
            "duration_ms": piece["duration_ms"], "metrics": metrics,
        })
    feedback = [
        {
            "id": "weak-rewrite", "feedback_family": "rewrite_clarity",
            "snippet_id": pieces[0]["snippet_id"], "take_session_id": take,
            "span": {"start": 0, "end": 20}, "quote": "a", "proposed_text": "b",
            "rule_version": "rewrite-generator-v1",
            "_manager_evidence": {"specificity": 1, "fallback": True},
        },
        {
            "id": "best-praise", "feedback_family": "great_formulation",
            "snippet_id": pieces[2]["snippet_id"], "take_session_id": take,
            "span": {"start": 100, "end": 130},
            "prompt_version": "praise-prompt-v1",
            "_manager_evidence": {"specificity": 4, "fallback": False},
        },
    ]
    frame = build_shadow_frame(
        take_document={"take_session_id": take, "text": "x" * 5000,
                       "pieces": pieces},
        snippets=snippets,
        suggestions={pieces[2]["snippet_id"]: {
            "trigger": "confident", "cue_keys": ["full_volume"]}},
        feedback_candidates=feedback,
        take_index=2,
        expected_recording_id=recording,
        served_text="x" * 5000,
    )
    assert frame is not None
    assert frame["frame_schema_version"] == FRAME_SCHEMA_VERSION
    return {
        "arc_id": arc_id, "take": take, "recording": recording,
        "principal": principal, "user_id": user_id, "frame": frame,
    }


def _write(cur, seed, frame):
    cur.execute(CALL, (
        seed["arc_id"], seed["take"], seed["recording"], seed["principal"],
        seed["user_id"], 2, POLICY_VERSION, psycopg2.extras.Json(frame),
        frame["frame_hash"]))
    return cur.fetchone()["record_take_feedback_policy_v3_shadow_v3"]


def test_the_frame_the_code_builds_is_stored_and_read_back(cur):
    seed = _seed_take(cur)
    outcome = _write(cur, seed, seed["frame"])
    assert outcome["outcome"] == "stored", outcome
    assert outcome["frame_hash"] == seed["frame"]["frame_hash"]
    cur.execute("SELECT frame, frame_hash, policy_version FROM "
                "public.take_feedback_policy_v3_shadow_frames "
                "WHERE take_session_id = %s", (seed["take"],))
    rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["policy_version"] == POLICY_VERSION
    assert rows[0]["frame_hash"] == seed["frame"]["frame_hash"]
    assert rows[0]["frame"]["frame_schema_version"] == FRAME_SCHEMA_VERSION
    assert rows[0]["frame"] == seed["frame"]
    # The replay the writer is idempotent for.
    assert _write(cur, seed, seed["frame"])["outcome"] == "stored"


def test_an_older_label_or_detector_is_refused(cur):
    seed = _seed_take(cur)
    frame = seed["frame"]
    older = [{**frame, "frame_schema_version": "take-feedback-policy-v3-frame-v3"},
             {**frame, "frame_schema_version": "take-feedback-policy-v3-frame-v4"},
             {**frame, "implementation_versions": {
                 **frame["implementation_versions"],
                 "confidence_detector_version": "voice-confidence-universal-v2"}}]
    for relabelled in older:
        cur.execute("SAVEPOINT refused")
        with pytest.raises(psycopg2.Error) as refused:
            _write(cur, seed, relabelled)
        cur.execute("ROLLBACK TO SAVEPOINT refused")
        assert "invalid universal-v3 dark frame" in str(refused.value)
    assert _write(cur, seed, frame)["outcome"] == "stored"


def test_re_applying_the_writer_keeps_it_accepting_the_frame(cur):
    cur.execute(_migration_body())
    cur.execute(_migration_body())
    seed = _seed_take(cur)
    assert _write(cur, seed, seed["frame"])["outcome"] == "stored"


def test_only_the_service_key_may_call_the_writer(cur):
    signature = ("public.record_take_feedback_policy_v3_shadow_v3("
                 "text, uuid, uuid, uuid, uuid, integer, text, jsonb, text)")
    cur.execute("SELECT prosecdef, proconfig FROM pg_proc WHERE oid = %s::regprocedure",
                (signature,))
    row = cur.fetchone()
    assert row["prosecdef"] is True
    assert row["proconfig"] == ["search_path=public"]
    for role, allowed in (("service_role", True), ("anon", False),
                          ("authenticated", False)):
        cur.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE') AS ok",
                    (role, signature))
        assert cur.fetchone()["ok"] is allowed, role
