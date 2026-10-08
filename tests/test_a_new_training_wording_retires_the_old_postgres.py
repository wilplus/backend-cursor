"""A new training wording retires the old one, in one call (0458; founder
D3, decisions log N68; legal/phase1-2026.1/23-…-v2-SIGNED-2026-10-08.md).

Run on the released rehearsal lane. Every case runs in one transaction that
is rolled back, so the policies it registers and retires never reach another
module. Each case first retires, inside that transaction only, whatever
training policy the shared lane already holds (the precedent is
tests/test_the_chain_hears_the_training_yes_postgres.py), then registers its
own "v1" through configure_mlc2_training_consent_policy_v1 (0373).

Pins:
  * one call retires v1 at the switch instant and registers v2 active from
    the same instant; exactly one training policy is in force afterwards;
  * a yes given under v1 reads as off once v1 is retired: the status reader,
    the pair view (door 2), the corpus copy and a new v1 yes all say so; the
    v1 consent events are all still there;
  * a new yes under v2 is recorded and reads as on;
  * the same call again changes nothing and answers replayed; any other
    call once v2 exists, or naming a predecessor that is not in force, or a
    switch instant in the past, is refused;
  * while a training copy made under a v1 yes is not yet purged (active or
    purge_pending), the call is refused and nothing changes; a purged one
    does not stop it;
  * the call holds training_corpus_items in SHARE ROW EXCLUSIVE mode until
    its transaction ends: another session's corpus write waits, its reads
    do not;
  * browser roles, PUBLIC and service_role cannot execute it, nor the guard;
  * a runtime role that can UPDATE the table and sets the door itself is
    still refused: the door opens only for the supersede function's owner;
  * the trigger keeps its name and still refuses every other UPDATE and
    every DELETE, the door's setting included; the door is closed again when
    the call returns.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import uuid

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "a_new_training_wording_retires_the_old.sql"
SUPERSEDE = ("public.supersede_mlc2_training_consent_policy_v1(text, text, text, "
             "text, text, text, text, text, timestamptz, text[], text, text, "
             "text, timestamptz)")
DOOR = "willab.training_policy_supersede"
GUARD = "public.guard_ml_consent_policy_mutation_v1()"

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


def test_a_new_yes_under_v2_is_recorded_and_reads_as_on(cur, lane):
    _supersede(cur, lane)
    speaker = lane["speaker"]
    grant = _grant(cur, speaker, lane["v2"], "terms-t2", "privacy-t2", V2_SHA)
    status = _status(cur, speaker)
    assert status["active"] is True
    assert status["grant_event_id"] == str(grant)
    assert status["consent_policy_version"] == lane["v2"]
    assert _one(cur, "SELECT consent_policy_version "
                     "FROM public.training_consent_active_grants "
                     "WHERE acquisition_principal_id = %s", (speaker,)) == lane["v2"]
    # The v1 wording's fingerprint does not buy a v2 yes.
    _raises(cur, "TRAINING_CONSENT_DOES_NOT_MATCH_APPROVAL",
            """SELECT public.record_mlc2_training_consent_grant_v2(
                   %s, %s, 'PL', 'terms-t2', 'privacy-t2', 'settings/training',
                   'test', %s::jsonb, now(), %s)""",
            (speaker, lane["v2"], _action(V1_SHA), f"g-{uuid.uuid4()}"))


# ── Again: the same call is a replay; every other call is refused ─────────

def test_the_same_call_again_changes_nothing(cur, lane):
    _supersede(cur, lane)
    before = _policies(cur, lane)
    again = _supersede(cur, lane)
    assert again["replayed"] is True
    assert again["consent_policy_version"] == lane["v2"]
    assert _policies(cur, lane) == before


def test_any_other_second_call_is_refused(cur, lane):
    _supersede(cur, lane)
    # The same successor at another instant.
    sql, args = _supersede_args(lane, active_from="now() + interval '1 hour'")
    _raises(cur, "TRAINING_POLICY_SUPERSEDE_COLLISION", sql, args)
    # The same successor with other words.
    sql, args = _supersede_args(lane)
    args = args[:2] + (V1_SHA, V1_COPY) + args[4:]
    _raises(cur, "TRAINING_POLICY_IDEMPOTENCY_COLLISION", sql, args)
    # Retiring the already-retired v1 again, for a third policy.
    sql, args = _supersede_args(lane, version=f"training-only-v3-{lane['tag']}")
    _raises(cur, "TRAINING_POLICY_PREDECESSOR_NOT_ACTIVE", sql, args)
    assert _policies(cur, lane)[lane["v2"]]["in_force"] is True


def test_it_refuses_a_bad_predecessor_or_instant(cur, lane):
    sql, args = _supersede_args(lane, predecessor="no-such-policy")
    _raises(cur, "TRAINING_POLICY_PREDECESSOR_UNKNOWN", sql, args)
    sql, args = _supersede_args(lane, version=lane["v1"])
    _raises(cur, "TRAINING_POLICY_CANNOT_SUPERSEDE_ITSELF", sql, args)
    sql, args = _supersede_args(lane, active_from="now() - interval '1 second'")
    _raises(cur, "TRAINING_POLICY_SWITCH_IN_THE_PAST", sql, args)
    # A refused call leaves v1 in force and registers nothing.
    rows = _policies(cur, lane)
    assert rows[lane["v1"]]["in_force"] is True and lane["v2"] not in rows
    assert _status(cur, lane["speaker"])["active"] is True


def test_a_failed_registration_leaves_v1_in_force(cur, lane):
    # The evidence placeholder left in: configure refuses, and the
    # retirement made earlier in the same call is undone with it.
    sql, args = _supersede_args(lane)
    args = args[:5] + ("<SIGNED_PDF_SHA256_OF_23>",) + args[6:]
    _raises(cur, "TRAINING_POLICY_EVIDENCE_HASH_REQUIRED", sql, args)
    rows = _policies(cur, lane)
    assert rows[lane["v1"]]["retired_at"] is None and lane["v2"] not in rows
    assert (_one(cur, "SELECT current_setting(%s, true)", (DOOR,)) or "") == ""


def test_an_active_copy_under_a_v1_yes_stops_the_call(cur, lane):
    artifact = _one(cur, """
        INSERT INTO public.processing_legal_artifacts (
            artifact_kind, version, approving_authority, approved_at,
            object_key, sha256)
        VALUES ('retention_schedule', 'supersede-' || gen_random_uuid(),
                'rehearsal', now(), 'rehearsal/retention.pdf', %s)
        RETURNING id""", ("a" * 64,))
    _one(cur, """
        INSERT INTO public.data_retention_rules (
            rule_code, evidence_category, retention_until_rule,
            legal_artifact_id, active)
        VALUES ('training_corpus', 'training_corpus', 'until withdrawal', %s, true)
        ON CONFLICT (rule_code) DO UPDATE SET active = true
        RETURNING id""", (artifact,))
    _one(cur, """
        SELECT (public.record_training_corpus_item_v1(
            %s, %s, 'project', 'take', %s, %s, 'transcript_span', NULL,
            '{"text": "every word"}'::jsonb, NULL, NULL, NULL, NULL)).id""",
         (lane["speaker"], lane["v1_grant"], f"snippet:{uuid.uuid4()}", "1" * 64))
    sql, args = _supersede_args(lane)
    _raises(cur, "TRAINING_POLICY_PREDECESSOR_HAS_ACTIVE_COPIES", sql, args)
    rows = _policies(cur, lane)
    assert rows[lane["v1"]]["in_force"] is True and lane["v2"] not in rows
    # Due for erasure is not gone: its object may still be in storage.
    cur.execute("UPDATE public.training_corpus_items SET state = 'purge_pending', "
                "state_changed_at = now() WHERE training_grant_event_id = %s",
                (lane["v1_grant"],))
    _raises(cur, "TRAINING_POLICY_PREDECESSOR_HAS_ACTIVE_COPIES", sql, args)
    rows = _policies(cur, lane)
    assert rows[lane["v1"]]["in_force"] is True and lane["v2"] not in rows
    # Purged (the object verified gone) no longer stops the call.
    cur.execute("UPDATE public.training_corpus_items SET state = 'purged', "
                "state_changed_at = now() WHERE training_grant_event_id = %s",
                (lane["v1_grant"],))
    assert _supersede(cur, lane)["replayed"] is False


def test_the_call_holds_the_corpus_still_until_it_ends(cur, lane):
    _supersede(cur, lane)
    assert _one(cur, """
        SELECT count(*) FROM pg_locks
         WHERE pid = pg_backend_pid() AND granted
           AND relation = 'public.training_corpus_items'::regclass
           AND mode = 'ShareRowExclusiveLock'""") == 1
    other = psycopg2.connect(DSN)
    other.autocommit = True
    try:
        with other.cursor() as cursor:
            cursor.execute("SET lock_timeout = '300ms'")
            # Reads go on.
            cursor.execute("SELECT count(*) FROM public.training_corpus_items")
            # A write (an insert, or a state moving) waits for the call's end.
            with pytest.raises(psycopg2.errors.LockNotAvailable):
                cursor.execute("UPDATE public.training_corpus_items "
                               "SET state = state WHERE false")
    finally:
        other.close()


# ── Who may call it ───────────────────────────────────────────────────────

def _role_exists(cur, role):
    return bool(_one(cur, "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)))


def test_no_browser_or_runtime_role_may_execute_it(cur):
    assert _one(cur, "SELECT prosecdef FROM pg_proc WHERE oid = %s::regprocedure",
                (SUPERSEDE,)) is True
    assert _one(cur, "SELECT count(*) FROM pg_proc p, aclexplode(p.proacl) a "
                     "WHERE p.oid = %s::regprocedure AND a.grantee = 0",
                (SUPERSEDE,)) == 0
    for role in ("anon", "authenticated", "service_role"):
        if not _role_exists(cur, role):
            continue
        assert _one(cur, "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                    (role, SUPERSEDE)) is False, role
        assert _one(cur, "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                    (role, GUARD)) is False, (role, GUARD)
        for privilege in ("UPDATE", "DELETE"):
            assert _one(cur, "SELECT has_table_privilege(%s, "
                             "'public.ml_consent_policies', %s)",
                        (role, privilege)) is False, (role, privilege)


# ── The trigger: one door, nothing else ───────────────────────────────────

def test_the_trigger_keeps_its_name_and_its_new_guard(cur):
    assert _one(cur, """
        SELECT p.proname FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
         WHERE t.tgname = 'ml_consent_policies_append_only'
           AND t.tgrelid = 'public.ml_consent_policies'::regclass""") \
        == "guard_ml_consent_policy_mutation_v1"


def test_the_trigger_still_refuses_every_other_change(cur, lane):
    refused = "append-only"
    v1 = lane["v1"]
    # No door: retiring by hand is refused, as before 0458.
    _raises(cur, refused, "UPDATE public.ml_consent_policies SET retired_at = now() "
                          "WHERE version = %s", (v1,))
    _raises(cur, refused, "DELETE FROM public.ml_consent_policies WHERE version = %s",
            (v1,))
    cur.execute("SELECT set_config(%s, %s, true)", (DOOR, v1))
    # With the door named, any other column, alone or beside retired_at.
    _raises(cur, refused, "UPDATE public.ml_consent_policies "
                          "SET active_from = active_from - interval '1 day' "
                          "WHERE version = %s", (v1,))
    _raises(cur, refused, "UPDATE public.ml_consent_policies "
                          "SET retired_at = now() + interval '1 day', "
                          "requires_processing_policy_version = 'other' "
                          "WHERE version = %s", (v1,))
    # Never a DELETE.
    _raises(cur, refused, "DELETE FROM public.ml_consent_policies WHERE version = %s",
            (v1,))
    # Never a bundled row, nor a row the door does not name.
    bundled = _one(cur, "SELECT version FROM public.ml_consent_policies "
                        "WHERE grant_scope = 'bundled_v1' AND retired_at IS NULL "
                        "LIMIT 1")
    if bundled:
        cur.execute("SELECT set_config(%s, %s, true)", (DOOR, bundled))
        _raises(cur, refused, "UPDATE public.ml_consent_policies "
                              "SET retired_at = now() + interval '1 day' "
                              "WHERE version = %s AND retired_at IS NULL", (bundled,))
    cur.execute("SELECT set_config(%s, %s, true)", (DOOR, "some-other-version"))
    _raises(cur, refused, "UPDATE public.ml_consent_policies "
                          "SET retired_at = now() + interval '1 day' "
                          "WHERE version = %s", (v1,))
    # Once retired, never re-dated, door or not.
    cur.execute("SELECT set_config(%s, '', true)", (DOOR,))
    _supersede(cur, lane)
    cur.execute("SELECT set_config(%s, %s, true)", (DOOR, v1))
    _raises(cur, refused, "UPDATE public.ml_consent_policies "
                          "SET retired_at = now() + interval '1 day' "
                          "WHERE version = %s", (v1,))
    _raises(cur, refused, "UPDATE public.ml_consent_policies SET retired_at = NULL "
                          "WHERE version = %s", (v1,))


def test_a_runtime_role_that_sets_the_door_itself_is_refused(cur, lane):
    """The door's setting is transaction-local and any role may set it. Give
    service_role, inside this rolled-back transaction, everything it would
    need to reach the row (UPDATE, and a row-security policy), set the door
    to v1 as service_role, and retire v1 directly: the guard refuses,
    because the statement does not run as the supersede function's owner."""
    if not _role_exists(cur, "service_role"):
        pytest.skip("no service_role on this lane")
    v1 = lane["v1"]
    cur.execute("GRANT SELECT, UPDATE ON public.ml_consent_policies TO service_role")
    cur.execute("CREATE POLICY supersede_rehearsal_reach ON public.ml_consent_policies "
                "FOR ALL TO service_role USING (true) WITH CHECK (true)")
    cur.execute("SET LOCAL ROLE service_role")
    cur.execute("SELECT set_config(%s, %s, true)", (DOOR, v1))
    # Any instant, no copy check: exactly what the door must not let through.
    _raises(cur, "append-only", "UPDATE public.ml_consent_policies "
                                "SET retired_at = now() - interval '1 day' "
                                "WHERE version = %s", (v1,))
    _raises(cur, "append-only", "UPDATE public.ml_consent_policies "
                                "SET retired_at = now() + interval '1 day' "
                                "WHERE version = %s", (v1,))
    cur.execute("RESET ROLE")
    assert _policies(cur, lane)[v1]["retired_at"] is None
    assert _status(cur, lane["speaker"])["active"] is True


def test_applied_again_the_file_changes_nothing(cur, lane):
    _supersede(cur, lane)
    before = _policies(cur, lane)
    # Without its BEGIN/COMMIT, so the case's transaction is still rolled back.
    body = "\n".join(line for line in MIGRATION.read_text().splitlines()
                     if line.strip() not in ("BEGIN;", "COMMIT;"))
    cur.execute(body)
    assert _policies(cur, lane) == before
    test_the_trigger_keeps_its_name_and_its_new_guard(cur)
