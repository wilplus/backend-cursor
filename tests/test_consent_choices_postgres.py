"""A person can change their mind after accepting (0361).

FOUNDER 2026-09-25, locked E1-E5. The acceptance screen promises that the
optional "Personalised practice" tick can be turned off at any time, and that
the sensitive-information consent can be withdrawn, ending recording. These
cases run the real functions in the released lane against a policy with one
optional purpose, and pin what the application relies on:

  * the receipt decides the starting point, and only a later change overrides
    it — never an edit of the receipt;
  * a change is recorded only when it changes something, and a replayed
    request writes nothing;
  * the two choices are independent;
  * a new receipt starts from its own ticks;
  * the record is append-only evidence, and browser roles cannot call it.
"""
from __future__ import annotations

import uuid

import psycopg2
import pytest

from tests import test_optional_consent_postgres as base

# The optional-consent suite's policy (one optional purpose) and helpers.
# Bound as module attributes, which is how pytest finds fixtures, so both
# suites run against the same production-shaped policy.
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


def _accept_later(db, policy, principal, optional):
    """A re-acceptance. The shared helper stamps every receipt with the same
    time, which would make "the newest receipt" a coin toss; a real one is
    always later."""
    return _one(db, """
        SELECT public.accept_phase1_processing_authorization_v2(
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::text[])""",
        (principal, base.POLICY, policy["terms"], policy["privacy"],
         policy["ai"], policy["agree"], "agree_and_continue", True, "PL",
         "en-GB", "test", "2026-09-24T10:00:00Z", f"k-{uuid.uuid4()}",
         optional))


def _state(db, principal):
    return _one(db, "SELECT public.get_phase1_consent_choices_v1(%s)",
                (principal,))


def _set(db, principal, choice, enabled, key=None):
    return _one(db, """
        SELECT public.set_phase1_consent_choice_v1(%s, %s, %s, %s, 'test')""",
        (principal, choice, enabled, key or f"choice-{uuid.uuid4()}"))


def _events(db, principal):
    return _one(db, """
        SELECT count(*) FROM public.processing_consent_choice_events
         WHERE acquisition_principal_id = %s""", (principal,))


def test_without_a_receipt_there_is_nothing_to_change(db, policy, principal):
    assert _state(db, principal)["has_receipt"] is False
    with pytest.raises(psycopg2.Error) as error:
        _set(db, principal, "personalised_practice", False)
    assert "PROCESSING_AUTHORIZATION_REQUIRED" in str(error.value)


def test_the_receipt_is_the_starting_point(db, policy, principal):
    _accept(db, policy, principal, [OPTIONAL])
    state = _state(db, principal)
    assert state["personalised_practice"] is True
    assert state["sensitive_information"] is True
    assert state["optional_purposes"] == [OPTIONAL]


def test_leaving_the_tick_unticked_starts_off(db, policy, principal):
    _accept(db, policy, principal, [])
    assert _state(db, principal)["personalised_practice"] is False


def test_turning_off_and_on_is_recorded_once_each(db, policy, principal):
    _accept(db, policy, principal, [OPTIONAL])
    assert _set(db, principal, "personalised_practice",
                False)["personalised_practice"] is False
    assert _events(db, principal) == 1
    # Off again changes nothing, so it records nothing.
    _set(db, principal, "personalised_practice", False)
    assert _events(db, principal) == 1
    assert _set(db, principal, "personalised_practice",
                True)["personalised_practice"] is True
    assert _events(db, principal) == 2


def test_a_replayed_request_writes_nothing(db, policy, principal):
    _accept(db, policy, principal, [OPTIONAL])
    _set(db, principal, "personalised_practice", False, key="replay-key-1")
    _set(db, principal, "personalised_practice", False, key="replay-key-1")
    assert _events(db, principal) == 1


def test_the_two_choices_are_independent(db, policy, principal):
    _accept(db, policy, principal, [OPTIONAL])
    state = _set(db, principal, "sensitive_information", False)
    assert state["sensitive_information"] is False
    assert state["personalised_practice"] is True
    state = _set(db, principal, "sensitive_information", True)
    assert state["sensitive_information"] is True


def test_a_new_receipt_starts_from_its_own_ticks(db, policy, principal):
    _accept(db, policy, principal, [OPTIONAL])
    _set(db, principal, "personalised_practice", False)
    _set(db, principal, "sensitive_information", False)
    # Accepting again writes a newer receipt; the change belonged to the old
    # one, so the new ticks are what counts.
    _accept_later(db, policy, principal, [OPTIONAL])
    state = _state(db, principal)
    assert state["personalised_practice"] is True
    assert state["sensitive_information"] is True


def test_an_unknown_choice_is_refused(db, policy, principal):
    _accept(db, policy, principal, [OPTIONAL])
    with pytest.raises(psycopg2.Error) as error:
        _set(db, principal, "marketing", False)
    assert "CONSENT_CHOICE_INVALID" in str(error.value)


def test_the_record_is_append_only(db, policy, principal):
    _accept(db, policy, principal, [OPTIONAL])
    _set(db, principal, "personalised_practice", False)
    for statement in (
        "UPDATE public.processing_consent_choice_events SET event_kind = "
        "'grant' WHERE acquisition_principal_id = %s",
        "DELETE FROM public.processing_consent_choice_events "
        "WHERE acquisition_principal_id = %s",
    ):
        with pytest.raises(psycopg2.Error) as error:
            _one(db, statement, (principal,))
        assert "append-only" in str(error.value)


def test_browser_roles_cannot_call_either_function(db):
    for role in ("anon", "authenticated"):
        for signature in (
            "public.get_phase1_consent_choices_v1(uuid)",
            "public.set_phase1_consent_choice_v1(uuid,text,boolean,text,text)",
        ):
            assert _one(db, "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                        (role, signature)) is False


def _withdrawn_since(db, since):
    return {str(r[0]) for r in base._rows(db, """
        SELECT acquisition_principal_id
          FROM public.list_recent_practice_withdrawals_v1(%s, 1000)""",
        (since,))}


def test_the_backstop_lists_only_a_standing_turn_off(db, policy):
    turned_off, turned_back, never_ticked = (
        _one(db, """INSERT INTO public.owner_principals (id, user_id)
                    VALUES (gen_random_uuid(), gen_random_uuid())
                    RETURNING id""") for _ in range(3))
    _accept(db, policy, turned_off, [OPTIONAL])
    _set(db, turned_off, "personalised_practice", False)
    _accept(db, policy, turned_back, [OPTIONAL])
    _set(db, turned_back, "personalised_practice", False)
    _set(db, turned_back, "personalised_practice", True)
    _accept(db, policy, never_ticked, [])
    listed = _withdrawn_since(db, "2000-01-01T00:00:00Z")
    assert str(turned_off) in listed
    assert str(turned_back) not in listed
    assert str(never_ticked) not in listed
    # Older than the window: not retried.
    assert str(turned_off) not in _withdrawn_since(db, "2999-01-01T00:00:00Z")
