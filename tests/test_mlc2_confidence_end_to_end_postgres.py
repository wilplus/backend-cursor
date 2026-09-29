"""The blind-label chain, end to end, on a disposable database (G-6 part 2).

What is rehearsed, in one rolled-back transaction on the released lane: a
Take promoted through the atomic producer RPC lands on the confidence outbox;
the worker claims it, the foundation frame factory builds the frame from the
Take's snippet rows, and ``finalize_mlc2_confidence_frame_v1`` accepts it —
one candidate set, one evidence span per snippet with the snippet's exact
offsets on the Take's own R2 object, one machine prediction per eligible
clip, exactly one selected candidate; a replay changes nothing; a blind
packet built from the selected candidate carries no transcript, prediction,
score, rank or selection hint; and the slice-4 health function reports a
safe state throughout.

What is NOT rehearsed here, and why: the D5 coach batch joins the stored
span to an exercise audio lineage through ``exercise_evidence_matches_audio_v1``,
whose lineage row needs a Phase-1 authorization snapshot (policy, receipt,
purpose), a learning profile and an exercise-service authority check. That
join is not executed. What is asserted is narrower: the stored span's
coordinates equal the snippet's offsets, and the stored object's store,
bucket, key, sha256 and byte size equal the source manifest. The join
additionally requires those to equal the Phase-1 registered
``processing_audio_objects`` row and the lineage's own hash, which this
suite does not seed. Rehearsing the join is a follow-up that seeds the
Phase-1 chain.

Nothing here changes any application flag: the RPCs are invoked directly,
exactly as ``tests/integration/mlc2_confidence_slice4_rehearsal.sql`` does,
and everything rolls back. The database name must start with
``willab_confident_moment_``.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
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
LEAK_KEYS = (
    "transcript", "text", "score", "rank", "model", "prediction",
    "threshold", "selection_reason", "sampling_probability", "rng",
    "user_label", "coach_label", "peer_label", "judgment",
)


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
    now = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)

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

    # The slice-4 pair, seeded fresh: the grant RPC matches the policy's own
    # approval (terms, privacy and copy hash) and needs active_from at or
    # before the grant time, so a policy another suite left in the lane can
    # never be the one this grant names.
    approval = str(uuid.uuid4())
    active_from = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
    cur.execute(
        "INSERT INTO public.ml_product_legal_approvals (id, approval_reference, approved_copy_sha256, "
        "onboarding_copy, consent_policy_version, terms_version, privacy_policy_version, "
        "approving_authority, approved_at, jurisdictions, article_6_basis, article_9_treatment, "
        "evidence_object_key, evidence_sha256) VALUES (%s, %s, %s, 'Rehearsal copy', %s, 'terms-v1', "
        "'privacy-v1', 'isolated-test', %s, ARRAY['EU'], '6(1)(a)', '9(2)(a)_when_special_category', "
        "'legal/g6.json', %s)",
        (approval, f"G6-REHEARSAL-{tag}", SHA["1"], f"g6-consent-{tag}", active_from, SHA["2"]),
    )
    cur.execute(
        "INSERT INTO public.ml_consent_policies (version, product_legal_approval_id, "
        "required_for_service, bundled_ui, active_from) VALUES (%s, %s, true, true, %s)",
        (f"g6-consent-{tag}", approval, active_from),
    )
    policy = {"version": f"g6-consent-{tag}", "terms_version": "terms-v1",
              "privacy_policy_version": "privacy-v1"}

    cur.execute(
        "SELECT public.register_ml_speaker_principal_v1(%s, %s, 'speaker-resolution-v1', 'initial', %s, "
        "'rehearsal', 'speaker-sha256-80-10-10-v1')", (owner, SHA["3"], SHA["4"]))
    cur.execute(
        "SELECT public.record_mlc2_consent_grant_v1(%s, %s, 'EU', %s, %s, '/g6', 'rehearsal-client', "
        "%s, %s, true, %s)",
        (owner, policy["version"], policy["terms_version"], policy["privacy_policy_version"],
         psycopg2.extras.Json({"accepted": True, "copy_sha256": SHA["1"],
                               "purposes": ["personalized_coaching", "pooled_model_improvement"]}),
         now, f"g6-consent-grant-{tag}"))
    cur.execute("SELECT public.create_mlc2_consent_snapshot_v1(%s, %s, NULL, NULL)", (owner, attempt))
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


def _candidate_set_id(chain):
    cur = chain["cur"]
    row = _one(cur, "SELECT id FROM public.ml_candidate_sets WHERE take_id = %s", (chain["attempt"],))
    assert row, chain["result"]
    return row["id"]


class TestThePromotionFreezesTheConsentSnapshot:
    """0392 (Q1): a second attempt of the same owner promotes with no
    pre-made snapshot, and the promotion takes one; an owner with no grant
    is still refused, and the refusal rolls the Take promotion back."""

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

    def test_a_second_attempt_promotes_without_a_pre_made_snapshot(self, chain):
        cur = chain["cur"]
        attempt = self._attempt(chain, chain["owner"], chain["project"], "second")
        assert _one(cur, "SELECT 1 AS present FROM public.ml_consent_snapshots WHERE recording_attempt_id = %s",
                    (attempt,)) is None
        cur.execute(
            "SELECT public.promote_recording_attempt_with_mlc2_confidence_v1(%s, %s, NULL, 1, %s, %s, %s, %s) AS r",
            (attempt, SHA["5"], SHA["6"], SHA["7"], f"g6-promotion-{chain['tag']}-second",
             psycopg2.extras.Json(MANIFEST)))
        promotion = cur.fetchone()["r"]
        assert promotion["take_id"], promotion
        snapshot = _one(cur, "SELECT id, purpose_state, retention_state FROM public.ml_consent_snapshots "
                             "WHERE recording_attempt_id = %s AND acquisition_principal_id = %s",
                        (attempt, chain["owner"]))
        assert snapshot is not None
        assert snapshot["retention_state"] == "eligible"
        assert snapshot["purpose_state"]["pooled_model_improvement"]["authorized"] is True
        receipt = _one(cur, "SELECT consent_snapshot_id FROM public.ml_confidence_producer_receipts "
                            "WHERE take_id = %s", (attempt,))
        assert str(receipt["consent_snapshot_id"]) == str(snapshot["id"])

    def test_the_pre_made_snapshot_of_the_first_attempt_was_honoured_not_doubled(self, chain):
        cur = chain["cur"]
        cur.execute("SELECT count(*) AS n FROM public.ml_consent_snapshots WHERE recording_attempt_id = %s",
                    (chain["attempt"],))
        assert cur.fetchone()["n"] == 1

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
        assert "no active bundled MLC-2 consent grant" in str(refusal.value)
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

    def test_the_event_is_processed_after_the_worker_ran(self, chain):
        row = _one(chain["cur"], "SELECT processed_at, last_error_code FROM public.ml_outbox_events "
                                 "WHERE aggregate_id = %s", (chain["attempt"],))
        assert row["processed_at"] is not None and row["last_error_code"] is None, row


class TestTheFrameIsStored:
    def test_one_candidate_set_with_every_snippet_that_has_a_span(self, chain):
        cur = chain["cur"]
        set_id = _candidate_set_id(chain)
        assert _count(cur, "SELECT count(*) FROM public.ml_candidates WHERE candidate_set_id = %s", (set_id,)) == 5
        assert _count(cur, "SELECT count(*) FROM public.ml_candidates WHERE candidate_set_id = %s AND selected",
                      (set_id,)) == 1
        assert _count(cur, "SELECT count(*) FROM public.ml_candidates WHERE candidate_set_id = %s AND eligible",
                      (set_id,)) == 3

    def test_every_span_is_the_snippets_exact_offsets_on_the_takes_own_object(self, chain):
        cur = chain["cur"]
        cur.execute(
            "SELECT e.coordinates, o.object_store, o.bucket, o.object_key, o.sha256, o.byte_size, "
            "o.content_type, e.take_id, e.recording_attempt_id "
            "FROM public.ml_evidence_spans e JOIN public.ml_object_artifacts o ON o.id = e.object_artifact_id "
            "WHERE e.take_id = %s ORDER BY (e.coordinates->>'start_ms')::int", (chain["attempt"],))
        rows = [dict(r) for r in cur.fetchall()]
        assert [(r["coordinates"]["start_ms"], r["coordinates"]["end_ms"]) for r in rows] == [
            (s[1], s[1] + s[2]) for s in chain["snippets"]
        ]
        # The identity exercise_evidence_matches_audio_v1 compares against a lineage.
        for r in rows:
            assert (r["object_store"], r["bucket"], r["object_key"], r["sha256"], r["byte_size"]) == (
                "cloudflare_r2", BUCKET, OBJECT_KEY, OBJECT_SHA, OBJECT_BYTES)
            assert r["content_type"].startswith("audio/")
            assert str(r["recording_attempt_id"]) == chain["attempt"]

    def test_a_prediction_exists_for_each_eligible_clip_and_none_for_the_rest(self, chain):
        cur = chain["cur"]
        set_id = _candidate_set_id(chain)
        cur.execute(
            "SELECT c.eligible, p.predicted_value, p.confidence_score "
            "FROM public.ml_candidates c LEFT JOIN public.ml_machine_predictions p ON p.id = c.machine_prediction_id "
            "WHERE c.candidate_set_id = %s ORDER BY c.rank NULLS LAST", (set_id,))
        rows = [dict(r) for r in cur.fetchall()]
        eligible = [r for r in rows if r["eligible"]]
        assert sorted(r["predicted_value"] for r in eligible) == ["in_between", "no", "yes"]
        assert all(r["predicted_value"] is None for r in rows if not r["eligible"])

    def test_the_runs_record_the_foundation_detector_and_the_policy(self, chain):
        cur = chain["cur"]
        set_id = _candidate_set_id(chain)
        sel = _one(cur, "SELECT s.exploration_probability, s.selection_policy_version, "
                        "s.classification_run_id, s.rng_seed, s.rng_draws "
                        "FROM public.ml_candidate_sets c "
                        "JOIN public.ml_selection_runs s ON s.model_run_id = c.selection_run_id "
                        "WHERE c.id = %s", (set_id,))
        assert float(sel["exploration_probability"]) == 0.2
        run = _one(cur, "SELECT detector_version, taxonomy_version, threshold_version "
                        "FROM public.ml_classification_runs WHERE model_run_id = %s",
                   (sel["classification_run_id"],))
        assert run["detector_version"] == "voice-confidence-universal-v3"
        assert run["taxonomy_version"] == "conf-q-v2"
        assert run["threshold_version"] == "voice-confidence-thresholds-v3"

    def test_the_stored_draw_can_be_rederived_by_the_databases_own_rng(self, chain):
        """The worker's sha256 counter is exercise_rng_draw_v1's construction:
        the recorded draw equals the SQL function's value for the stored seed
        and the draw's index, so a selection can be re-checked in SQL."""
        cur = chain["cur"]
        set_id = _candidate_set_id(chain)
        sel = _one(cur, "SELECT s.rng_seed, s.rng_draws FROM public.ml_candidate_sets c "
                        "JOIN public.ml_selection_runs s ON s.model_run_id = c.selection_run_id "
                        "WHERE c.id = %s", (set_id,))
        for draw in sel["rng_draws"]:
            sql = _one(cur, "SELECT public.exercise_rng_draw_v1(convert_to(%s, 'UTF8'), %s) AS v",
                       (sel["rng_seed"], f":{draw['index']}"))["v"]
            assert abs(float(sql) - float(draw["value"])) < 1e-12


class TestAReplayChangesNothing:
    def test_the_worker_can_run_the_same_event_again(self, chain):
        cur = chain["cur"]
        before = (
            _count(cur, "SELECT count(*) FROM public.ml_candidate_sets WHERE take_id = %s", (chain["attempt"],)),
            _count(cur, "SELECT count(*) FROM public.ml_evidence_spans WHERE take_id = %s", (chain["attempt"],)),
        )
        again = chain["worker"].process_claimed(chain["claimed"], worker_id=chain["worker_id"])
        after = (
            _count(cur, "SELECT count(*) FROM public.ml_candidate_sets WHERE take_id = %s", (chain["attempt"],)),
            _count(cur, "SELECT count(*) FROM public.ml_evidence_spans WHERE take_id = %s", (chain["attempt"],)),
        )
        assert before == after == (1, 5)
        assert again["idempotent_replay"] is True
        assert str(again["candidate_set_id"]) == str(_candidate_set_id(chain))
        assert chain["result"]["idempotent_replay"] is False


class TestTheBlindPacket:
    def test_a_packet_from_the_selected_candidate_carries_no_answer_or_hint(self, chain):
        cur = chain["cur"]
        set_id = _candidate_set_id(chain)
        selected = _one(cur, "SELECT id FROM public.ml_candidates WHERE candidate_set_id = %s AND selected", (set_id,))
        cur.execute(
            "SELECT public.create_mlc2_confidence_blind_packet_v1(%s, %s, 'coach', "
            "'confidence-five-state-v1', 'blind-confidence-v1', 'canary', %s)",
            (selected["id"], chain["reviewer"], f"g6-blind-packet-{chain['tag']}"))
        packet = _one(cur, "SELECT visible_packet FROM public.ml_confidence_blind_packets WHERE candidate_id = %s",
                      (selected["id"],))["visible_packet"]
        assert not any(k in packet for k in LEAK_KEYS), packet
        assert not any(k in (packet.get("clip") or {}) for k in ("transcript", "score", "rank")), packet
        assert packet["taxonomy"]["choices"] == [
            "rating_yes", "rating_in_between", "rating_no", "rating_not_sure", "rating_audio_unclear",
        ]


class TestTheCoachCardConsumesTheChain:
    """0393 (Q2): the legacy coach card's three wrappers, in the order the
    card uses them: packet, render receipt, judgment with its reveal."""

    @pytest.fixture(scope="class")
    def coach(self, chain):
        cur = chain["cur"]
        coach = str(uuid.uuid4())
        cur.execute("INSERT INTO public.owner_principals (id, guest_secret_hash) VALUES (%s, %s)",
                    (coach, f"g6-coach-{chain['tag']}"))
        selected = _one(cur, "SELECT id FROM public.ml_candidates WHERE candidate_set_id = %s AND selected",
                        (_candidate_set_id(chain),))
        snippet = _one(cur, "SELECT clip_id FROM public.ml_candidates WHERE id = %s", (selected["id"],))
        return {"principal": coach, "candidate_id": str(selected["id"]), "snippet_id": str(snippet["clip_id"])}

    def _packet(self, chain, coach):
        return _one(chain["cur"],
                    "SELECT public.prepare_mlc2_confidence_coach_packet_v1(%s, %s, %s, 'canary') AS p",
                    (chain["attempt"], coach["snippet_id"], coach["principal"]))["p"]

    def test_the_selected_snippet_yields_a_packet_with_the_four_identifiers(self, chain, coach):
        packet = self._packet(chain, coach)
        assert packet is not None
        for field in ("review_assignment_id", "presentation_id", "acknowledgement_token",
                      "visible_packet_sha256"):
            assert packet.get(field), field
        assert str(packet["candidate_id"]) == coach["candidate_id"]
        assert not any(k in packet["visible_packet"] for k in LEAK_KEYS)
        again = self._packet(chain, coach)
        assert again["review_assignment_id"] == packet["review_assignment_id"]
        assert again["replayed"] is True

    def test_a_snippet_without_a_selected_candidate_yields_nothing(self, chain, coach):
        cur = chain["cur"]
        other = _one(cur, "SELECT clip_id FROM public.ml_candidates WHERE candidate_set_id = %s AND NOT selected LIMIT 1",
                     (_candidate_set_id(chain),))
        row = _one(cur, "SELECT public.prepare_mlc2_confidence_coach_packet_v1(%s, %s, %s, 'canary') AS p",
                   (chain["attempt"], other["clip_id"], coach["principal"]))
        assert row["p"] is None

    def test_the_owner_reviewing_their_own_take_gets_no_packet(self, chain, coach):
        row = _one(chain["cur"],
                   "SELECT public.prepare_mlc2_confidence_coach_packet_v1(%s, %s, %s, 'canary') AS p",
                   (chain["attempt"], coach["snippet_id"], chain["owner"]))
        assert row["p"] is None

    def test_the_render_receipt_then_the_judgment_then_the_reveal(self, chain, coach):
        cur = chain["cur"]
        packet = self._packet(chain, coach)
        render_instance = str(uuid.uuid4())
        exposure = _one(cur,
                        "SELECT * FROM public.ack_mlc2_confidence_coach_render_v1(%s, %s, %s, %s, %s, now(), "
                        "'coach-card-blind-v1', %s, %s)",
                        (packet["review_assignment_id"], packet["presentation_id"],
                         packet["acknowledgement_token"], coach["principal"], render_instance,
                         packet["visible_packet_sha256"], f"g6-card-render-{chain['tag']}"))
        assert exposure["id"]
        key = f"g6-card-judgment-{chain['tag']}"
        result = _one(cur,
                      "SELECT public.submit_mlc2_confidence_coach_judgment_v1(%s, %s, %s, 'rating_yes', now(), %s) AS r",
                      (packet["review_assignment_id"], coach["principal"], exposure["id"], key))["r"]
        assert result["replayed"] is False and result["revealed"] is True and result["reveal_event_id"]
        judgment = _one(cur, "SELECT actor_provenance, decision, exposure_id, training_eligibility "
                             "FROM public.ml_judgments WHERE id = %s", (result["judgment_id"],))
        assert judgment["actor_provenance"] == "blind_coach"
        assert judgment["decision"] == "rating_yes"
        assert str(judgment["exposure_id"]) == str(exposure["id"])
        assert judgment["training_eligibility"] == "potentially_eligible"
        revealed = _one(cur, "SELECT count(*) AS n FROM public.ml_review_assignment_events "
                             "WHERE review_assignment_id = %s AND event_kind = 'revealed'",
                        (packet["review_assignment_id"],))
        assert revealed["n"] == 1
        # The exact retry replays; a different answer on the same act is refused.
        replay = _one(cur,
                      "SELECT public.submit_mlc2_confidence_coach_judgment_v1(%s, %s, %s, 'rating_yes', now(), %s) AS r",
                      (packet["review_assignment_id"], coach["principal"], exposure["id"], key))["r"]
        assert replay["replayed"] is True and str(replay["judgment_id"]) == str(result["judgment_id"])
        cur.execute("SAVEPOINT second_answer")
        with pytest.raises(psycopg2.Error):
            cur.execute("SELECT public.submit_mlc2_confidence_coach_judgment_v1(%s, %s, %s, 'rating_no', now(), %s)",
                        (packet["review_assignment_id"], coach["principal"], exposure["id"], key + "-b"))
        cur.execute("ROLLBACK TO SAVEPOINT second_answer")

    def test_a_judgment_without_a_render_receipt_is_refused(self, chain, coach):
        cur = chain["cur"]
        packet = self._packet(chain, coach)
        cur.execute("SAVEPOINT no_receipt")
        with pytest.raises(psycopg2.Error):
            cur.execute("SELECT public.submit_mlc2_confidence_coach_judgment_v1(%s, %s, %s, 'rating_yes', now(), %s)",
                        (packet["review_assignment_id"], coach["principal"], str(uuid.uuid4()),
                         f"g6-card-no-receipt-{chain['tag']}"))
        cur.execute("ROLLBACK TO SAVEPOINT no_receipt")

    def test_readiness_counts_no_orphan_after_the_card_consumed_the_chain(self, chain, coach):
        readiness = _one(chain["cur"], "SELECT public.get_mlc2_confidence_canary_readiness_v1(%s) AS r",
                         (chain["owner"],))["r"]
        assert readiness["blind_assignment_without_packet_count"] == 0
        assert readiness["revealed_without_judgment_count"] == 0


class TestHealthStaysSafe:
    def test_the_slice4_health_reports_no_orphan_and_no_open_gate(self, chain):
        cur = chain["cur"]
        health = _one(cur, "SELECT public.get_mlc2_confidence_slice4_health_v1() AS h")["h"]
        assert health["processed_without_frame_count"] == 0
        assert health["receipt_without_outbox_count"] == 0
        assert health["blind_assignment_without_packet_count"] == 0
        assert health["dataset_creation_enabled"] is False
        assert health["training_enabled"] is False
        assert health["promotion_enabled"] is False
