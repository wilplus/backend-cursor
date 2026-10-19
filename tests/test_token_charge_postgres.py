"""
STORY    As a speaker, I want each action charged once at its price and never
         when I cannot cover it, so that my balance is always what I paid for.
         (Critical path: payments.)
OUTCOME
  O1  A charge takes the flat price once: charging the same reference again
      takes nothing and writes no second ledger row.
  O2  Too few tokens: the charge is refused, the balance is untouched and no
      ledger row is written.
  O3  The monthly allowance is spent before the tokens that never expire.
PROVES   O1 -> test_a_reference_is_charged_once
         O2 -> test_too_few_tokens_is_refused_with_nothing_taken
         O3 -> test_the_expiring_tokens_go_first
WHY      add_token_charge_rpc.sql: the four-call Python charge could debit
         twice or debit without a ledger row; the database now decides.

Executed against the real token_charge() (migrations/add_token_charge_rpc.sql)
on the released rehearsal lane, driven by the production Python
services.token_account.charge through the SQL client of
tests/test_account_deletion_starts_postgres.py as service_role. The lane does
not carry the account table, so each case builds it in its own transaction
from its migrations (on a one-column stand-in for v2_student_details, which
predates the migrations directory) and rolls everything back.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import pytest

from services import token_account as ta
from services.token_prices import price_of
from tests.test_account_deletion_starts_postgres import _Database

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ("add_token_pricing.sql", "add_legacy_credit_conversion.sql",
              "a_package_is_bought_once.sql", "add_token_charge_rpc.sql")


@pytest.fixture
def db(monkeypatch):
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS public.v2_student_details (
                               user_id text PRIMARY KEY, credits integer)""")
            for name in MIGRATIONS:
                cur.execute((ROOT / "migrations" / name).read_text())
            cur.execute("""
                GRANT SELECT, INSERT, UPDATE ON public.v2_student_details,
                      public.token_ledger TO service_role;
                GRANT USAGE ON SEQUENCE public.token_ledger_id_seq TO service_role""")
        monkeypatch.setenv("TOKEN_PRICING_ENABLED", "1")
        monkeypatch.setattr(ta, "_rpc_missing_until", 0.0)
        yield conn
    finally:
        conn.rollback()
        conn.close()


def _account(db, *, monthly, bonus=0):
    user = str(uuid.uuid4())
    with db.cursor() as cur:
        cur.execute("""
            INSERT INTO public.v2_student_details (
                user_id, tier, token_balance, bonus_balance, period_start,
                coach_reviews_used)
            VALUES (%s, 'free', %s, %s, %s, 0)""",
            (user, monthly, bonus, datetime.now(timezone.utc)))
    return user


def _balance(db, user):
    with db.cursor() as cur:
        cur.execute("SELECT token_balance, bonus_balance FROM public.v2_student_details "
                    "WHERE user_id = %s", (user,))
        return cur.fetchone()


def _ledger(db, user):
    with db.cursor() as cur:
        cur.execute("SELECT action, delta, ref_id FROM public.token_ledger "
                    "WHERE user_id = %s ORDER BY id", (user,))
        return cur.fetchall()


def test_a_reference_is_charged_once(db):
    user = _account(db, monthly=12_000)
    price = price_of("take_short")

    first = ta.charge(user, "take_short", ref_id="rec-1", database=_Database(db))
    again = ta.charge(user, "take_short", ref_id="rec-1", database=_Database(db))

    assert (first.ok, first.charged, first.balance) == (True, price, 12_000 - price)
    assert (again.ok, again.charged, again.reason) == (True, 0, "already_charged")
    assert _balance(db, user) == (12_000 - price, 0)
    assert _ledger(db, user) == [("take_short", -price, "rec-1")]
    assert ta._rpc_missing_until == 0.0, "fell back to the legacy Python path"


def test_too_few_tokens_is_refused_with_nothing_taken(db):
    user = _account(db, monthly=500)

    result = ta.charge(user, "take_short", ref_id="rec-2", database=_Database(db))

    assert (result.ok, result.charged, result.reason) == (False, 0, "insufficient")
    assert _balance(db, user) == (500, 0)
    assert _ledger(db, user) == []


def test_the_expiring_tokens_go_first(db):
    user = _account(db, monthly=400, bonus=5_000)

    result = ta.charge(user, "take_short", ref_id="rec-3", database=_Database(db))

    assert (result.ok, result.charged) == (True, 1_000)
    assert _balance(db, user) == (0, 4_400)
