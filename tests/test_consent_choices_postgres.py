"""
STORY    As a speaker, I want each change of my mind recorded once, as permanent
         evidence that no browser can touch, so that my consent history can be
         trusted.
OUTCOME
  O1  Turning practice off and back on is recorded once each; repeating the
      same choice records nothing.
  O2  The record cannot be edited or deleted.
  O3  Browser roles (anon, authenticated) cannot call the read or change
      functions.
PROVES   O1 -> test_turning_off_and_on_is_recorded_once_each
         O2 -> test_the_record_is_append_only
         O3 -> test_browser_roles_cannot_call_either_function
WHY      Founder 2026-09-25, locked E1-E5 (migration 0361).
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


def _set(db, principal, choice, enabled, key=None):
    return _one(db, """
        SELECT public.set_phase1_consent_choice_v1(%s, %s, %s, %s, 'test')""",
        (principal, choice, enabled, key or f"choice-{uuid.uuid4()}"))


def _events(db, principal):
    return _one(db, """
        SELECT count(*) FROM public.processing_consent_choice_events
         WHERE acquisition_principal_id = %s""", (principal,))


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
