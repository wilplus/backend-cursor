"""
STORY    As a speaker under a policy where practice is part of the service, I
         want practice on for me whatever I ticked before, and my objection to
         blind checks recorded once, so that the service matches the policy I
         accepted.
OUTCOME
  O1  Under a policy that makes practice required, practice (and personalised
      practice) reads as on even after I had switched it off; under the
      optional policy nothing changes.
  O2  My objection to blind checks is recorded once, however often it is
      sent, and applies only to me.
PROVES   O1 -> test_where_practice_is_part_of_the_service_it_is_on_and_stays_on
         O2 -> test_an_objection_is_recorded_once_and_read_for_the_person
WHY      Founder N55, N66.2 (migration 0454).
"""
from __future__ import annotations

import uuid

import psycopg2
import pytest

from tests import test_optional_consent_postgres as base

DSN = base.DSN
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
