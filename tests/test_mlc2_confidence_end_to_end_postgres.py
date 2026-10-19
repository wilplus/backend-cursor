"""
STORY    As the founder, I want a Take promoted with a training yes to flow to
         one finalized confidence frame with exact spans, one selected
         candidate, a replay that changes nothing and a blind packet with no
         hints, so that the training corpus is consented, exact and blind.
OUTCOME
  O1  One Take, one producer receipt and one outbox event per promotion.
  O2  The worker's frame is accepted: one candidate per snippet, each span
      the snippet's exact offsets on the Take's own audio object, one
      prediction per eligible clip, exactly one selected candidate.
  O3  A replay of the same event changes nothing and the health check
      reports no processed event without its frame.
  O4  The coach's blind packet carries the clip and the five answers and no
      transcript, prediction, score, rank or selection hint (Never-2: no
      coach sees the machine's guess before answering).
  O5  An owner without a training yes is refused and the promotion rolls back.
PROVES   O1 -> test_the_take_and_its_receipt_and_event_exist_once
         O2 -> test_the_frame_holds_every_snippet_at_its_exact_span
         O3 -> test_a_replay_changes_nothing_and_health_is_safe
         O4 -> test_the_coach_packet_is_the_clip_and_the_answers_only
         O5 -> test_an_owner_without_a_grant_is_refused_and_the_take_promotion_rolls_back
WHY      G-6 part 2; runs in one rolled-back transaction on a database whose
         name starts with ``willab_confident_moment_`` (rehearsal tier only).
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from types import SimpleNamespace

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

SHA = {c: c * 64 for c in "0123456789abcdef"}
BUCKET = "mlc2-rehearsal"
OBJECT_KEY = "confidence/g6-end-to-end-source.webm"
OBJECT_SHA = SHA["8"]
OBJECT_BYTES = 4096
MANIFEST = {
    "source_schema_version": "confidence-source-audio-v1",
    "audio": {
        "object_store": "cloudflare_r2",
        "bucket": BUCKET,
        "object_key": OBJECT_KEY,
        "sha256": OBJECT_SHA,
        "byte_size": OBJECT_BYTES,
        "content_type": "audio/webm",
    },
}


def _stamp(score: float) -> dict:
    from services.voice_confidence import VERSION

    return {"voice_confidence": {
        "score": score, "band": "x", "baseline": "user", "cues": 6,
        "version": VERSION,
    }}


class _Rpc:
    """`client.rpc(name, params).execute()` over one psycopg2 transaction."""

    def __init__(self, cur, name, params):
        self.cur, self.name, self.params = cur, name, params

    def execute(self):
        keys = list(self.params)
        placeholders = ", ".join(f"{k} := %s" for k in keys)
        values = [
            psycopg2.extras.Json(v) if isinstance(v, (dict, list)) else v
            for v in (self.params[k] for k in keys)
        ]
        self.cur.execute(f"SELECT * FROM public.{self.name}({placeholders})", values)
        rows = [dict(r) for r in self.cur.fetchall()]
        if len(rows) == 1 and list(rows[0]) == [self.name]:
            return SimpleNamespace(data=rows[0][self.name])
        return SimpleNamespace(data=rows)


class _Client:
    def __init__(self, cur):
        self.cur = cur

    def rpc(self, name, params):
        return _Rpc(self.cur, name, params)


@pytest.fixture(scope="module")
def conn():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    if not parsed.get("host", "").startswith(("/tmp/willab-", "/private/tmp/willab-")):
        raise RuntimeError("Refusing a database outside the rehearsal socket")
    connection = psycopg2.connect(DSN)
    connection.autocommit = False
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def _one(cur, sql, params=()):
    cur.execute(sql, params)
    row = cur.fetchone()
    return dict(row) if row else None


def _count(cur, sql, params=()):
    cur.execute(sql, params)
    return list(cur.fetchone().values())[0]


def _training_yes(cur, owner):
    """The owner's training yes (0373/0412), the one consent authority the
    chain reads since 0430. Reuses the active training-only policy another
    suite left in the lane, or registers one inside this rolled-back
    transaction (the database allows one at a time); the receipt is for the
    processing version that policy requires (C1)."""
    live = _one(cur, """
        SELECT policy.version, policy.requires_processing_policy_version AS processing,
               approval.approved_copy_sha256 AS sha, approval.terms_version AS terms,
               approval.privacy_policy_version AS privacy
          FROM public.ml_consent_policies policy
          JOIN public.ml_product_legal_approvals approval
            ON approval.id = policy.product_legal_approval_id
         WHERE policy.grant_scope = 'training_only' AND policy.active_from <= now()
           AND (policy.retired_at IS NULL OR policy.retired_at > now())
         ORDER BY policy.active_from DESC LIMIT 1""")
    if live is None:
        processing = (_one(cur, "SELECT version FROM public.processing_policy_versions "
                                "ORDER BY created_at LIMIT 1") or {}).get("version")
        if not processing:
            processing = f"phase1-g6-{uuid.uuid4()}"
            digest = hashlib.sha256(b"g6").hexdigest()
            cur.execute(
                "INSERT INTO public.processing_policy_versions (version, status, terms_version, "
                "terms_copy, terms_copy_sha256, privacy_version, privacy_copy, privacy_copy_sha256, "
                "ai_notice_version, ai_notice_copy, ai_notice_copy_sha256, agreement_copy, "
                "agreement_copy_sha256, allowed_countries, created_by) VALUES (%s, 'draft', 't', "
                "'terms', %s, 'p', 'privacy', %s, 'a', 'notice', %s, 'agree', %s, ARRAY['pl'], 'g6')",
                (processing, digest, digest, digest, digest))
        copy = "G-6 rehearsal training sentence."
        sha = hashlib.sha256(copy.encode()).hexdigest()
        cur.execute(
            "SELECT public.configure_mlc2_training_consent_policy_v1('g6-training-approval', %s, %s, "
            "'g6-training-only-v1', 'terms-t', 'privacy-t', 'isolated-test', now(), ARRAY['PL'], "
            "'legal/g6-training.pdf', %s, %s, now() - interval '1 minute')",
            (sha, copy, SHA["2"], processing))
        live = {"version": "g6-training-only-v1", "processing": processing, "sha": sha,
                "terms": "terms-t", "privacy": "privacy-t"}
    cur.execute(
        "INSERT INTO public.processing_authorization_receipts (acquisition_principal_id, policy_id, "
        "idempotency_key, explicit_action, age_18_attested, country_of_residence, locale, "
        "client_version, accepted_at, evidence_sha256) SELECT %s, id, %s, 'agree_and_continue', "
        "true, 'PL', 'en-GB', 'g6', now(), %s FROM public.processing_policy_versions WHERE version = %s",
        (owner, f"g6-receipt-{uuid.uuid4()}", SHA["a"], live["processing"]))
    cur.execute(
        "SELECT * FROM public.record_mlc2_training_consent_grant_v2(%s, %s, 'PL', %s, %s, "
        "'settings/training', 'rehearsal-client', %s::jsonb, now() - interval '1 second', %s)",
        (owner, live["version"], live["terms"], live["privacy"],
         json.dumps({"accepted": True, "control": "training_toggle", "copy_sha256": live["sha"]}),
         f"g6-training-yes-{uuid.uuid4()}"))
    return str(cur.fetchone()["id"])


@pytest.fixture(scope="module")
def chain(conn):
    """Seed, promote, claim, build, finalize. Everything rolls back after
    the module, so the shared lane is left exactly as it was."""
    from services.mlc2_confidence import Mlc2ConfidenceStore
    from services.mlc2_confidence_frame_factory import foundation_frame_factory
    from services.mlc2_confidence_producer import (
        DarkConfidenceWorker,
        Mlc2ConfidenceProducerStore,
    )

    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    owner, reviewer = str(uuid.uuid4()), str(uuid.uuid4())
    project, attempt, recording = (str(uuid.uuid4()) for _ in range(3))
    tag = uuid.uuid4().hex[:8]

    cur.execute("INSERT INTO public.owner_principals (id, guest_secret_hash) VALUES (%s, %s), (%s, %s)",
                (owner, f"g6-owner-{tag}", reviewer, f"g6-reviewer-{tag}"))
    cur.execute("INSERT INTO public.projects (id, owner_principal_id, display_name) VALUES (%s, %s, %s)",
                (project, owner, "G-6 end to end"))
    # On the released lane an attempt IS its v2 session (recording_attempts.id
    # → v2_sessions.id) and snippets point at both the session and the recording.
    cur.execute("INSERT INTO public.recordings (id) VALUES (%s)", (recording,))
    cur.execute(
        "INSERT INTO public.v2_sessions (id, user_id, owner_principal_id, project_id, arc_id, "
        "take_index, analysis_state, recording_kind, recording_1_id) "
        "VALUES (%s, %s, %s, %s, %s, 1, 'ready', 'spoken', %s)",
        (attempt, str(uuid.uuid4()), owner, project, f"g6-arc-{tag}", recording),
    )
    cur.execute(
        "INSERT INTO public.recording_attempts (id, owner_principal_id, project_id, "
        "upload_idempotency_key, recording_id, storage_bucket, storage_key, recording_kind, status) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, 'spoken', 'processing')",
        (attempt, owner, project, f"g6-upload-{tag}", recording, BUCKET, OBJECT_KEY),
    )

    # 0430 (N48.5 Q27 A): the chain is admitted by the training yes alone.
    # The owner's speaker is bound, the owner holds a processing receipt for
    # the version the training policy requires (C1) and says yes through the
    # one training writer; the pre-made snapshot is the training snapshot.
    cur.execute(
        "SELECT public.register_ml_speaker_principal_v1(%s, %s, 'speaker-resolution-v1', 'initial', %s, "
        "'rehearsal', 'speaker-sha256-80-10-10-v1')", (owner, SHA["3"], SHA["4"]))
    _training_yes(cur, owner)
    cur.execute("SELECT public.create_mlc2_training_consent_snapshot_v1(%s, %s, NULL, NULL)",
                (owner, attempt))
    cur.execute(
        "SELECT public.promote_recording_attempt_with_mlc2_confidence_v1(%s, %s, NULL, 1, %s, %s, %s, %s)",
        (attempt, SHA["5"], SHA["6"], SHA["7"], f"g6-promotion-{tag}", psycopg2.extras.Json(MANIFEST)))

    # The Take's snippets: three rateable clips, one too short, one never stamped.
    snippets = [
        (str(uuid.uuid4()), 0, 4000, _stamp(0.8)),
        (str(uuid.uuid4()), 5000, 4000, _stamp(0.45)),
        (str(uuid.uuid4()), 10000, 4000, _stamp(-0.7)),
        (str(uuid.uuid4()), 15000, 500, _stamp(0.9)),
        (str(uuid.uuid4()), 20000, 4000, None),
    ]
    for sid, start, duration, metrics in snippets:
        cur.execute(
            "INSERT INTO public.snippets (id, session_id, recording_id, start_offset_ms, duration_ms, metrics) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (sid, attempt, recording, start, duration,
             psycopg2.extras.Json(metrics) if metrics is not None else None))

    def get_snippets_by_session(take_id):
        cur.execute("SELECT id, session_id, recording_id, start_offset_ms, duration_ms, metrics "
                    "FROM public.snippets WHERE session_id = %s ORDER BY start_offset_ms", (take_id,))
        return [dict(r) for r in cur.fetchall()]

    client = _Client(cur)
    producer_store = Mlc2ConfidenceProducerStore(client)
    worker = DarkConfidenceWorker(
        producer_store=producer_store,
        frame_store=Mlc2ConfidenceStore(client),
        frame_factory=foundation_frame_factory(
            SimpleNamespace(get_snippets_by_session=get_snippets_by_session)),
    )
    worker_id = f"g6-worker-{tag}"
    claimed = producer_store.claim(worker_id=worker_id, limit=5, lease_seconds=60)
    ours = [row for row in claimed if str(row.get("aggregate_id")) == attempt]
    assert len(ours) == 1, claimed
    result = worker.process_claimed(ours[0], worker_id=worker_id)
    return {
        "cur": cur, "owner": owner, "reviewer": reviewer, "project": project,
        "attempt": attempt, "recording": recording, "tag": tag,
        "snippets": snippets, "claimed": ours[0], "worker": worker,
        "worker_id": worker_id, "result": result,
        "candidate_set_id": (result.get("candidate_set_id") or result.get("candidate_set", {}).get("id")),
    }


class TestThePromotionNeedsATrainingYes:
    """0430: an owner with no training yes is refused, and the refusal rolls
    the Take promotion back."""

    def _attempt(self, chain, owner, project, label):
        cur = chain["cur"]
        recording, attempt = str(uuid.uuid4()), str(uuid.uuid4())
        cur.execute("INSERT INTO public.recordings (id) VALUES (%s)", (recording,))
        cur.execute(
            "INSERT INTO public.v2_sessions (id, user_id, owner_principal_id, project_id, arc_id, "
            "take_index, analysis_state, recording_kind, recording_1_id) "
            "VALUES (%s, %s, %s, %s, %s, 2, 'ready', 'spoken', %s)",
            (attempt, str(uuid.uuid4()), owner, project, f"g6-arc-{chain['tag']}-{label}", recording),
        )
        cur.execute(
            "INSERT INTO public.recording_attempts (id, owner_principal_id, project_id, "
            "upload_idempotency_key, recording_id, storage_bucket, storage_key, recording_kind, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'spoken', 'processing')",
            (attempt, owner, project, f"g6-upload-{chain['tag']}-{label}", recording, BUCKET, OBJECT_KEY),
        )
        return attempt


    def test_an_owner_without_a_grant_is_refused_and_the_take_promotion_rolls_back(self, chain):
        cur = chain["cur"]
        stranger, project = str(uuid.uuid4()), str(uuid.uuid4())
        cur.execute("INSERT INTO public.owner_principals (id, guest_secret_hash) VALUES (%s, %s)",
                    (stranger, f"g6-stranger-{chain['tag']}"))
        cur.execute("INSERT INTO public.projects (id, owner_principal_id, display_name) VALUES (%s, %s, %s)",
                    (project, stranger, "G-6 stranger"))
        cur.execute(
            "SELECT public.register_ml_speaker_principal_v1(%s, %s, 'speaker-resolution-v1', 'initial', %s, "
            "'rehearsal', 'speaker-sha256-80-10-10-v1')", (stranger, SHA["9"], SHA["a"]))
        attempt = self._attempt(chain, stranger, project, "stranger")
        cur.execute("SAVEPOINT stranger_promotion")
        with pytest.raises(psycopg2.Error) as refusal:
            cur.execute(
                "SELECT public.promote_recording_attempt_with_mlc2_confidence_v1(%s, %s, NULL, 1, %s, %s, %s, %s)",
                (attempt, SHA["5"], SHA["6"], SHA["7"], f"g6-promotion-{chain['tag']}-stranger",
                 psycopg2.extras.Json(MANIFEST)))
        assert "no active training yes" in str(refusal.value)
        cur.execute("ROLLBACK TO SAVEPOINT stranger_promotion")
        assert _one(cur, "SELECT 1 AS present FROM public.takes WHERE id = %s", (attempt,)) is None
        assert _one(cur, "SELECT 1 AS present FROM public.ml_consent_snapshots WHERE recording_attempt_id = %s",
                    (attempt,)) is None


class TestThePromotionReachesTheOutbox:
    def test_the_take_and_its_receipt_and_event_exist_once(self, chain):
        cur = chain["cur"]
        assert _count(cur, "SELECT count(*) FROM public.takes WHERE id = %s", (chain["attempt"],)) == 1
        assert _count(cur, "SELECT count(*) FROM public.ml_confidence_producer_receipts WHERE take_id = %s",
                      (chain["attempt"],)) == 1
        assert _count(cur, "SELECT count(*) FROM public.ml_outbox_events WHERE aggregate_id = %s",
                      (chain["attempt"],)) == 1


def _frame(cur, candidate_set_id):
    cur.execute(
        "SELECT c.clip_id::text AS clip_id, c.eligible, c.selected, c.exclusion_reason_code, "
        "c.machine_prediction_id, c.id::text AS candidate_id, e.coordinates, "
        "o.bucket, o.object_key, o.sha256, o.byte_size "
        "FROM public.ml_candidates c "
        "JOIN public.ml_evidence_spans e ON e.id = c.evidence_span_id "
        "JOIN public.ml_object_artifacts o ON o.id = e.object_artifact_id "
        "WHERE c.candidate_set_id = %s ORDER BY (e.coordinates ->> 'start_ms')::int",
        (candidate_set_id,))
    return [dict(r) for r in cur.fetchall()]


class TestTheWorkerFinalizesOneFrame:
    def test_the_frame_holds_every_snippet_at_its_exact_span(self, chain):
        result = chain["result"]
        assert result["idempotent_replay"] is False
        assert (result["pool_size"], result["eligible_count"],
                result["excluded_count"], result["selected_count"]) == (5, 3, 2, 1)
        rows = _frame(chain["cur"], chain["candidate_set_id"])
        assert [r["clip_id"] for r in rows] == [s[0] for s in chain["snippets"]]
        for row, (_sid, start, duration, _m) in zip(rows, chain["snippets"]):
            assert row["coordinates"] == {"start_ms": start, "end_ms": start + duration}
            assert (row["bucket"], row["object_key"], row["sha256"], row["byte_size"]) == (
                BUCKET, OBJECT_KEY, OBJECT_SHA, OBJECT_BYTES)
        assert [r["exclusion_reason_code"] for r in rows] == [
            None, None, None, "audio_too_short", "no_confidence_read"]
        assert [r["machine_prediction_id"] is not None for r in rows] == [
            True, True, True, False, False]
        assert sum(r["selected"] for r in rows) == 1
        assert all(r["eligible"] for r in rows if r["selected"])

    def test_a_replay_changes_nothing_and_health_is_safe(self, chain):
        cur = chain["cur"]
        before = _count(cur, "SELECT count(*) FROM public.ml_candidates WHERE candidate_set_id = %s",
                        (chain["candidate_set_id"],))
        replay = chain["worker"].process_claimed(chain["claimed"], worker_id=chain["worker_id"])
        assert replay["idempotent_replay"] is True
        assert str(replay["candidate_set_id"]) == str(chain["candidate_set_id"])
        assert replay["immutable_pool_sha256"] == chain["result"]["immutable_pool_sha256"]
        assert _count(cur, "SELECT count(*) FROM public.ml_candidates WHERE candidate_set_id = %s",
                      (chain["candidate_set_id"],)) == before == 5
        health = _Client(cur).rpc("get_mlc2_confidence_slice4_health_v1", {}).execute().data
        assert health["processed_without_frame_count"] == 0
        assert health["receipt_without_outbox_count"] == 0


class TestTheCoachPacketIsBlind:
    def test_the_coach_packet_is_the_clip_and_the_answers_only(self, chain):
        cur = chain["cur"]
        selected = next(r for r in _frame(cur, chain["candidate_set_id"]) if r["selected"])
        out = _one(cur, "SELECT public.create_mlc2_confidence_blind_packet_v1(%s, %s, 'coach', "
                        "'conf-q-v2', 'blind-confidence-v1', 'canary', %s) AS out",
                   (selected["candidate_id"], chain["reviewer"], f"g6-packet-{chain['tag']}"))["out"]
        packet = out["visible_packet"]
        # What the coach gets: the exact clip and the five answers.
        assert packet["clip"]["clip_id"] == selected["clip_id"]
        assert (packet["clip"]["start_ms"], packet["clip"]["end_ms"]) == (
            selected["coordinates"]["start_ms"], selected["coordinates"]["end_ms"])
        assert packet["taxonomy"]["choices"] == [
            "rating_yes", "rating_in_between", "rating_no",
            "rating_not_sure", "rating_audio_unclear"]
        # What the coach must not get: the machine's guess or any hint of it.
        flat = json.dumps(packet)
        for hint in ("transcript", "text", "prediction", "predicted", "score", "rank",
                     "selected", "selection", "sampling", "rng", "probability",
                     "confident", "label", "judgment"):
            assert hint not in flat, hint
        assert set(packet) == {"packet_version", "clip", "taxonomy"}
        assert set(packet["clip"]) == {"clip_id", "audio_object_id", "audio_sha256",
                                       "start_ms", "end_ms"}
