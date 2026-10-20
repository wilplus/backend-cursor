"""
STORY    As a speaker, I want my training "yes" to count only for the wording
         I actually agreed to, so that a new consent sentence needs my new
         yes.
OUTCOME
  O1  One call retires the old wording and starts the new one at the same
      instant; exactly one wording is in force, with the signed sentence.
  O2  A yes given under the old wording now reads as off: no new yes to
      the old wording, and no training copy made on it.
  O3  The old yes stays on record as it was and can still be withdrawn.
PROVES   O1 -> test_one_call_retires_v1_and_registers_v2_at_the_same_instant
         O2, O3 -> test_a_v1_yes_reads_as_off_everywhere_and_stays_on_record
WHY      Founder D3, N68 (migration 0458).
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

DOOR = "willab.training_policy_supersede"

V1_COPY = "Supersede test: the old training switch sentence."
V1_SHA = hashlib.sha256(V1_COPY.encode()).hexdigest()
V2_COPY = ("Use my practice text, my coach's words and answers about it, and "
           "measurements of my practice to train the models that give every "
           "WillpowerLab speaker feedback.")
V2_SHA = "69d3e70205d991b725a55d5a537071358a9fd31b236d5c5049a5273fb521083c"


@pytest.fixture
def cur():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            yield cursor
    finally:
        conn.rollback()
        conn.close()


def _one(cur, sql, args=()):
    cur.execute(sql, args)
    row = cur.fetchone()
    return next(iter(row.values())) if row else None


def _raises(cur, code, sql, args=()):
    cur.execute("SAVEPOINT expect_refusal")
    with pytest.raises(psycopg2.Error) as caught:
        cur.execute(sql, args)
    cur.execute("ROLLBACK TO SAVEPOINT expect_refusal")
    assert code in str(caught.value), str(caught.value)


def _processing_version(cur):
    return _one(cur, "SELECT version FROM public.processing_policy_versions "
                     "ORDER BY created_at LIMIT 1")


def _principal(cur):
    return _one(cur, "INSERT INTO public.owner_principals (id, user_id) "
                     "VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id")


def _receipt(cur, principal, version):
    _one(cur, """
        INSERT INTO public.processing_authorization_receipts (
            acquisition_principal_id, policy_id, idempotency_key,
            explicit_action, age_18_attested, country_of_residence, locale,
            client_version, accepted_at, evidence_sha256)
        SELECT %s, id, %s, 'agree_and_continue', true, 'PL', 'en-GB', 'test',
               now(), %s
          FROM public.processing_policy_versions WHERE version = %s
        RETURNING id""", (principal, f"r-{uuid.uuid4()}", "a" * 64, version))


def _action(sha):
    return json.dumps({"accepted": True, "control": "training_toggle",
                       "copy_sha256": sha})


def _grant(cur, principal, policy, terms, privacy, sha, at="now()"):
    return _one(cur, f"""
        SELECT (public.record_mlc2_training_consent_grant_v2(
            %s, %s, 'PL', %s, %s, 'settings/training', 'test', %s::jsonb,
            {at}, %s)).id""",
        (principal, policy, terms, privacy, _action(sha), f"g-{uuid.uuid4()}"))


def _status(cur, principal):
    return _one(cur, "SELECT public.get_mlc2_training_consent_status_v2(%s)",
                (principal,))


@pytest.fixture
def lane(cur):
    """A clean training slate inside the rolled-back transaction: every
    training policy the lane holds is retired with the trigger lifted (as
    other suites do), the trigger is put back, and a fresh v1 is registered
    and in force, with one speaker holding a v1 yes."""
    cur.execute("ALTER TABLE public.ml_consent_policies "
                "DISABLE TRIGGER ml_consent_policies_append_only")
    cur.execute("UPDATE public.ml_consent_policies "
                "SET retired_at = now() - interval '2 seconds' "
                "WHERE grant_scope = 'training_only' "
                "AND active_from < now() - interval '2 seconds' "
                "AND (retired_at IS NULL OR retired_at > now() - interval '2 seconds')")
    cur.execute("ALTER TABLE public.ml_consent_policies "
                "ENABLE TRIGGER ml_consent_policies_append_only")
    assert _one(cur, "SELECT count(*) FROM public.ml_consent_policies "
                     "WHERE grant_scope = 'training_only' "
                     "AND (retired_at IS NULL OR retired_at > now())") == 0
    tag = uuid.uuid4().hex[:8]
    processing = _processing_version(cur)
    v1, v2 = f"training-only-v1-{tag}", f"training-only-v2-{tag}"
    _one(cur, """
        SELECT public.configure_mlc2_training_consent_policy_v1(
            %s, %s, %s, %s, 'terms-t1', 'privacy-t1', 'founder', now(),
            ARRAY['PL'], 'evidence/v1.pdf', %s, %s, now() - interval '2 seconds')""",
        (f"approval-{v1}", V1_SHA, V1_COPY, v1, "e" * 64, processing))
    speaker = _principal(cur)
    _receipt(cur, speaker, processing)
    v1_grant = _grant(cur, speaker, v1, "terms-t1", "privacy-t1", V1_SHA,
                      at="now() - interval '1 second'")
    assert _status(cur, speaker)["active"] is True
    return {"v1": v1, "v2": v2, "tag": tag, "processing": processing,
            "speaker": speaker, "v1_grant": v1_grant}


def _supersede_args(lane, *, predecessor=None, version=None, active_from="now()"):
    version = version or lane["v2"]
    sql = f"""
        SELECT public.supersede_mlc2_training_consent_policy_v1(
            %s, %s, %s, %s, %s, 'terms-t2', 'privacy-t2', 'founder',
            now(), ARRAY['PL'], 'evidence/v2.pdf', %s, %s, {active_from})"""
    args = (predecessor or lane["v1"], f"approval-{version}", V2_SHA, V2_COPY,
            version, "f" * 64, lane["processing"])
    return sql, args


def _supersede(cur, lane, **over):
    sql, args = _supersede_args(lane, **over)
    return _one(cur, sql, args)


def _policies(cur, lane):
    cur.execute("""
        SELECT version, active_from, retired_at,
               active_from <= now() AND (retired_at IS NULL OR retired_at > now())
                   AS in_force
          FROM public.ml_consent_policies
         WHERE version IN (%s, %s) ORDER BY version""", (lane["v1"], lane["v2"]))
    return {row["version"]: row for row in cur.fetchall()}


# ── One call: v1 retired, v2 in force ─────────────────────────────────────

def test_one_call_retires_v1_and_registers_v2_at_the_same_instant(cur, lane):
    now = _one(cur, "SELECT now()")
    result = _supersede(cur, lane)
    assert result["consent_policy_version"] == lane["v2"]
    assert result["predecessor_version"] == lane["v1"]
    assert result["replayed"] is False
    rows = _policies(cur, lane)
    assert rows[lane["v1"]]["retired_at"] == now
    assert rows[lane["v2"]]["active_from"] == now
    assert rows[lane["v2"]]["retired_at"] is None
    assert rows[lane["v1"]]["in_force"] is False
    assert rows[lane["v2"]]["in_force"] is True
    assert _one(cur, "SELECT count(*) FROM public.ml_consent_policies "
                     "WHERE grant_scope = 'training_only' AND active_from <= now() "
                     "AND (retired_at IS NULL OR retired_at > now())") == 1
    approval = _one(cur, """
        SELECT row_to_json(a) FROM public.ml_product_legal_approvals a
          JOIN public.ml_consent_policies p ON p.product_legal_approval_id = a.id
         WHERE p.version = %s""", (lane["v2"],))
    assert approval["onboarding_copy"] == V2_COPY
    assert approval["approved_copy_sha256"] == V2_SHA
    # The door is shut again once the call returns.
    assert (_one(cur, "SELECT current_setting(%s, true)", (DOOR,)) or "") == ""


# ── A v1 yes reads as off; a v2 yes reads as on ───────────────────────────

def test_a_v1_yes_reads_as_off_everywhere_and_stays_on_record(cur, lane):
    _supersede(cur, lane)
    speaker = lane["speaker"]
    assert _status(cur, speaker) == {"active": False}
    assert _one(cur, "SELECT count(*) FROM public.training_consent_active_grants "
                     "WHERE acquisition_principal_id = %s", (speaker,)) == 0
    # No new v1 yes: the policy is no longer in force.
    _raises(cur, "TRAINING_POLICY_NOT_ACTIVE",
            """SELECT public.record_mlc2_training_consent_grant_v2(
                   %s, %s, 'PL', 'terms-t1', 'privacy-t1', 'settings/training',
                   'test', %s::jsonb, now(), %s)""",
            (speaker, lane["v1"], _action(V1_SHA), f"g-{uuid.uuid4()}"))
    # No training copy can be made on the strength of the old yes.
    _raises(cur, "TRAINING_CORPUS_NO_ACTIVE_YES",
            """SELECT public.record_training_corpus_item_v1(
                   %s, %s, 'project', 'take', %s, %s, 'transcript_span', NULL,
                   '{"text": "words"}'::jsonb, NULL, NULL, NULL, NULL)""",
            (speaker, lane["v1_grant"], f"snippet:{uuid.uuid4()}", "1" * 64))
    # Nothing was rewritten: the v1 yes is still on record, as it was.
    assert _one(cur, "SELECT consent_policy_version FROM public.ml_consent_events "
                     "WHERE id = %s", (lane["v1_grant"],)) == lane["v1"]
    # A v1 yes may still be withdrawn (the record of the choice).
    withdrawal = _one(cur, """
        SELECT (public.record_mlc2_consent_withdrawal_v2(
            %s, %s, 'pooled_model_improvement', 'settings/training', 'test',
            '{"control": "training_toggle", "accepted": false}'::jsonb,
            now(), %s)).id""", (speaker, lane["v1_grant"], f"w-{uuid.uuid4()}"))
    assert withdrawal is not None


# ── Again: the same call is a replay; every other call is refused ─────────


# ── Who may call it ───────────────────────────────────────────────────────


# ── The trigger: one door, nothing else ───────────────────────────────────
