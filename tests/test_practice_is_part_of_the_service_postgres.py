"""Practice is part of the service (0454; founder N55, N66.2).

Runs the real functions in the released lane. Under a policy where practice
is optional (the shape of 3.3, and of the shared optional-consent policy
these suites use) every answer is what it was. Under a policy that makes
practice required (the shape of 3.4) practice reads as on for every receipt
and no withdraw event turns it off. That second policy is made inside one
transaction that is rolled back, so no other suite sees it.

And the blind check's written objection: recorded once per person, read for
the whole person, closed to browser roles.
"""
from __future__ import annotations

import uuid

import psycopg2
import pytest

from tests import test_optional_consent_postgres as base

DSN = base.DSN
OPTIONAL = base.OPTIONAL
_accept = base._accept
_one = base._one
db = base.db
policy = base.policy
principal = base.principal

pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

PRACTICE = "personalized_exercise_recommendation"


def _state(conn, principal):
    with conn.cursor() as cur:
        cur.execute("SELECT public.get_phase1_consent_choices_v1(%s)",
                    (principal,))
        return cur.fetchone()[0]


def _withdraw_practice(db, principal):
    return _one(db, """
        SELECT public.set_phase1_consent_choice_v1(
            %s, 'personalised_practice', false, %s, 'test')""",
        (principal, f"choice-{uuid.uuid4()}"))


def test_where_practice_is_a_choice_nothing_changes(db, policy, principal):
    _accept(db, policy, principal, [OPTIONAL])
    state = _state(db, principal)
    assert state["practice_in_service"] is False
    assert state["personalised_practice"] is True
    _withdraw_practice(db, principal)
    assert _state(db, principal)["personalised_practice"] is False


def test_without_a_receipt_the_answer_says_whether_practice_is_a_choice(
        db, policy, principal):
    state = _state(db, principal)
    assert state["has_receipt"] is False
    assert state["practice_in_service"] is False
    assert state["optional_purposes"] == [OPTIONAL]


def test_where_practice_is_part_of_the_service_it_is_on_and_stays_on(
        db, policy, principal):
    # A receipt that left the tick empty, and a later withdraw: off today.
    _accept(db, policy, principal, [])
    _withdraw_practice(db, principal)
    assert _state(db, principal)["personalised_practice"] is False

    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO public.processing_policy_purposes (
                    policy_id, purpose_id, lawful_basis_code,
                    required_for_core_service)
                SELECT id, %s, 'contract', true
                  FROM public.processing_policy_versions
                 WHERE status = 'active'""", (PRACTICE,))
        state = _state(conn, principal)
        assert state["practice_in_service"] is True
        assert state["personalised_practice"] is True
        assert state["sensitive_information"] is True
    finally:
        conn.rollback()
        conn.close()
    # Rolled back: the shared policy is exactly as it was.
    assert _state(db, principal)["practice_in_service"] is False


def test_an_objection_is_recorded_once_and_read_for_the_person(
        db, principal):
    other = _one(db, """
        INSERT INTO public.owner_principals (id, user_id)
        VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id""")
    assert _one(db, "SELECT public.has_blind_check_objection_v1(%s)",
                (principal,)) is False
    first = _one(db, """
        SELECT public.record_blind_check_objection_v1(%s, 'test operator')""",
        (principal,))
    again = _one(db, """
        SELECT public.record_blind_check_objection_v1(%s, 'someone else')""",
        (principal,))
    assert first == again
    assert _one(db, """
        SELECT count(*) FROM public.blind_check_objections
         WHERE acquisition_principal_id = %s""", (principal,)) == 1
    assert _one(db, "SELECT public.has_blind_check_objection_v1(%s)",
                (principal,)) is True
    assert _one(db, "SELECT public.has_blind_check_objection_v1(%s)",
                (other,)) is False


def _guest_claimed_by(db, account):
    guest = _one(db, """
        INSERT INTO public.owner_principals (id, guest_secret_hash)
        VALUES (gen_random_uuid(), %s) RETURNING id""", (uuid.uuid4().hex,))
    _one(db, """
        INSERT INTO public.owner_claim_events (
            source_owner_principal_id, target_owner_principal_id,
            claimed_user_id, claim_proof_hash, idempotency_key,
            source_created_at)
        SELECT %s, %s, user_id, %s, %s, now()
          FROM public.owner_principals WHERE id = %s RETURNING id""",
        (guest, account, "a" * 64, f"claim-{uuid.uuid4()}", account))
    return guest


@pytest.mark.parametrize("objects_as", ["account", "guest"])
def test_an_objection_under_one_principal_counts_for_the_whole_person(
        db, principal, objects_as):
    """A Take recorded as a guest who later signed up is the same person:
    the objection read walks claim links both ways, so an objection given
    under either principal is found from the other."""
    guest = _guest_claimed_by(db, principal)
    objector, sampled = ((principal, guest) if objects_as == "account"
                         else (guest, principal))
    _one(db, "SELECT public.record_blind_check_objection_v1(%s, 'test')",
         (objector,))
    assert _one(db, "SELECT public.has_blind_check_objection_v1(%s)",
                (sampled,)) is True


def test_the_purge_can_delete_an_objection_while_the_principal_stays(
        db, principal):
    """The account purge deletes the objection and keeps owner_principals as
    deletion evidence; ON DELETE RESTRICT guards only the principal."""
    _one(db, "SELECT public.record_blind_check_objection_v1(%s, 'test')",
         (principal,))
    _one(db, """
        DELETE FROM public.blind_check_objections
         WHERE acquisition_principal_id = %s RETURNING 1""", (principal,))
    assert _one(db, "SELECT count(*) FROM public.owner_principals "
                    "WHERE id = %s", (principal,)) == 1
    assert _one(db, "SELECT public.has_blind_check_objection_v1(%s)",
                (principal,)) is False


def test_an_objection_needs_a_person_and_a_recorder(db, principal):
    for args, code in (((str(uuid.uuid4()), "test operator"),
                        "PROCESSING_PRINCIPAL_UNRESOLVED"),
                       ((principal, "  "),
                        "BLIND_CHECK_OBJECTION_RECORDER_REQUIRED")):
        with pytest.raises(psycopg2.Error) as error:
            _one(db, "SELECT public.record_blind_check_objection_v1(%s, %s)",
                 args)
        assert code in str(error.value)


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_browser_roles_cannot_reach_the_objections(db, role):
    for signature in ("public.record_blind_check_objection_v1(uuid, text)",
                      "public.has_blind_check_objection_v1(uuid)"):
        assert _one(db, "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                    (role, signature)) is False
    assert _one(db, """
        SELECT has_table_privilege(%s, 'public.blind_check_objections',
                                   'SELECT')""", (role,)) is False
