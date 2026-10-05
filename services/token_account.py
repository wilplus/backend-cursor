"""willab — the user's token balance: monthly period, charging, coach caps.

docs/PRICING-TOKENS-PLAN.md §7 Phase 1. Schema: migrations/add_token_pricing.sql.

Distinct from ``services/llm_usage.py``, which records what WE pay OpenAI. Two
ledgers, never joined — see services/token_prices.py for why that separation is
load-bearing rather than tidy.

THE TWO FENCES THIS MODULE IMPLEMENTS
-------------------------------------
**Fail open on the live loop.** ``charge()`` deducts SOFTLY: the balance floors
at zero and the caller is told what happened, but nothing here can abort a
recording, drop a transcript, or fail analysis. Callers on the F1 path gate at
the START of an action and then run to completion regardless. Precedent already
in this codebase — ``v2_charge_lab_credits_once`` deducts softly and
the retired per-session decrement floored at 0.

**Flat published prices.** Every number comes from ``token_prices``. Nothing
here inspects what an action actually cost us.

THE MONTHLY RESET IS LAZY — THERE IS NO CRON
--------------------------------------------
``ensure_period_current`` runs at the top of every read and every charge. A
scheduled grant job would be the obvious design and the wrong one: it fails
SILENTLY (nobody notices a grant that did not happen until a user complains they
have no tokens), it needs its own Railway service, and this repo has a standing
habit of infrastructure that was specified and never wired. Lazy reset is
self-healing — a process down for three months rolls the period forward
correctly on the next read.

Three rules, each of which is a bug if broken:
  * **JUMP, never loop.** Four dormant months advance period_start by four
    months and grant ONCE. Looping would hand returning users a windfall.
  * **SET, never add.** Adding is rollover, which the founder ruled out; on Max
    three quiet months would bank 4.5M tokens.
  * **CAS on period_start.** Two concurrent requests can both observe a stale
    period; the conditional UPDATE means exactly one wins.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from services.token_prices import (
    COACH_ACTIONS,
    DEFAULT_TIER,
    PRICE_VERSION,
    coach_reviews_for,
    grant_for,
    normalize_tier,
    price_of,
)

logger = logging.getLogger(__name__)

#: Contract §8 (founder 2026-10-05, "Packages"; N44): no billing periods. The
#: monthly roll below re-granted the tier's tokens every month, the free grant
#: included; with this off the free grant lands once, at seeding, and a
#: balance only grows by a package or an operator grant. The roll is kept
#: behind this one switch rather than deleted, so its tests still describe it.
PERIOD_RESET_ENABLED = False

_ACCOUNT_TABLE = "v2_student_details"
_LEDGER_TABLE = "token_ledger"

# The Postgres function that performs a charge as ONE transaction.
# migrations/add_token_charge_rpc.sql — see _charge_atomic below.
_CHARGE_RPC = "token_charge"

# Sentinel: the function is not installed on this database, so the caller
# should run the legacy multi-call path. Distinct from "the function ran and
# refused the charge" and from "the function errored", which must NOT fall back
# — retrying a charge that may have already committed is how you double-bill.
_RPC_MISSING = object()

# Negative cache. Once we learn the function is absent, stop paying a failed
# round trip on every charge — but re-probe periodically so running the
# migration takes effect WITHOUT a redeploy. "Merged on main" never means "run
# in prod" in this repo; the founder applies migrations by hand.
_RPC_RECHECK_SECONDS = 600.0
_rpc_missing_until: float = 0.0


class ChargeResult:
    """What a charge did. Never an exception — callers on the F1 path branch on
    ``ok`` and carry on either way."""

    __slots__ = ("ok", "charged", "balance", "reason", "action")

    def __init__(self, ok: bool, charged: int, balance: int,
                 reason: str = "", action: str = ""):
        self.ok = ok
        self.charged = charged
        self.balance = balance
        self.reason = reason
        self.action = action

    def as_dict(self) -> dict:
        return {"ok": self.ok, "charged": self.charged,
                "balance": self.balance, "reason": self.reason,
                "action": self.action}

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return (f"ChargeResult(ok={self.ok}, charged={self.charged}, "
                f"balance={self.balance}, reason={self.reason!r})")


def enabled() -> bool:
    """Default OFF, unlike the Phase 0 cost ledger.

    Phase 0 only observed; this can refuse a user's action, so it ships dark and
    is turned on deliberately once the FE can render a balance."""
    return (os.getenv("TOKEN_PRICING_ENABLED") or "0").strip().lower() \
        in ("1", "true", "yes")


# ── Period arithmetic ────────────────────────────────────────────────

def _parse_ts(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        s = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _add_months(dt: datetime, months: int) -> datetime:
    """Calendar-month addition, clamping the day.

    Jan 31 + 1 month = Feb 28/29, not Mar 3. Naive 30-day arithmetic would drift
    a user's renewal date backwards through the year — by month seven someone
    who signed up on the 31st would be renewing in the previous month."""
    if months <= 0:
        return dt
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    # Last day of the target month, found by stepping back from the 1st of the
    # month after it.
    first_next = datetime(year + (month // 12), month % 12 + 1, 1,
                          tzinfo=dt.tzinfo)
    last_day = (first_next - timedelta(days=1)).day
    return dt.replace(year=year, month=month, day=min(dt.day, last_day))


def months_elapsed(start: datetime, now: datetime) -> int:
    """Whole calendar months between start and now. Never negative."""
    if now <= start:
        return 0
    months = (now.year - start.year) * 12 + (now.month - start.month)
    if _add_months(start, months) > now:
        months -= 1
    return max(0, months)


def period_end(start: datetime) -> datetime:
    return _add_months(start, 1)


# ── Account read + lazy reset ────────────────────────────────────────

def _db():
    from services.db import db
    return db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_period_current(user_id: str, *, database=None) -> Optional[dict]:
    """Load the account, rolling the monthly period forward if it has elapsed.

    Returns the account dict, or None when it cannot be read at all. Callers on
    the F1 path treat None as "no metering this turn" and continue — a balance
    we cannot read must never block a recording.
    """
    if not user_id:
        return None
    db = database or _db()
    try:
        res = (
            db.client.table(_ACCOUNT_TABLE)
            .select("user_id, tier, token_balance, period_start, "
                    "coach_reviews_used")
            .eq("user_id", str(user_id))
            .execute()
        )
        rows = res.data or []
    except Exception as e:
        logger.warning("token_account: read failed user=%s err=%s", user_id, e)
        return None

    now = _now()
    if not rows:
        return _seed(user_id, now, database=db)

    row = rows[0]
    tier = normalize_tier(row.get("tier"))
    start = _parse_ts(row.get("period_start"))

    # Never initialised (pre-migration row, or migration seed skipped it).
    if start is None or row.get("token_balance") is None:
        return _seed(user_id, now, tier=tier, database=db)

    elapsed = months_elapsed(start, now)
    if elapsed < 1 or not PERIOD_RESET_ENABLED:
        row["tier"] = tier
        return row

    new_start = _add_months(start, elapsed)          # JUMP, never loop
    granted = grant_for(tier)                        # SET, never add
    try:
        upd = (
            db.client.table(_ACCOUNT_TABLE)
            .update({
                "period_start": new_start.isoformat(),
                "token_balance": granted,
                "coach_reviews_used": 0,
            })
            .eq("user_id", str(user_id))
            .eq("period_start", row.get("period_start"))   # CAS
            .execute()
        )
        won = bool(upd.data)
    except Exception as e:
        logger.warning("token_account: period roll failed user=%s err=%s",
                       user_id, e)
        row["tier"] = tier
        return row

    if not won:
        # Another request rolled it first. Not an error — re-read and use theirs.
        try:
            res2 = (
                db.client.table(_ACCOUNT_TABLE)
                .select("user_id, tier, token_balance, period_start, "
                        "coach_reviews_used")
                .eq("user_id", str(user_id)).execute()
            )
            if res2.data:
                out = res2.data[0]
                out["tier"] = normalize_tier(out.get("tier"))
                return out
        except Exception:
            pass
        row["tier"] = tier
        return row

    # One grant row per period. ref_id is the period start, so the partial
    # unique index makes a double grant impossible even if two workers raced
    # past the CAS on different connections.
    _ledger(user_id, granted, granted, "period_grant",
            ref_id=new_start.date().isoformat(), tier=tier, database=db)
    logger.info("token_account: period rolled user=%s tier=%s months=%d "
                "granted=%d", user_id, tier, elapsed, granted)
    return {
        "user_id": str(user_id), "tier": tier, "token_balance": granted,
        "period_start": new_start.isoformat(), "coach_reviews_used": 0,
    }


def _seed(user_id: str, now: datetime, *, tier: str = DEFAULT_TIER,
          database=None) -> Optional[dict]:
    """First touch: put the account on the model with a full period."""
    db = database or _db()
    tier = normalize_tier(tier)
    granted = grant_for(tier)
    payload = {
        "user_id": str(user_id),
        "tier": tier,
        "token_balance": granted,
        "period_start": now.isoformat(),
        "coach_reviews_used": 0,
    }
    try:
        db.client.table(_ACCOUNT_TABLE).upsert(payload).execute()
    except Exception as e:
        logger.warning("token_account: seed failed user=%s err=%s", user_id, e)
        return None
    _ledger(user_id, granted, granted, "period_grant",
            ref_id=now.date().isoformat(), tier=tier, database=db)
    return payload


def _read_bonus_balance(user_id: str, *, database=None) -> int:
    """Non-expiring tokens, or 0 if unreadable/unmigrated. Never raises.

    Its own query, deliberately — folding `bonus_balance` into the main account
    select would make the whole balance read fail on a database where
    add_legacy_credit_conversion.sql has not been run yet, and that read is the
    one thing this module works hardest to keep alive. 0 is the correct
    degraded answer: it is exactly today's behaviour."""
    if not user_id:
        return 0
    db = database or _db()
    try:
        res = (
            db.client.table(_ACCOUNT_TABLE)
            .select("bonus_balance")
            .eq("user_id", str(user_id)).limit(1).execute()
        )
        row = (res.data or [{}])[0] or {}
        return max(0, int(row.get("bonus_balance") or 0))
    except Exception as e:
        logger.info("token_account: bonus balance unreadable user=%s (%s)",
                    user_id, type(e).__name__)
        return 0


def _read_coach_review_credits(user_id: str, *, database=None) -> int:
    """Coach reviews bought in packages (0420), or 0 if unreadable or not
    migrated. Its own query, for the reason ``_read_bonus_balance`` gives."""
    if not user_id:
        return 0
    db = database or _db()
    try:
        res = (
            db.client.table(_ACCOUNT_TABLE)
            .select("coach_review_credits")
            .eq("user_id", str(user_id)).limit(1).execute()
        )
        row = (res.data or [{}])[0] or {}
        return max(0, int(row.get("coach_review_credits") or 0))
    except Exception as e:
        logger.info("token_account: coach credits unreadable user=%s (%s)",
                    user_id, type(e).__name__, exc_info=True)
        return 0


def coach_allowance(user_id: str, tier: Optional[str], *, database=None) -> int:
    """The coach reviews a user may have in all: the tier's own (the free
    tier's is 0) plus every review bought in a package. Spent against
    ``coach_reviews_used``, which no longer resets (contract §8)."""
    return coach_reviews_for(tier) + _read_coach_review_credits(
        user_id, database=database)


def get_account(user_id: str, *, database=None) -> Optional[dict]:
    """Balance + tier + period + coach allowance, period already rolled.

    No ``plan`` (founder 2026-10-05, N48.3 Q13 A; contract 50): there are no
    subscriptions, so there is nothing to tell "upgrade" from "manage" by."""
    row = ensure_period_current(user_id, database=database)
    if not row:
        return None
    tier = normalize_tier(row.get("tier"))
    start = _parse_ts(row.get("period_start")) or _now()
    used = int(row.get("coach_reviews_used") or 0)
    allowed = coach_allowance(user_id, tier, database=database)
    monthly = int(row.get("token_balance") or 0)
    bonus = _read_bonus_balance(user_id, database=database)
    return {
        # TOTAL spendable. `balance` keeps meaning "what you can spend right
        # now", so nothing that already reads it needs to change.
        "balance": monthly + bonus,
        # The split matters to the FE and only to the FE: `period_ends_at`
        # applies to `monthly_balance` alone. Rendering one renewal date over a
        # total that is partly non-expiring would tell someone their honoured
        # credits are about to disappear.
        "monthly_balance": monthly,
        "bonus_balance": bonus,
        "tier": tier,
        "period_start": start.isoformat(),
        # Nothing renews (contract §8): no end date to show.
        "period_ends_at": (period_end(start).isoformat()
                           if PERIOD_RESET_ENABLED else None),
        "coach_reviews": {"used": used, "allowed": allowed,
                          "remaining": max(0, allowed - used)},
    }


# ── Charging ─────────────────────────────────────────────────────────

def _spend(db, user_id: str, price: int, monthly: int, bonus: int) -> bool:
    """Deduct ``price``, MONTHLY ALLOWANCE FIRST, then the non-expiring bonus.

    Returns whether the compare-and-swap won.

    The order is the whole point. The monthly allowance is deleted at the next
    roll and the bonus (honoured legacy credits) is not, so spending the bonus
    first would quietly burn the permanent balance while the expiring one
    evaporated unused. Expiring money goes first, always.

    ``bonus_balance`` is written ONLY when some of it is actually being spent.
    Pre-migration the bonus is always 0, so the payload and the CAS are
    byte-identical to what they were before this bucket existed — a database
    without add_legacy_credit_conversion.sql cannot notice this function
    changed.
    """
    from_monthly = min(price, monthly)
    from_bonus = price - from_monthly

    payload = {"token_balance": monthly - from_monthly}
    q = (db.client.table(_ACCOUNT_TABLE)
         .update({**payload, **({"bonus_balance": bonus - from_bonus}
                                if from_bonus else {})})
         .eq("user_id", str(user_id))
         .eq("token_balance", monthly))          # CAS against concurrent spend
    if from_bonus:
        # CAS both columns, or a concurrent bonus spend would be overwritten.
        q = q.eq("bonus_balance", bonus)
    return bool(q.execute().data)


def _rpc_not_found(err: Exception) -> bool:
    """Is this "the function does not exist" rather than "the charge failed"?

    The distinction decides whether we may fall back to the legacy path. Get it
    wrong in the permissive direction and a charge that already COMMITTED gets
    replayed by the fallback — a double debit, which is the exact failure this
    whole change exists to remove. So this matches narrowly and anything it
    does not recognise is treated as a real failure.

    PostgREST reports a missing function as PGRST202 ("Could not find the
    function public.token_charge(...) in the schema cache"); Postgres itself
    reports 42883 / undefined_function.
    """
    code = str(getattr(err, "code", "") or "")
    if code in ("PGRST202", "42883", "404"):
        return True
    low = f"{getattr(err, 'message', '')} {err}".lower()
    return (
        "pgrst202" in low
        or "42883" in low
        or "could not find the function" in low
        or ("does not exist" in low and _CHARGE_RPC in low)
        or ("schema cache" in low and _CHARGE_RPC in low)
    )


def _charge_atomic(db, user_id: str, action: str, price: int, *,
                   ref_id: Optional[str], tier: str, coach_action: bool,
                   coach_allowed: int):
    """One round trip: the whole charge, or none of it.

    Calls migrations/add_token_charge_rpc.sql, which holds a row lock on the
    user's account for the duration and commits the debit, the coach counter
    and the ledger row together. That closes three half-states the four-call
    Python path below cannot:

      * a debit whose ledger row never landed — which silently re-arms the
        idempotency probe and lets a pipeline retry charge the same recording
        twice;
      * two concurrent charges for one ref both passing the probe and both
        debiting, with the unique index quietly dropping the second ledger row;
      * a spent balance with an unmoved coach counter — a free review past a cap
        that is a fence, not a preference.

    Returns a ChargeResult, or ``_RPC_MISSING`` when the migration has not been
    run on this database (the caller then uses the legacy path). Never raises:
    a real RPC failure fails OPEN, same as every other error on this module's
    live-loop path.
    """
    global _rpc_missing_until

    if time.monotonic() < _rpc_missing_until:
        return _RPC_MISSING

    try:
        res = db.client.rpc(_CHARGE_RPC, {
            "p_user_id": str(user_id),
            "p_action": action,
            "p_price": int(price),
            "p_ref_id": str(ref_id) if ref_id is not None else None,
            "p_tier": tier,
            "p_price_version": PRICE_VERSION,
            "p_coach_action": bool(coach_action),
            "p_coach_allowed": int(coach_allowed),
        }).execute()
    except Exception as e:
        if _rpc_not_found(e):
            _rpc_missing_until = time.monotonic() + _RPC_RECHECK_SECONDS
            logger.info(
                "token_account: %s() not installed — using the legacy "
                "non-atomic path (run migrations/add_token_charge_rpc.sql); "
                "re-probing in %.0fs", _CHARGE_RPC, _RPC_RECHECK_SECONDS,
            )
            return _RPC_MISSING
        # The function exists and something went wrong inside it. The
        # transaction rolled back, so nothing was charged — but we must not
        # retry through the legacy path, because "rolled back" is what the
        # error SAYS and a lost response after a successful commit looks
        # identical from here.
        logger.warning("token_account: atomic charge failed user=%s action=%s "
                       "err=%s", user_id, action, e)
        return ChargeResult(True, 0, 0, "write_failed", action)

    payload = getattr(res, "data", None)
    if isinstance(payload, list):            # PostgREST can wrap scalars
        payload = payload[0] if payload else None
    if not isinstance(payload, dict):
        logger.warning("token_account: atomic charge returned %r user=%s",
                       payload, user_id)
        return ChargeResult(True, 0, 0, "write_failed", action)

    return ChargeResult(
        bool(payload.get("ok")),
        int(payload.get("charged") or 0),
        int(payload.get("balance") or 0),
        str(payload.get("reason") or ""),
        action,
    )


def charge(user_id: str, action: str, *, ref_id: Optional[str] = None,
           database=None) -> ChargeResult:
    """Deduct the flat price of ``action``. NEVER raises.

    Soft by design (fence §6.1): the balance floors at zero and ``ok`` reports
    whether it covered the price. A caller on the F1 path may look at ``ok``
    BEFORE starting an action, but once the action is under way it must run to
    completion regardless of what this returned.

    ``ref_id`` makes the charge idempotent for per-arc items — the partial
    unique index on (user_id, action, ref_id) rejects the second insert, which
    is reported as ok with charged=0 ("already paid"), not as an error. Pass
    None for legitimately repeatable actions like chat.

    TWO IMPLEMENTATIONS, ONE CONTRACT
    ---------------------------------
    The charge itself runs in Postgres (``_charge_atomic``) so the debit, the
    coach counter and the ledger row commit as ONE transaction. On a database
    where that migration has not been run yet, ``_charge_legacy`` reproduces
    the old four-round-trip behaviour byte for byte. Both return the same
    ChargeResult; callers cannot tell which ran, and no caller should try.

    ``ensure_period_current`` stays on THIS side of the line. It seeds the
    account and rolls the monthly period, and it has its own CAS and its own
    ledger row — a separate invariant from "charge atomically", and the next
    candidate to move rather than something to bundle in here.
    """
    if not enabled():
        return ChargeResult(True, 0, 0, "disabled", action)
    price = price_of(action)
    db = database or _db()

    acct = ensure_period_current(user_id, database=db)
    if acct is None:
        # Cannot read the account — do not block. Better to give away an action
        # than to fail a recording over a billing lookup.
        logger.warning("token_account: charge skipped (no account) user=%s "
                       "action=%s", user_id, action)
        return ChargeResult(True, 0, 0, "account_unavailable", action)

    tier = normalize_tier(acct.get("tier"))
    coach_action = action in COACH_ACTIONS

    outcome = _charge_atomic(
        db, user_id, action, price, ref_id=ref_id, tier=tier,
        coach_action=coach_action,
        coach_allowed=(coach_allowance(user_id, tier, database=db)
                       if coach_action else 0),
    )
    if outcome is not _RPC_MISSING:
        return outcome

    return _charge_legacy(db, user_id, action, price, ref_id=ref_id, acct=acct)


def _charge_legacy(db, user_id: str, action: str, price: int, *,
                   ref_id: Optional[str], acct: dict) -> ChargeResult:
    """The pre-transaction path, kept VERBATIM for databases without the RPC.

    Four unsynchronised round trips — probe, debit, coach counter, ledger — with
    the half-states catalogued in migrations/add_token_charge_rpc.sql. Nothing
    here is a good idea; it is what shipped, and deleting it before the
    migration is applied everywhere would take charging down instead of making
    it atomic. Delete this once the function is confirmed live in production.
    """
    acct = acct or {}
    monthly = int(acct.get("token_balance") or 0)
    bonus = _read_bonus_balance(user_id, database=db)
    balance = monthly + bonus
    tier = normalize_tier(acct.get("tier"))

    if action in COACH_ACTIONS:
        used = int(acct.get("coach_reviews_used") or 0)
        allowed = coach_allowance(user_id, tier, database=db)
        if used >= allowed:
            # The SECOND limit, and it binds independently of the balance: a Max
            # user with 1.4M tokens can still be out of reviews. Not purchasable
            # past — the cap protects the founder's calendar, and a price ladder
            # on his Tuesday is noise.
            return ChargeResult(False, 0, balance, "coach_cap_reached", action)

    if price and balance < price:
        return ChargeResult(False, 0, balance, "insufficient", action)

    if ref_id is not None:
        already = _already_charged(user_id, action, ref_id, database=db)
        if already:
            return ChargeResult(True, 0, balance, "already_charged", action)

    new_balance = max(0, balance - price)
    try:
        upd = _spend(db, user_id, price, monthly, bonus)
        if not upd:
            # Lost the race. Re-read and retry ONCE; a second loss means heavy
            # concurrency on one user, where letting the action through is the
            # right failure (fail open).
            acct2 = ensure_period_current(user_id, database=db)
            monthly2 = int((acct2 or {}).get("token_balance") or 0)
            bonus2 = _read_bonus_balance(user_id, database=db)
            bal2 = monthly2 + bonus2
            if price and bal2 < price:
                return ChargeResult(False, 0, bal2, "insufficient", action)
            new_balance = max(0, bal2 - price)
            if not _spend(db, user_id, price, monthly2, bonus2):
                logger.warning("token_account: CAS lost twice user=%s "
                               "action=%s — allowing", user_id, action)
                return ChargeResult(True, 0, bal2, "cas_contention", action)
    except Exception as e:
        logger.warning("token_account: charge write failed user=%s action=%s "
                       "err=%s", user_id, action, e)
        return ChargeResult(True, 0, balance, "write_failed", action)

    if action in COACH_ACTIONS:
        _consume_coach_review(user_id, acct, database=db)

    _ledger(user_id, -price, new_balance, action, ref_id=ref_id, tier=tier,
            database=db)
    return ChargeResult(True, price, new_balance, "", action)


ADMIN_ADJUST = "admin_adjust"

# The column `bonus_balance` lives in add_legacy_credit_conversion.sql, which
# this repo's migration ledger has previously claimed to have applied when it
# had not. A grant that fails because the column is absent must say so — the
# fix is a migration, and no amount of retrying the form will find it.
_NO_COLUMN = ("bonus_balance", "does not exist", "42703", "pgrst204")


def _bonus_raw(user_id: str, *, database=None):
    """(value, reason). value is int | None (SQL NULL); reason names the
    failure when the read could not happen at all.

    SEPARATE FROM `_read_bonus_balance`, WHICH CANNOT BE USED HERE. That one
    collapses NULL, a missing column and a genuine zero into the integer 0 —
    correct for a balance READ, where every one of those means "no bonus
    tokens". It is wrong for a compare-and-swap, because `WHERE
    bonus_balance = 0` never matches a NULL row: SQL comparison against NULL
    is NULL, not true. Reading the raw value is what lets the caller pick
    `.is_(…, "null")` over `.eq(…, 0)` and actually match the row it read.
    """
    db = database or _db()
    try:
        res = (
            db.client.table(_ACCOUNT_TABLE)
            .select("bonus_balance")
            .eq("user_id", str(user_id)).limit(1).execute()
        )
    except Exception as e:
        low = str(e).lower()
        if all(s in low for s in ("bonus_balance", "does not exist")) or \
                any(s in low for s in ("42703", "pgrst204")):
            return None, "column_missing"
        logger.warning("token_account: bonus read failed user=%s err=%s",
                       user_id, e)
        return None, "read_failed"
    rows = res.data or []
    if not rows:
        return None, "no_account"
    value = (rows[0] or {}).get("bonus_balance")
    if value is None:
        return None, ""
    try:
        return int(value), ""
    except (TypeError, ValueError):
        return None, ""


def admin_grant(user_id: str, tokens: int, *, ref_id: str,
                database=None) -> dict:
    """Grant non-expiring tokens to one account.

    Returns ``{"ok": bool, "reason": str, "account": dict|None}``. A REASON
    rather than a bare None, because every way this fails needs a different
    human action — run a migration, pick another account, retry — and a panel
    that can only say "could not apply the grant" sends the operator to the
    server logs to find out which.

    THE BUCKET IS `bonus_balance`, NOT `token_balance`, and the difference is
    the whole reason this function exists rather than an UPDATE. The monthly
    roll does `token_balance = grant_for(tier)` — SET, never add — so tokens
    put there are DELETED at the user's next period roll. For a testing top-up
    that is a top-up with a silent expiry date, and for a support gesture it is
    worse: the operator sees it land and the user finds it gone.
    `bonus_balance` is never touched by the roll, and it is spent SECOND, after
    the expiring monthly allowance — the only order that does not quietly burn
    the durable money first.

    IDEMPOTENT ON `ref_id`, checked before the balance moves. The ledger's
    partial unique index (user_id, action, ref_id) would absorb a duplicate
    ROW, but the balance write is a separate statement and the index cannot
    protect it — so a double-submitted form would grant twice and record once,
    which is the exact irreconcilable state `token_charge`'s RPC was written to
    close on the debit side.

    NOT TRANSACTIONAL, and honestly so. The debit path earned a Postgres
    function because it runs on the F1 live loop under concurrency; this runs
    from one operator's browser at human speed. The residual risk is a balance
    write landing while the ledger insert fails, which leaves the account RICHER
    than the audit trail — the safe direction for a grant, and the inverse of
    the debit case. If admin grants ever become automated, this needs the same
    RPC treatment.

    ``tokens`` may be negative (a correction). Never lets the bucket go below
    zero.
    """
    db = database or _db()
    try:
        delta = int(tokens)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "invalid_amount", "account": None}
    if not user_id or delta == 0:
        return {"ok": False, "reason": "invalid_amount", "account": None}
    if _already_charged(user_id, ADMIN_ADJUST, ref_id, database=db):
        logger.info("token_account: admin grant already applied user=%s "
                    "ref=%s", user_id, ref_id)
        return {"ok": True, "reason": "already_applied",
                "account": get_account(str(user_id), database=db)}

    current, why = _bonus_raw(str(user_id), database=db)
    if why:
        return {"ok": False, "reason": why, "account": None}
    new_bonus = max(0, (current or 0) + delta)
    try:
        q = (
            db.client.table(_ACCOUNT_TABLE)
            .update({"bonus_balance": new_bonus})
            .eq("user_id", str(user_id))
        )
        # CAS so a concurrent spend is not overwritten by this grant — and it
        # has to match the value we actually READ. A never-granted account
        # holds SQL NULL, and `.eq(col, 0)` does not match NULL, so the
        # zero-that-is-really-NULL needs `.is_` or the very first grant on
        # every account silently updates no rows at all.
        q = (q.is_("bonus_balance", "null") if current is None
             else q.eq("bonus_balance", current))
        res = q.execute()
    except Exception as e:
        low = str(e).lower()
        reason = ("column_missing"
                  if all(s in low for s in ("bonus_balance", "does not exist"))
                  else "write_failed")
        logger.warning("token_account: admin grant failed user=%s reason=%s "
                       "err=%s", user_id, reason, e)
        return {"ok": False, "reason": reason, "account": None}
    if not (res.data or []):
        # Zero rows matched: the row moved under us, or there is no account
        # row yet. Never retried blind — a second attempt with a stale read
        # is how a grant lands twice.
        logger.warning("token_account: admin grant matched no row user=%s "
                       "(raced or no account)", user_id)
        return {"ok": False, "reason": "no_row", "account": None}

    acct = get_account(str(user_id), database=db)
    _ledger(str(user_id), new_bonus - (current or 0),
            int((acct or {}).get("balance") or new_bonus),
            ADMIN_ADJUST, ref_id=ref_id,
            tier=(acct or {}).get("tier"), database=db)
    return {"ok": True, "reason": "", "account": acct}


PACKAGE_PURCHASE = "package_purchase"


def package_grant(user_id: str, *, tokens: int, coach_reviews: int,
                  ref_id: str, package: str, database=None) -> dict:
    """Credit one paid package (contract §8; N44): its tokens into
    ``bonus_balance``, which never resets, and its coach reviews into
    ``coach_review_credits`` (0420). Called by the Stripe webhook only, after
    ``services.token_packages`` checked the session is paid for exactly this
    package's price.

    Returns ``{"ok": bool, "reason": str}``. IDEMPOTENT ON ``ref_id`` (the
    Checkout Session id): a delivery Stripe repeats finds the ledger row and
    grants nothing. Each balance write is a compare-and-set on the value read,
    so a concurrent spend is never overwritten; a lost race answers
    ``no_row`` and the webhook asks Stripe to deliver again.
    """
    db = database or _db()
    try:
        tokens = max(0, int(tokens))
        coach_reviews = max(0, int(coach_reviews))
    except (TypeError, ValueError):
        return {"ok": False, "reason": "invalid_amount"}
    if not user_id or not ref_id or (tokens == 0 and coach_reviews == 0):
        return {"ok": False, "reason": "invalid_amount"}
    if _already_charged(user_id, PACKAGE_PURCHASE, ref_id, database=db):
        return {"ok": True, "reason": "already_applied"}
    # A buyer who never opened the wallet has no account row yet.
    if ensure_period_current(str(user_id), database=db) is None:
        return {"ok": False, "reason": "account_unavailable"}

    current, why = _bonus_raw(str(user_id), database=db)
    if why:
        return {"ok": False, "reason": why}
    credits = _read_coach_review_credits(str(user_id), database=db)
    update: dict = {"bonus_balance": (current or 0) + tokens}
    if coach_reviews:
        update["coach_review_credits"] = credits + coach_reviews
    try:
        q = (db.client.table(_ACCOUNT_TABLE).update(update)
             .eq("user_id", str(user_id)))
        q = (q.is_("bonus_balance", "null") if current is None
             else q.eq("bonus_balance", current))
        if coach_reviews:
            q = q.eq("coach_review_credits", credits)
        res = q.execute()
    except Exception as e:
        logger.warning("token_account: package grant failed user=%s ref=%s "
                       "err=%s", user_id, ref_id, e, exc_info=True)
        return {"ok": False, "reason": "write_failed"}
    if not (res.data or []):
        logger.warning("token_account: package grant matched no row user=%s "
                       "ref=%s (raced)", user_id, ref_id)
        return {"ok": False, "reason": "no_row"}

    acct = get_account(str(user_id), database=db)
    _ledger(str(user_id), tokens,
            int((acct or {}).get("balance") or update["bonus_balance"]),
            PACKAGE_PURCHASE, ref_id=ref_id, tier=package, database=db)
    logger.info("token_account: package granted user=%s package=%s tokens=%d "
                "reviews=%d ref=%s", user_id, package, tokens, coach_reviews,
                ref_id)
    return {"ok": True, "reason": ""}


def _already_charged(user_id: str, action: str, ref_id: str, *,
                     database=None) -> bool:
    db = database or _db()
    try:
        res = (
            db.client.table(_LEDGER_TABLE)
            .select("id")
            .eq("user_id", str(user_id)).eq("action", action)
            .eq("ref_id", str(ref_id)).limit(1).execute()
        )
        return bool(res.data)
    except Exception:
        # Unknown → assume not charged. Double-charging is worse than the
        # occasional free re-open, and the unique index is the real guard.
        return False


def _consume_coach_review(user_id: str, acct: dict, *, database=None) -> None:
    db = database or _db()
    used = int(acct.get("coach_reviews_used") or 0)
    try:
        (
            db.client.table(_ACCOUNT_TABLE)
            .update({"coach_reviews_used": used + 1})
            .eq("user_id", str(user_id))
            .eq("coach_reviews_used", used)          # CAS
            .execute()
        )
    except Exception as e:
        logger.warning("token_account: coach counter failed user=%s err=%s",
                       user_id, e)


def _ledger(user_id: str, delta: int, balance_after: int, action: str, *,
            ref_id: Optional[str] = None, tier: Optional[str] = None,
            database=None) -> None:
    """Append to the audit trail. Best-effort — a ledger write must never undo
    a balance change the user already saw."""
    db = database or _db()
    try:
        db.client.table(_LEDGER_TABLE).insert({
            "user_id": str(user_id),
            "delta": int(delta),
            "balance_after": int(balance_after),
            "action": action,
            "ref_id": str(ref_id) if ref_id is not None else None,
            "price_version": PRICE_VERSION,
            "tier": tier,
        }).execute()
    except Exception as e:
        # A duplicate here is the unique index doing its job on a raced grant
        # or re-open — expected, not a fault.
        logger.info("token_account: ledger insert skipped action=%s user=%s "
                    "(%s)", action, user_id, type(e).__name__)


def charged_actions_for_ref(user_id: str, ref_id: str, *,
                            database=None) -> set:
    """Which once-per-ref actions this user has ALREADY paid for on ``ref_id``.

    One indexed query, no pagination, no charge. Exists so the FE can price a
    control correctly before rendering it: a per-arc action costs its price the
    first time and nothing after, so a static label would be right once and
    wrong every time thereafter.

    Scoped to ``user_id``, so it can only ever report what THIS user was
    charged — an arc they do not own simply comes back empty rather than
    leaking that it exists.

    Returns an empty set on any failure. The caller renders "no price" for
    unknown, which is the safe direction: showing nothing beats showing a
    number that might be wrong.
    """
    if not user_id or not ref_id:
        return set()
    db = database or _db()
    try:
        res = (
            db.client.table(_LEDGER_TABLE)
            .select("action")
            .eq("user_id", str(user_id))
            .eq("ref_id", str(ref_id))
            .execute()
        )
        return {r.get("action") for r in (res.data or []) if r.get("action")}
    except Exception as e:
        logger.warning("token_account: charged_actions failed user=%s ref=%s "
                       "err=%s", user_id, ref_id, e)
        return set()


def history(user_id: str, *, limit: int = 50, before_id: Optional[int] = None,
            database=None) -> list:
    """Ledger rows, newest first. Read-only."""
    db = database or _db()
    try:
        q = (
            db.client.table(_LEDGER_TABLE)
            .select("id, delta, balance_after, action, ref_id, tier, created_at")
            .eq("user_id", str(user_id))
            .order("id", desc=True)
            .limit(max(1, min(int(limit or 50), 200)))
        )
        if before_id:
            q = q.lt("id", int(before_id))
        return q.execute().data or []
    except Exception as e:
        logger.warning("token_account: history failed user=%s err=%s",
                       user_id, e)
        return []
