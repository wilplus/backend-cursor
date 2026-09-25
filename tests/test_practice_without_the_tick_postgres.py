"""Who counts as never having ticked the box (0363, founder decision 1).

Runs list_practice_without_the_tick_v1 on the released lane, against the
optional-consent suite's policy (one optional purpose: the tick). Pinned:

  * accepted without the tick, never turned on → `unticked` (the only group
    the erasure script touches);
  * accepted WITH the tick → `ticked`, even if they later turned it off;
  * accepted without it, then turned it on → `ticked`;
  * never accepted anything → `no_receipt`, reported only;
  * the function lists, and browser roles cannot call it.
"""
from __future__ import annotations

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


def _with_practice(db, principal) -> str:
    user_id = _one(db, "SELECT user_id FROM public.owner_principals WHERE id = %s",
                   (principal,))
    return str(_one(db, """
        INSERT INTO public.confident_voice_practice (id, owner_user_id, take_session_id)
        VALUES (gen_random_uuid(), %s, gen_random_uuid()) RETURNING id""", (user_id,)))


def _category(db, principal):
    with db.cursor() as cur:
        cur.execute("""
            SELECT category, practice_count
              FROM public.list_practice_without_the_tick_v1()
             WHERE principal_id = %s""", (principal,))
        return cur.fetchone()


def _set(db, principal, enabled):
    return _one(db, """
        SELECT public.set_phase1_consent_choice_v1(
            %s, 'personalised_practice', %s, %s, 'test')""",
        (principal, enabled, f"tick-{principal}-{enabled}"))


def test_accepted_without_the_tick_is_unticked(db, policy, principal):
    _accept(db, policy, principal, [])
    _with_practice(db, principal)
    assert _category(db, principal) == ("unticked", 1)


def test_accepted_with_the_tick_is_ticked_even_after_turning_it_off(db, policy, principal):
    _accept(db, policy, principal, [OPTIONAL])
    _with_practice(db, principal)
    _set(db, principal, False)
    assert _category(db, principal)[0] == "ticked"


def test_turning_it_on_later_counts_as_ticked(db, policy, principal):
    _accept(db, policy, principal, [])
    _with_practice(db, principal)
    _set(db, principal, True)
    assert _category(db, principal)[0] == "ticked"


def test_never_accepting_is_reported_not_erased(db, policy, principal):
    _with_practice(db, principal)
    assert _category(db, principal) == ("no_receipt", 1)


def test_someone_without_practice_is_not_listed(db, policy, principal):
    _accept(db, policy, principal, [])
    assert _category(db, principal) is None


def test_browser_roles_cannot_list(db):
    for role in ("anon", "authenticated"):
        with db.cursor() as cur:
            cur.execute(f"SET ROLE {role}")
            try:
                with pytest.raises(psycopg2.Error):
                    cur.execute("SELECT * FROM public.list_practice_without_the_tick_v1()")
            finally:
                db.rollback() if not db.autocommit else None
                cur.execute("RESET ROLE")
