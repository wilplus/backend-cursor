"""
STORY    As the founder, I want the database to say correctly who never ticked
         the "Personalised practice" box, so that erasing practice made
         without the tick touches only those people (consent).
OUTCOME
  O1  Accepted without the tick and never turned it on -> `unticked`, the
      only group the erasure script touches.
  O2  Accepted WITH the tick -> `ticked`, even after turning it off later:
      a yes once given protects that person's practice from this erasure.
  O3  Accepted without the tick, then turned it on -> `ticked`.
  O4  Never accepted anything -> `no_receipt`, reported only.
  O5  Browser roles cannot call the function.
PROVES   O1 -> test_accepted_without_the_tick_is_unticked
         O2 -> test_ticked_then_turned_off_is_still_ticked
         O3 -> test_turned_on_after_accepting_is_ticked
         O4 -> test_never_accepted_is_no_receipt
         O5 -> test_browser_roles_cannot_call_it
WHY      Founder 2026-09-25, decision 1 (0363): the tick was recorded and read
         by nothing, so practice was made for people who left it empty.

Runs list_practice_without_the_tick_v1 on the released rehearsal lane,
against the optional-consent suite's policy (one optional purpose: the tick).
"""
from __future__ import annotations

import uuid

import psycopg2
import psycopg2.errors
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


def _with_practice(db, principal) -> str:
    user_id = _one(db, "SELECT user_id FROM public.owner_principals WHERE id = %s",
                   (principal,))
    return str(_one(db, """
        INSERT INTO public.confident_voice_practice (id, owner_user_id, take_session_id)
        VALUES (gen_random_uuid(), %s, gen_random_uuid()) RETURNING id""", (user_id,)))


def _set_tick(db, principal, enabled):
    _one(db, """
        SELECT public.set_phase1_consent_choice_v1(
            %s, 'personalised_practice', %s, %s, 'test')""",
         (principal, enabled, f"choice-{uuid.uuid4()}"))


def _category(db, principal):
    with db.cursor() as cur:
        cur.execute("""
            SELECT category, practice_count
              FROM public.list_practice_without_the_tick_v1()
             WHERE principal_id = %s""", (principal,))
        return cur.fetchone()


def test_accepted_without_the_tick_is_unticked(db, policy, principal):
    _accept(db, policy, principal, [])
    _with_practice(db, principal)
    assert _category(db, principal) == ("unticked", 1)


def test_ticked_then_turned_off_is_still_ticked(db, policy, principal):
    _accept(db, policy, principal, [OPTIONAL])
    _set_tick(db, principal, False)
    _with_practice(db, principal)
    assert _category(db, principal) == ("ticked", 1)


def test_turned_on_after_accepting_is_ticked(db, policy, principal):
    _accept(db, policy, principal, [])
    _set_tick(db, principal, True)
    _with_practice(db, principal)
    assert _category(db, principal) == ("ticked", 1)


def test_never_accepted_is_no_receipt(db, policy, principal):
    _with_practice(db, principal)
    assert _category(db, principal) == ("no_receipt", 1)


def test_browser_roles_cannot_call_it(db):
    for role in ("anon", "authenticated"):
        with db.cursor() as cur:
            cur.execute(f"SET ROLE {role}")
            try:
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                    cur.execute(
                        "SELECT * FROM public.list_practice_without_the_tick_v1()")
            finally:
                cur.execute("RESET ROLE")
