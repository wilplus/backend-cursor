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
``v2_deduct_session_credits`` floors at 0.

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

_ACCOUNT_TABLE = "v2_student_details"
_LEDGER_TABLE = "token_ledger"


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
    if elapsed < 1:
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


def get_account(user_id: str, *, database=None) -> Optional[dict]:
    """Balance + tier + period + coach allowance, period already rolled."""
    row = ensure_period_current(user_id, database=database)
    if not row:
        return None
    tier = normalize_tier(row.get("tier"))
    start = _parse_ts(row.get("period_start")) or _now()
    used = int(row.get("coach_reviews_used") or 0)
    allowed = coach_reviews_for(tier)
    return {
        "balance": int(row.get("token_balance") or 0),
        "tier": tier,
        "period_start": start.isoformat(),
        "period_ends_at": period_end(start).isoformat(),
        "coach_reviews": {"used": used, "allowed": allowed,
                          "remaining": max(0, allowed - used)},
    }


# ── Charging ─────────────────────────────────────────────────────────

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

    balance = int(acct.get("token_balance") or 0)
    tier = normalize_tier(acct.get("tier"))

    if action in COACH_ACTIONS:
        used = int(acct.get("coach_reviews_used") or 0)
        allowed = coach_reviews_for(tier)
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
        upd = (
            db.client.table(_ACCOUNT_TABLE)
            .update({"token_balance": new_balance})
            .eq("user_id", str(user_id))
            .eq("token_balance", balance)          # CAS against concurrent spend
            .execute()
        )
        if not upd.data:
            # Lost the race. Re-read and retry ONCE; a second loss means heavy
            # concurrency on one user, where letting the action through is the
            # right failure (fail open).
            acct2 = ensure_period_current(user_id, database=db)
            bal2 = int((acct2 or {}).get("token_balance") or 0)
            if price and bal2 < price:
                return ChargeResult(False, 0, bal2, "insufficient", action)
            new_balance = max(0, bal2 - price)
            upd2 = (
                db.client.table(_ACCOUNT_TABLE)
                .update({"token_balance": new_balance})
                .eq("user_id", str(user_id))
                .eq("token_balance", bal2)
                .execute()
            )
            if not upd2.data:
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


def set_tier(user_id: str, tier: str, *, period_start: Optional[datetime] = None,
             ref_id: Optional[str] = None, database=None) -> Optional[dict]:
    """Move a user onto a tier and grant it immediately. Called by the Stripe
    webhook, never by user-facing code.

    Re-anchors the period to the Stripe billing date so the app's renewal and
    the card charge stay on the same day — otherwise a user is billed on the 3rd
    and re-granted on the 17th, and every support question becomes "when do my
    tokens come back?".
    """
    db = database or _db()
    tier = normalize_tier(tier)
    start = period_start or _now()
    granted = grant_for(tier)
    try:
        db.client.table(_ACCOUNT_TABLE).upsert({
            "user_id": str(user_id),
            "tier": tier,
            "token_balance": granted,
            "period_start": start.isoformat(),
            "coach_reviews_used": 0,
        }).execute()
    except Exception as e:
        logger.error("token_account: set_tier failed user=%s tier=%s err=%s",
                     user_id, tier, e)
        return None
    _ledger(user_id, granted, granted, "tier_change", ref_id=ref_id, tier=tier,
            database=db)
    logger.info("token_account: tier set user=%s tier=%s granted=%d",
                user_id, tier, granted)
    return {"tier": tier, "balance": granted,
            "period_start": start.isoformat()}


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
