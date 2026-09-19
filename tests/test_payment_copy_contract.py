"""Payment config and the published Terms must not contradict each other.

WHY THIS EXISTS. Three config-versus-copy contradictions were found in two
days, all by a person looking rather than by anything automatic:

  2026-09-16  OpenAI data-sharing was enabled while the Privacy Policy said we
              do not share content. Ran for an unknown period.
  2026-09-17  CURRENT_TERMS_VERSION said 1.2 while every acceptance in the
              database said 1.0, and no surface asked anyone to re-accept.
  2026-09-17  STRIPE_SECRET_KEY was present in production — so checkout was
              live — while the Terms said "there is no paid plan and we do not
              take payment".

Each one is a setting quietly disagreeing with a published document. Nothing in
the codebase linked the two, so nothing could notice.

THE ORDER MATTERS, AND IT IS THE POINT. Enabling payment is a COPY decision
before it is a CONFIG decision: re-version the Terms first, then set the key.
Doing it the other way round means the product takes money while its own Terms
say it does not — which is the state production was actually in.

MATCHED ON THE SENTENCE, NOT A FLAG. A boolean "payments_enabled" constant
would drift from the published text exactly as CURRENT_TERMS_VERSION drifted
from the published pages. The copy IS the record, so the copy is what gets
read.

WHAT THIS CAN AND CANNOT CATCH. It bites wherever the key is set — a dev box,
a CI job, a readiness script run against production config. It cannot see
production from CI, where the key is absent and this passes trivially. The
durable version of this check is one that runs at boot on the service that
holds the key; that is a live-loop change (a raising check would take
production down the moment someone set the key) and is deliberately not made
here.

Run: python3 -m pytest tests/test_payment_copy_contract.py
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]

#: The Terms as they will ship, used when no policy is registered yet. The
#: draft is the record until register_phase1_policy_v1 has run; after that the
#: served policy wins, because that is what users are shown.
_DRAFT_TERMS = ROOT / "legal" / "phase1-2026.1" / "copy" / "terms-2.0.txt"

#: Claims that the product does not take money. Written as they appear in the
#: copy, matched against whitespace-normalised text because the .txt files are
#: hard-wrapped and every one of these phrases straddles a line break
#: somewhere.
_NO_PAYMENT_CLAIMS = (
    "we do not take payment",
    "we take no payment",
    "do not currently take payment",
    "there is no paid plan",
    "the service is free",
    "we hold no billing data",
    "there is no billing data",
)


def normalised(text: Any) -> str:
    """Lowercased, whitespace-collapsed. Hard-wrapped copy is the reason: a
    claim split across two source lines is the same claim to a reader."""
    if not isinstance(text, str):
        return ""
    return re.sub(r"\s+", " ", text).strip().lower()


def claims_no_payment_is_taken(text: Any) -> bool:
    """Does this copy tell the reader we do not take money?"""
    body = normalised(text)
    return any(claim in body for claim in _NO_PAYMENT_CLAIMS)


def stripe_payment_configured(app_config: Any) -> bool:
    """Is a Stripe key present, i.e. can a user be charged?

    Presence, never the value. STRIPE_SECRET_KEY is what every payment surface
    gates on — credits checkout, tier checkout, arc checkout and the webhook
    all return 503 DISABLED without it — so its presence is the same statement
    as "the till is on".
    """
    return bool((getattr(app_config, "STRIPE_SECRET_KEY", None) or "").strip())


def active_policy_terms_copy(database: Any = None) -> Optional[str]:
    """The Terms text users are actually being shown, or ``None`` when no
    policy is registered.

    ``processing_policy_versions.terms_copy`` is the served text. Any failure
    to reach it returns ``None`` rather than raising: this is a check, and a
    check that explodes when the database is unreachable teaches people to
    delete it.
    """
    try:
        if database is None:
            from services.db import db as database
        policy = database.get_active_processing_policy()
    except Exception:
        return None
    if isinstance(policy, dict):
        copy = policy.get("terms_copy")
        if isinstance(copy, str) and copy.strip():
            return copy
    return None


def terms_text_in_force(database: Any = None) -> str:
    """The served policy when there is one, the draft otherwise."""
    served = active_policy_terms_copy(database)
    if served:
        return served
    return _DRAFT_TERMS.read_text(encoding="utf-8")


class ThePredicates(unittest.TestCase):
    """Both directions, because a one-sided assertion passes forever once the
    condition it watches for stops being reachable."""

    def test_the_old_absolute_claim_is_a_no_payment_claim(self):
        self.assertTrue(claims_no_payment_is_taken(
            "The service is free. There is no paid plan and we do not take "
            "payment."))

    def test_the_approved_replacement_is_still_a_no_payment_claim(self):
        """Deliberate. The new wording says payment is COMING, but it still
        tells today's reader we do not take money — so the gate must still
        fire if the key goes on before the Terms are amended again."""
        self.assertTrue(claims_no_payment_is_taken(
            "WillpowerLab is free to use today, and we do not take payment. We "
            "expect to introduce paid plans in future."))

    def test_a_claim_split_across_lines_still_matches(self):
        """The copy files are hard-wrapped; a matcher defeated by a newline is
        a matcher that passes on the real document."""
        self.assertTrue(claims_no_payment_is_taken(
            "WillpowerLab is free to use today, and we do not take\npayment."))

    def test_copy_that_describes_charging_is_not_a_no_payment_claim(self):
        self.assertFalse(claims_no_payment_is_taken(
            "Plans start at 29 PLN a month. You can cancel at any time and we "
            "will bill you for the current period only."))

    def test_junk_is_not_a_claim(self):
        for value in (None, "", "   ", 42, object()):
            self.assertFalse(claims_no_payment_is_taken(value), repr(value))

    def test_stripe_presence_is_read_as_presence_not_value(self):
        class _C:
            STRIPE_SECRET_KEY = "sk_test_abc"

        class _Empty:
            STRIPE_SECRET_KEY = "   "

        class _Missing:
            pass

        self.assertTrue(stripe_payment_configured(_C))
        self.assertFalse(stripe_payment_configured(_Empty))
        self.assertFalse(stripe_payment_configured(_Missing))


class TheGate(unittest.TestCase):
    """The contradiction itself."""

    def _assert_consistent(self, *, stripe_on: bool, terms: str, where: str):
        if stripe_on and claims_no_payment_is_taken(terms):
            self.fail(
                f"{where}: Stripe payment config is present, so a user can be "
                "charged, but the Terms in force still tell them we do not "
                "take payment.\n\n"
                "Enabling payment is a COPY decision before it is a CONFIG "
                "decision. Re-version the Terms to describe payment, get "
                "founder sign-off, register the policy — THEN set "
                "STRIPE_SECRET_KEY. Doing it the other way round is the state "
                "production was in on 2026-09-17."
            )

    def test_the_contradiction_is_detected_when_it_exists(self):
        """The gate must be capable of failing. A gate only ever exercised in
        the passing direction is decoration."""
        with self.assertRaises(AssertionError):
            self._assert_consistent(
                stripe_on=True,
                terms="The service is free and we do not take payment.",
                where="synthetic",
            )

    def test_payment_config_with_terms_that_describe_payment_is_fine(self):
        self._assert_consistent(
            stripe_on=True,
            terms="Paid plans start at 29 PLN a month.",
            where="synthetic",
        )

    def test_no_payment_config_with_a_no_payment_claim_is_fine(self):
        self._assert_consistent(
            stripe_on=False,
            terms="The service is free and we do not take payment.",
            where="synthetic",
        )

    def test_this_environment_does_not_contradict_the_terms_in_force(self):
        """THE LIVE ONE. Reads the served policy when a policy is registered,
        the shipped draft otherwise, and this process's own config.

        In CI the key is absent and this passes without proving much. Where
        the key IS set — a dev box, or a readiness script run against
        production config — it fails, which is the whole point.
        """
        from config import Config

        self._assert_consistent(
            stripe_on=stripe_payment_configured(Config),
            terms=terms_text_in_force(),
            where="this environment",
        )


class TheDraftIsWhereWeThinkItIs(unittest.TestCase):
    """If the draft moves or is renamed, the gate above silently starts
    reading nothing. Fail loudly instead."""

    def test_the_draft_terms_exist_and_are_not_empty(self):
        self.assertTrue(_DRAFT_TERMS.is_file(), str(_DRAFT_TERMS))
        self.assertGreater(len(_DRAFT_TERMS.read_text(encoding="utf-8")), 500)

    def test_the_draft_still_contains_a_payment_sentence_to_match_on(self):
        """Guards the matcher, not the copy. If a future edit drops every
        phrase in _NO_PAYMENT_CLAIMS, the gate would pass because it found
        nothing to object to — indistinguishable from copy that correctly
        describes payment. This test makes that rewrite a conscious act."""
        body = normalised(_DRAFT_TERMS.read_text(encoding="utf-8"))
        self.assertIn("payment", body)


if __name__ == "__main__":
    unittest.main()
