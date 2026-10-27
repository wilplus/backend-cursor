"""
STORY    As a speaker, I want never to be charged while the Terms I agreed to
         say the service takes no payment, so that what I agreed to matches
         what happens. (Payments.)
OUTCOME
  O1  The check fails when a Stripe key is set and the Terms in force claim
      that no payment is taken.
  O2  Every Terms copy we ship describes what is paid for (the paid plans;
      from Terms 3.7 the packages, N44) and makes no such claim, so a Stripe
      key may be set (the copy decision came first).
  O3  This process's own config does not contradict the Terms in force.
PROVES   O1 -> test_the_contradiction_is_detected_when_it_exists
         O2 -> test_every_shipped_terms_describes_payment
         O3 -> test_this_environment_does_not_contradict_the_terms_in_force
WHY      2026-09-17: STRIPE_SECRET_KEY was live in production while the Terms
         said "there is no paid plan and we do not take payment".
LIMITS   The check lives in this test file only; production has no boot or
         readiness check for it yet. O3 passes trivially wherever the key is
         absent (CI); it bites on a box that holds the key.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
COPY = ROOT / "legal" / "phase1-2026.1" / "copy"

#: Claims that the product does not take money, as they appear in copy,
#: matched on whitespace-normalised text (the .txt files are hard-wrapped).
_NO_PAYMENT_CLAIMS = (
    "we do not take payment",
    "we take no payment",
    "do not currently take payment",
    "there is no paid plan",
    "the service is free",
    "we hold no billing data",
    "there is no billing data",
)


def _version(path: Path) -> tuple[int, ...]:
    return tuple(int(n) for n in path.stem.removeprefix("terms-").split("."))


SHIPPED_TERMS = sorted(COPY.glob("terms-*.txt"), key=_version)


def normalised(text: Any) -> str:
    return re.sub(r"\s+", " ", text).strip().lower() if isinstance(text, str) else ""


def claims_no_payment_is_taken(text: Any) -> bool:
    body = normalised(text)
    return any(claim in body for claim in _NO_PAYMENT_CLAIMS)


def stripe_payment_configured(app_config: Any) -> bool:
    """Presence, never the value: every payment surface (checkout, webhook)
    answers 503 DISABLED without STRIPE_SECRET_KEY."""
    return bool((getattr(app_config, "STRIPE_SECRET_KEY", None) or "").strip())


def active_policy_terms_copy(database: Any = None) -> Optional[str]:
    """The served Terms (processing_policy_versions.terms_copy), or None when
    no policy is registered or the database cannot be reached."""
    try:
        if database is None:
            from services.db import db as database
        policy = database.get_active_processing_policy()
    except Exception:
        return None
    copy = policy.get("terms_copy") if isinstance(policy, dict) else None
    return copy if isinstance(copy, str) and copy.strip() else None


def terms_text_in_force(database: Any = None) -> str:
    """The served policy when there is one, the newest shipped copy otherwise."""
    return active_policy_terms_copy(database) or SHIPPED_TERMS[-1].read_text(encoding="utf-8")


def contradiction(*, stripe_on: bool, terms: str) -> Optional[str]:
    if stripe_on and claims_no_payment_is_taken(terms):
        return ("Stripe payment config is present, so a user can be charged, but "
                "the Terms in force still say we do not take payment. Re-version "
                "the Terms first, get founder sign-off, register the policy, THEN "
                "set STRIPE_SECRET_KEY.")
    return None


def test_the_contradiction_is_detected_when_it_exists():
    free = "The service is free and we do not take\n payment."
    assert contradiction(stripe_on=True, terms=free)
    assert contradiction(stripe_on=False, terms=free) is None
    assert contradiction(stripe_on=True, terms=SHIPPED_TERMS[-1].read_text()) is None


@pytest.mark.parametrize("terms", SHIPPED_TERMS, ids=lambda p: p.name)
def test_every_shipped_terms_describes_payment(terms):
    body = normalised(terms.read_text(encoding="utf-8"))
    assert ("paid plan" in body or "package" in body) and "payment" in body
    assert not claims_no_payment_is_taken(body)


def test_this_environment_does_not_contradict_the_terms_in_force():
    from config import Config

    problem = contradiction(stripe_on=stripe_payment_configured(Config),
                            terms=terms_text_in_force())
    assert problem is None, problem
