"""
STORY    As a business that buys a model's answers, I want an answer charged
         once however often my call is retried, and my monthly limit never
         passed by two answers arriving together (PIPE-07, PIPE-08, N615
         item 3).
OUTCOME
  O1  The charges and the reserve function are the backend's only: RLS on,
      nothing for a browser role, the function executable by service_role
      alone.
  O2  (PIPE-08) Two reserves for one key at its limit's edge, on two
      connections at once: the second waits on the first's row lock and is
      refused; only one passes. The month counts answers given before the
      migration (ai_model_calls rows with no charge) and not released ones.
  O3  (PIPE-07) The same Idempotency-Key again: "in_flight" while the first
      is reserved, then the first reply once it is answered, nothing new
      reserved; another question with it is a "mismatch"; a released charge
      frees the key for a new try.
PROVES   O1 -> test_the_charges_are_locked_to_the_backend
         O2 -> test_two_answers_at_the_limit_only_one_passes
         O3 -> test_the_same_idempotency_key_is_charged_once
WHY      Migration a_paid_answer_is_charged_once_within_its_limit (0523),
         applied twice in both rehearsal lanes (the reapply is its
         idempotency check).
"""
from __future__ import annotations

import hashlib
import os
import threading
import uuid

import psycopg2
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="disposable confident-moment rehearsal only")
RESERVE = "SELECT outcome, charge_id, reply FROM public.ai_model_answer_reserve(%s, %s, %s, %s)"


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


def _reserve(conn, key, units, once=None, asked=None):
    with conn.cursor() as cur:
        cur.execute(RESERVE, (key, units, once, asked))
        return cur.fetchone()


def _key(db, limit):
    buyer = str(uuid.uuid4())
    _one(db, "INSERT INTO auth.users(id,email) VALUES (%s,%s) RETURNING id", (buyer, f"{buyer}@example.com"))
    model = _one(db, "INSERT INTO public.ai_models(name, owner_id) VALUES ('Job interview coach', %s) "
                     "RETURNING id", (buyer,))
    version = _one(db, "INSERT INTO public.ai_model_versions(model_id, number) VALUES (%s, 1) RETURNING id",
                   (model,))
    key = _one(db, "INSERT INTO public.ai_model_api_keys(model_id, buyer_id, version_id, key_hash, key_tail, "
                   "kind, monthly_limit_units) VALUES (%s,%s,%s,%s,'abcd','live',%s) RETURNING id",
               (model, buyer, version, hashlib.sha256(buyer.encode()).hexdigest(), limit))
    return key, model, version


def test_the_charges_are_locked_to_the_backend(db):
    assert _one(db, "SELECT relrowsecurity FROM pg_class WHERE oid = 'public.ai_model_charges'::regclass")
    fn = "public.ai_model_answer_reserve(uuid, integer, text, text)"
    for role in ("anon", "authenticated"):
        assert _one(db, "SELECT has_table_privilege(%s, 'public.ai_model_charges', 'SELECT')", (role,)) is False
        assert _one(db, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, fn)) is False
    assert _one(db, "SELECT has_function_privilege('service_role', %s, 'EXECUTE')", (fn,)) is True
    assert _one(db, "SELECT prosecdef FROM pg_proc WHERE oid = %s::regprocedure", (fn,)) is False


def test_two_answers_at_the_limit_only_one_passes(db):
    key, model, version = _key(db, 900)
    # 300 billed this month before the migration, 300 reserved since, one released.
    _one(db, "INSERT INTO public.ai_model_calls(key_id, model_id, version_id, price_units, cost_units, "
             "fee_units, founder_units, teachers_units) VALUES (%s,%s,%s,300,60,48,19,173) RETURNING id",
         (key, model, version))
    assert _reserve(db, key, 300)[0] == "reserved"
    released = _reserve(db, key, 300)
    _one(db, "UPDATE public.ai_model_charges SET status = 'released', settled_at = now() WHERE id = %s "
             "RETURNING id", (released[1],))

    first, second = psycopg2.connect(DSN), psycopg2.connect(DSN)
    try:
        assert _reserve(first, key, 300)[0] == "reserved"     # holds the key's row lock, uncommitted
        got: dict = {}
        racer = threading.Thread(target=lambda: got.setdefault("second", _reserve(second, key, 300)))
        racer.start()
        racer.join(timeout=1.0)
        assert racer.is_alive(), "the second reserve must wait for the first"
        first.commit()
        racer.join(timeout=10)
        second.commit()
        assert got["second"][0] == "limit"
    finally:
        first.close()
        second.close()
    assert _one(db, "SELECT count(*) FROM public.ai_model_charges WHERE key_id = %s AND status = 'reserved'",
                (key,)) == 2


def test_the_same_idempotency_key_is_charged_once(db):
    key, _model, _version = _key(db, None)
    asked = hashlib.sha256(b"How do I answer?").hexdigest()
    outcome, charge, _ = _reserve(db, key, 300, "order-7", asked)
    assert outcome == "reserved"
    assert _reserve(db, key, 300, "order-7", asked)[:2] == ("in_flight", charge)
    _one(db, "UPDATE public.ai_model_charges SET status = 'answered', settled_at = now(), "
             "reply = '{\"answer\": \"Say what you learned.\", \"sure\": true, \"version\": 1}' "
             "WHERE id = %s RETURNING id", (charge,))
    again = _reserve(db, key, 300, "order-7", asked)
    assert again == ("replay", charge, {"answer": "Say what you learned.", "sure": True, "version": 1})
    assert _reserve(db, key, 300, "order-7", hashlib.sha256(b"Another?").hexdigest())[0] == "mismatch"
    assert _one(db, "SELECT count(*) FROM public.ai_model_charges WHERE key_id = %s", (key,)) == 1

    outcome, gone, _ = _reserve(db, key, 300, "order-8", asked)
    _one(db, "UPDATE public.ai_model_charges SET status = 'released', settled_at = now() WHERE id = %s "
             "RETURNING id", (gone,))
    retry = _reserve(db, key, 300, "order-8", asked)
    assert retry[0] == "reserved" and retry[1] != gone
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _one(db, "INSERT INTO public.ai_model_charges(key_id, units, idempotency_key) VALUES (%s, 300, "
                 "'order-8') RETURNING id", (key,))
