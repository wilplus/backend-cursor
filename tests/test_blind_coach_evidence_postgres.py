"""
STORY    As a coach, I want the blind evidence packet to carry only audio and
         timing, never the machine's or other raters' answers, so that my
         judgement stays blind.
OUTCOME
  O1  blind_coach_evidence_v1 gives the assigned coach the moment's audio and
      timing, and nothing else: no owner, machine or peer value, no words.
  O2  coach_evidence_comparison_v1 shows the owner, machine and peer answers
      only after the coach's own answer is committed; before it, nothing.
PROVES   O1 -> test_the_blind_packet_is_audio_and_timing_only
         O2 -> test_the_comparison_opens_only_after_the_coach_answers
WHY      CLAUDE.md Never rule 2; 0296 add_canonical_feedback_data_contract.sql.

Runs on the released confident-moment lane (scripts/rehearsal_tier.sh). Every
case is one transaction as the superuser that seeds, then calls the functions
as service_role (the backend's role), and is always rolled back.
"""
from __future__ import annotations

import os
import uuid

import psycopg2
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

PACKET_COLUMNS = [
    "evidence_span_id", "audio_ref", "start_ms", "end_ms",
    "technical_metadata",
]
OWNER, MACHINE, PEER, COACH = "no", "confident", "in_between", "yes"
SPOKEN = "We grew three times last year"


@pytest.fixture(scope="module")
def conn():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    if not parsed.get("host", "").startswith(
        ("/tmp/willab-", "/private/tmp/willab-")
    ):
        raise RuntimeError("Refusing a database outside the rehearsal socket")
    c = psycopg2.connect(DSN)
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def moment(conn):
    """One take with one confidence moment that the owner, the machine and a
    peer have already answered; a coach is assigned to it blind."""
    cur = conn.cursor()
    user_id, coach, peer = (str(uuid.uuid4()) for _ in range(3))

    def one(sql, args=()):
        cur.execute(sql, args)
        return cur.fetchone()[0]

    principal = one("INSERT INTO public.owner_principals (id, user_id) "
                    "VALUES (gen_random_uuid(), %s) RETURNING id", (user_id,))
    project = one("INSERT INTO public.projects (id, owner_principal_id, "
                  "display_name) VALUES (gen_random_uuid(), %s, 'Pitch') "
                  "RETURNING id", (principal,))
    take = one("INSERT INTO public.v2_sessions (id, user_id, "
               "owner_principal_id, project_id, arc_id, take_index) "
               "VALUES (gen_random_uuid(), %s, %s, %s, %s, 1) RETURNING id",
               (user_id, principal, project, str(project)))
    span = one("""
        INSERT INTO public.evidence_spans (
            id, owner_principal_id, project_id, take_id, evidence_kind,
            task_type, audio_ref, start_ms, end_ms, technical_metadata,
            evidence_hash, input_hash)
        VALUES (gen_random_uuid(), %s, %s, %s, 'audio_interval',
                'confidence_classification', 'take-audio/clip.wav', 1200,
                2800, '{"sample_rate": 16000}', %s, 'in')
        RETURNING id""", (principal, project, take, str(uuid.uuid4())))
    cur.execute("""
        INSERT INTO public.confidence_self_reports (
            id, evidence_span_id, value, rater_id, taxonomy_version,
            idempotency_key)
        VALUES (gen_random_uuid(), %s, %s, %s, 'v1', %s)""",
                (span, OWNER, principal, str(uuid.uuid4())))
    cur.execute("""
        INSERT INTO public.machine_predictions (
            id, evidence_span_id, owner_principal_id, project_id, take_id,
            task_type, surface, classification, score, model_version,
            input_hash, complete_output, code_commit)
        VALUES (gen_random_uuid(), %s, %s, %s, %s,
                'confidence_classification', 'rehearsal', %s, 0.91, 'm1',
                'in', jsonb_build_object('text', %s::text), 'abc')""",
                (span, principal, project, take, MACHINE, SPOKEN))
    cur.execute("""
        INSERT INTO public.confidence_peer_labels (
            id, evidence_span_id, value, rater_id, taxonomy_version,
            blind_packet_hash, idempotency_key)
        VALUES (gen_random_uuid(), %s, %s, %s, 'v1', 'peer-packet', %s)""",
                (span, PEER, peer, str(uuid.uuid4())))
    cur.execute("SET ROLE service_role")
    cur.execute(
        "SELECT public.assign_confidence_coach_evidence_v1("
        "%s, %s, %s, 'coach-packet', 'rehearsal', %s)",
        (take, span, coach, str(uuid.uuid4())))
    try:
        yield {"cur": cur, "take": take, "span": span, "coach": coach,
               "unassigned_rater": peer}
    finally:
        conn.rollback()
        cur.close()


def _blind(cur, take, coach):
    cur.execute("SELECT * FROM public.blind_coach_evidence_v1(%s, %s)",
                (take, coach))
    return [d.name for d in cur.description], cur.fetchall()


def _comparison(cur, span, coach):
    cur.execute("SELECT * FROM public.coach_evidence_comparison_v1(%s, %s)",
                (span, coach))
    return [d.name for d in cur.description], cur.fetchall()


def test_the_blind_packet_is_audio_and_timing_only(moment):
    cur = moment["cur"]
    columns, rows = _blind(cur, moment["take"], moment["coach"])
    assert columns == PACKET_COLUMNS
    assert rows == [(moment["span"], "take-audio/clip.wav", 1200, 2800,
                     {"sample_rate": 16000})]
    packet = repr(rows)
    for answer in (OWNER, MACHINE, PEER, SPOKEN):
        assert f"'{answer}'" not in packet
    # A rater who was not assigned this moment gets nothing at all.
    assert _blind(cur, moment["take"], moment["unassigned_rater"])[1] == []


def test_the_comparison_opens_only_after_the_coach_answers(moment):
    cur, span, coach = moment["cur"], moment["span"], moment["coach"]
    assert _comparison(cur, span, coach)[1] == []

    cur.execute(
        "SELECT public.record_confidence_coach_judgment_v1("
        "%s, %s, %s, 'v1', 'coach-packet', %s)",
        (span, coach, COACH, str(uuid.uuid4())))

    columns, rows = _comparison(cur, span, coach)
    assert columns == ["coach_label_id", "coach_value", "owner_value",
                       "machine_value", "peer_values"]
    [(_, coach_value, owner_value, machine_value, peer_values)] = rows
    assert (coach_value, owner_value, machine_value) == (COACH, OWNER, MACHINE)
    assert [p["value"] for p in peer_values] == [PEER]
    # Answered moments leave the blind queue.
    assert _blind(cur, moment["take"], coach)[1] == []
