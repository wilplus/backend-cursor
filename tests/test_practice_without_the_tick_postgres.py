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


def test_accepted_without_the_tick_is_unticked(db, policy, principal):
    _accept(db, policy, principal, [])
    _with_practice(db, principal)
    assert _category(db, principal) == ("unticked", 1)
