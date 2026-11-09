"""
STORY    As a business that buys a model's answers, and as the teachers who
         earn from them, I want the API's tables to keep only a hash of my
         key, never let a test key bill, never let a sale's split stop adding
         up, and keep what the teachers earned when a buyer leaves (N528,
         N531, N566, N577, N583).
OUTCOME
  O1  The five new tables have RLS on and grant nothing to a browser role;
      ai_models has its price, which is never zero or below.
  O2  The tables refuse what the rules never allow: a key stored as
      anything but a SHA-256 hash, the same key twice, free answers on a
      live key, a billed test answer, a split that does not add up, a
      second version 1, a payout month that is not a month's first day.
  O3  Erasing a buyer deletes their keys and keeps their paid answers with
      no buyer; erasing a model's founder keeps the version with no
      founder; erasing a teacher takes their share and payouts.
PROVES   O1 -> test_the_tables_are_locked_to_the_backend_and_a_price_is_positive
         O2 -> test_the_tables_refuse_what_the_rules_never_allow
         O3 -> test_a_buyers_paid_answers_stay_and_a_teachers_share_goes
WHY      Migration a_business_can_buy_a_model_s_answers (0521), applied
         twice in both rehearsal lanes (the reapply is its idempotency check).
"""
from __future__ import annotations

import hashlib
import os
import uuid

import psycopg2
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="disposable confident-moment rehearsal only")
TABLES = ("ai_model_versions", "ai_model_shares", "ai_model_api_keys", "ai_model_calls", "ai_model_payouts")


@pytest.fixture(scope="module")
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    try:
        yield conn
    finally:
        conn.close()


def _one(db, sql, args=()):
    with db.cursor() as cur:
        cur.execute(sql, args)
        row = cur.fetchone()
        return row[0] if row else None


def _run(db, sql, args=()):
    with db.cursor() as cur:
        cur.execute(sql, args)


def _user(db):
    uid = str(uuid.uuid4())
    _run(db, "INSERT INTO auth.users(id,email) VALUES (%s,%s)", (uid, f"{uid}@example.com"))
    return uid


def _hash():
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()


def _for_sale(db):
    """A model with a released version 1, its founder, and a buyer's key."""
    founder, buyer = _user(db), _user(db)
    model = _one(db, "INSERT INTO public.ai_models(name, owner_id, visibility, status, price_units) "
                     "VALUES ('Job interview coach', %s, 'public', 'ready', 300) RETURNING id", (founder,))
    version = _one(db, "INSERT INTO public.ai_model_versions(model_id, number, status, founder_id, released_at) "
                       "VALUES (%s, 1, 'released', %s, now()) RETURNING id", (model, founder))
    key = _one(db, "INSERT INTO public.ai_model_api_keys(model_id, buyer_id, version_id, key_hash, key_tail, "
                   "kind, monthly_limit_units) VALUES (%s, %s, %s, %s, 'ab12', 'live', 900) RETURNING id",
               (model, buyer, version, _hash()))
    return founder, buyer, model, version, key


def test_the_tables_are_locked_to_the_backend_and_a_price_is_positive(db):
    for table in TABLES:
        assert _one(db, "SELECT relrowsecurity FROM pg_class WHERE oid = %s::regclass",
                    (f"public.{table}",)) is True, table
        for role in ("anon", "authenticated"):
            assert _one(db, "SELECT has_table_privilege(%s, %s, 'SELECT')", (role, f"public.{table}")) is False
    _founder, _buyer, model, _version, _key = _for_sale(db)
    with pytest.raises(psycopg2.errors.CheckViolation):
        _run(db, "UPDATE public.ai_models SET price_units = 0 WHERE id = %s", (model,))


def test_the_tables_refuse_what_the_rules_never_allow(db):
    _founder, buyer, model, version, key = _for_sale(db)
    checks = [
        ("INSERT INTO public.ai_model_api_keys(model_id, buyer_id, version_id, key_hash, key_tail) "
         "VALUES (%s, %s, %s, 'wpl_sk_test_plaintext', 'text')", (model, buyer, version)),
        ("INSERT INTO public.ai_model_api_keys(model_id, buyer_id, version_id, key_hash, key_tail, kind, free_left) "
         "VALUES (%s, %s, %s, %s, 'ab12', 'live', 100)", (model, buyer, version, _hash())),
        ("INSERT INTO public.ai_model_calls(model_id, version_id, test, price_units, cost_units, teachers_units) "
         "VALUES (%s, %s, true, 300, 60, 240)", (model, version)),
        ("INSERT INTO public.ai_model_calls(model_id, version_id, price_units, cost_units, fee_units, "
         "founder_units, teachers_units) VALUES (%s, %s, 300, 60, 48, 19, 100)", (model, version)),
        ("INSERT INTO public.ai_model_payouts(version_id, user_id, role, month, units) "
         "VALUES (%s, %s, 'teacher', '2026-11-09', 10)", (version, buyer)),
    ]
    for sql, args in checks:
        with pytest.raises(psycopg2.errors.CheckViolation):
            _run(db, sql, args)
    same = _one(db, "SELECT key_hash FROM public.ai_model_api_keys WHERE id = %s", (key,))
    for sql, args in [
        ("INSERT INTO public.ai_model_api_keys(model_id, buyer_id, version_id, key_hash, key_tail) "
         "VALUES (%s, %s, %s, %s, 'ab12')", (model, buyer, version, same)),
        ("INSERT INTO public.ai_model_versions(model_id, number) VALUES (%s, 1)", (model,)),
    ]:
        with pytest.raises(psycopg2.errors.UniqueViolation):
            _run(db, sql, args)
    _run(db, "INSERT INTO public.ai_model_calls(key_id, buyer_id, model_id, version_id, price_units, "
             "cost_units, fee_units, founder_units, teachers_units) VALUES (%s, %s, %s, %s, 300, 60, 48, 19, 173)",
         (key, buyer, model, version))


def test_a_buyers_paid_answers_stay_and_a_teachers_share_goes(db):
    founder, buyer, model, version, key = _for_sale(db)
    teacher = _user(db)
    _run(db, "INSERT INTO public.ai_model_shares(version_id, user_id, points, answers) VALUES (%s, %s, 3, 3)",
         (version, teacher))
    _run(db, "INSERT INTO public.ai_model_payouts(version_id, user_id, role, month, units) "
             "VALUES (%s, %s, 'teacher', '2026-11-01', 173)", (version, teacher))
    call = _one(db, "INSERT INTO public.ai_model_calls(key_id, buyer_id, model_id, version_id, price_units, "
                    "cost_units, fee_units, founder_units, teachers_units) "
                    "VALUES (%s, %s, %s, %s, 300, 60, 48, 19, 173) RETURNING id", (key, buyer, model, version))
    _run(db, "DELETE FROM auth.users WHERE id = %s", (buyer,))
    assert _one(db, "SELECT count(*) FROM public.ai_model_api_keys WHERE id = %s", (key,)) == 0
    assert _one(db, "SELECT buyer_id IS NULL AND key_id IS NULL FROM public.ai_model_calls WHERE id = %s",
                (call,)) is True
    _run(db, "DELETE FROM auth.users WHERE id = %s", (founder,))
    assert _one(db, "SELECT founder_id FROM public.ai_model_versions WHERE id = %s", (version,)) is None
    _run(db, "DELETE FROM auth.users WHERE id = %s", (teacher,))
    assert _one(db, "SELECT count(*) FROM public.ai_model_shares WHERE version_id = %s", (version,)) == 0
    assert _one(db, "SELECT count(*) FROM public.ai_model_payouts WHERE version_id = %s", (version,)) == 0
    assert _one(db, "SELECT count(*) FROM public.ai_model_calls WHERE id = %s", (call,)) == 1
